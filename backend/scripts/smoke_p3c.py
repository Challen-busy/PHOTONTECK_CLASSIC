"""段3c 冒烟：客户/销售收尾（客户认证薄+★并行会签复用 / 售后技术工单 / Forecast接单占位 /
特批发货可隐藏模块+★财务特批审 + 功能开关）。

经唯一写入路径（execute_transition / execute_command）验证 PRD 05：
  [1] 客户认证 CUSTOMER_QUALIFICATION：建单取号 QUAL-YYMM-001 + 资料清单/风险审查子表；
      备资料不齐/风险项未判 → 提交被 hard_rule 拦；齐备 → DRAFT→UNDER_COSIGN（★进态预生成
      PA+FINANCE+BOSS 三行待签，复用 cosign 标准件）。
  [2] ★三方并行会签：未签/单签/缺签 → 放行被 cosign 校验器拦；PA+FINANCE+BOSS 全 AGREE →
      UNDER_COSIGN→APPROVED（回写 customer.qualified_code + 写有效期）。
  [3] 一票否决：另起一单 → 任一驳回 → 放行被拦（→REJECTED）。
  [4] 售后技术工单 SERVICE_TICKET：建单取号 ST-YYMM-001 → OPEN→IN_PROGRESS→RESOLVED→CLOSED
      （关闭前 resolution_type/notes/closure_note 必填 hard_rule）；ESCALATED_RMA 旁路可达。
  [5] 特批发货 SPECIAL_SHIPMENT：建单取号 SS-YYMM-001 + 入仓编号明细子表（无 SO）→
      ★FINANCE_SPECIAL_APPROVAL（财务特批审，置 special_approved）→ APPROVED→出库（pending_so=true）→
      SHIPPED_PENDING_SO→（补单 SO 号非空 hard_rule）RECONCILED（抵减在途/pending_so=false）→ CLOSED。
  [6] Forecast 接单占位 CUSTOMER_FORECAST：建单取号 FC-YYMM-001 + 滚动月份子表 → CONFIRMED。
  [7] 功能开关：feature.special_batch_shipment 默认 OFF（per-company 一行，受控隐藏依据）。
  [8] 架构边界：引擎核心零改；会签复用 cosign 标准件（不另造）。

在 backend/ 下执行（指向干净库 photonteck_p3c，需先 alembic upgrade head + seed + seed_phase1）:
  DATABASE_URL=postgresql+asyncpg://photonteck:photonteck@localhost:5433/photonteck_p3c \
    python -m scripts.smoke_p3c
"""

import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import models as m
from core.database import get_session_factory
from services.commands import execute_command
from services.workflow import execute_transition


def _check(label, cond):
    print(f"  [{'OK ' if cond else 'FAIL'}] {label}")
    if not cond:
        raise SystemExit(f"冒烟失败: {label}")


def _ym() -> str:
    return date.today().strftime("%y%m")


async def _user(db, username):
    return (await db.execute(select(m.UserAccount).where(m.UserAccount.username == username))).scalar_one()


async def main():
    factory = get_session_factory()

    # ============ 0) 取演示用户/主数据 ============
    async with factory() as db:
        sa = await _user(db, "sa")
        company_id = sa.company_id
        customer = (await db.execute(
            select(m.Customer).where(m.Customer.company_id == company_id)
        )).scalars().first()
        material = (await db.execute(select(m.Material))).scalars().first()
        customer_id = customer.id
        material_id = material.id

    # 为特批补单勾稽闭环准备一张补单 SO（含同型号明细，便于抵减在途）。
    async with factory() as db:
        u = await _user(db, "sa")
        created = await execute_transition(
            db, "SALES_ORDER", None, u, to_state="START",
            field_updates={"customer_id": customer_id, "currency": "USD"},
        )
        reorder_so_id = created["doc_id"]
    async with factory() as db:
        u = await _user(db, "sa")
        await execute_transition(db, "SALES_ORDER", reorder_so_id, u, to_state="DRAFT")
    async with factory() as db:
        u = await _user(db, "sa")
        await execute_transition(
            db, "SALES_ORDER", reorder_so_id, u, to_state="SALES_MANAGER_REVIEW",
            field_updates={"external_order_no": "PO-CUST-3C", "total_amount": 500},
            sub_updates=[{
                "table": "sales_order_line", "parent_fk": "sales_order_id",
                "fields": {"line_number": 1, "material_id": material_id, "quantity": 50,
                           "unit_price": 10, "total_price": 500},
            }],
        )

    # ============ 1) 客户认证：建单取号 + 资料/风险子表 + 提交闸 ============
    print("\n[1] 客户认证 CUSTOMER_QUALIFICATION：建单取号 + 资料/风险子表 + 提交 hard_rule")
    async with factory() as db:
        u = await _user(db, "sales")
        created = await execute_transition(
            db, "CUSTOMER_QUALIFICATION", None, u, to_state="START",
            field_updates={"customer_id": customer_id, "qualification_type": "NEW_SUPPLIER"},
        )
        _check("销售经 execute_transition 建认证单", created.get("success"))
        qual_id = created["doc_id"]
    async with factory() as db:
        q = (await db.execute(select(m.CustomerQualification).where(m.CustomerQualification.id == qual_id))).scalar_one()
        expected = f"QUAL-{_ym()}-001"
        _check(f"认证单号 = {expected}（实 {q.qualification_number}）", q.qualification_number == expected)

    # START→DRAFT 进录入。
    async with factory() as db:
        u = await _user(db, "sales")
        r = await execute_transition(db, "CUSTOMER_QUALIFICATION", qual_id, u, to_state="DRAFT")
        _check("认证 START→DRAFT 进录入", r.get("success"))

    # 资料不齐（必备项 is_ready=False）+ 风险项未判 → 提交被拦。
    async with factory() as db:
        u = await _user(db, "sales")
        denied = await execute_transition(
            db, "CUSTOMER_QUALIFICATION", qual_id, u, to_state="UNDER_COSIGN",
            field_updates={"qualified_code": "VENDOR-2026-001", "risk_summary": "无重大冲突"},
            sub_updates=[
                {"table": "qualification_doc_line", "parent_fk": "qualification_id",
                 "fields": {"line_number": 1, "doc_item": "营业执照", "is_required": True, "is_ready": False}},
                {"table": "qualification_risk_line", "parent_fk": "qualification_id",
                 "fields": {"line_number": 1, "risk_type": "违约金", "presence": "PENDING"}},
            ],
        )
        _check("必备资料未齐/风险项未判 → 提交会签被 hard_rule 拦", not denied.get("success"))

    # 补齐资料 + 判风险 → 提交进会签。
    async with factory() as db:
        u = await _user(db, "sales")
        r = await execute_transition(
            db, "CUSTOMER_QUALIFICATION", qual_id, u, to_state="UNDER_COSIGN",
            field_updates={"qualified_code": "VENDOR-2026-001", "risk_summary": "无重大冲突"},
            sub_updates=[
                {"table": "qualification_doc_line", "parent_fk": "qualification_id",
                 "fields": {"line_number": 1, "doc_item": "营业执照", "is_required": True, "is_ready": True}},
                {"table": "qualification_risk_line", "parent_fk": "qualification_id",
                 "fields": {"line_number": 1, "risk_type": "违约金", "presence": "ABSENT", "note": "无"}},
            ],
        )
        _check("资料齐+风险已判 → DRAFT→UNDER_COSIGN 提交会签", r.get("success"))

    # 进态预生成 PA+FINANCE+BOSS 三行待签。
    async with factory() as db:
        lines = (await db.execute(select(m.CosignLine).where(
            m.CosignLine.doc_type == "CUSTOMER_QUALIFICATION", m.CosignLine.doc_id == qual_id,
            m.CosignLine.cosign_group == "CERTIFICATION",
        ))).scalars().all()
        roles = sorted(ln.required_role for ln in lines)
        _check(f"★进会签预生成 PA+财务+BOSS 三行待签（实 {roles}）",
               roles == ["BOSS", "FINANCE", "PRODUCT_ASSISTANT"])
        pa_line_id = next(ln.id for ln in lines if ln.required_role == "PRODUCT_ASSISTANT")
        fin_line_id = next(ln.id for ln in lines if ln.required_role == "FINANCE")
        boss_line_id = next(ln.id for ln in lines if ln.required_role == "BOSS")

    # ============ 2) 三方会签：单签/缺签不过，全签才过 ============
    print("\n[2] ★三方会签：单签/缺签拦，PA+财务+BOSS 全 AGREE 才 APPROVED")
    async with factory() as db:
        u = await _user(db, "pa")
        denied = await execute_transition(db, "CUSTOMER_QUALIFICATION", qual_id, u, to_state="APPROVED")
        _check("未签时放行被 cosign 校验拦", not denied.get("success"))

    async with factory() as db:
        u = await _user(db, "pa")
        sig = await execute_command(db, u, "sign_cosign", {"line_id": pa_line_id, "decision": "AGREE"})
        await db.commit()
        _check("PA 签字落库", sig.get("success"))
    async with factory() as db:
        u = await _user(db, "finance")
        sig = await execute_command(db, u, "sign_cosign", {"line_id": fin_line_id, "decision": "AGREE"})
        await db.commit()
        _check("FINANCE 签字落库", sig.get("success"))
    # 缺 BOSS 一签 → 仍不可放行。
    async with factory() as db:
        u = await _user(db, "pa")
        denied = await execute_transition(db, "CUSTOMER_QUALIFICATION", qual_id, u, to_state="APPROVED")
        _check("PA+FINANCE 签、缺 BOSS → 放行仍被拦（未集齐）", not denied.get("success"))

    async with factory() as db:
        u = await _user(db, "boss")
        sig = await execute_command(db, u, "sign_cosign", {"line_id": boss_line_id, "decision": "AGREE"})
        await db.commit()
        _check("BOSS 签字落库", sig.get("success"))
    async with factory() as db:
        u = await _user(db, "pa")
        r = await execute_transition(db, "CUSTOMER_QUALIFICATION", qual_id, u, to_state="APPROVED")
        _check("★集齐 PA+财务+BOSS → UNDER_COSIGN→APPROVED 放行", r.get("success"))
    async with factory() as db:
        q = (await db.execute(select(m.CustomerQualification).where(m.CustomerQualification.id == qual_id))).scalar_one()
        _check("认证通过后状态 = APPROVED", q.status == "APPROVED")
        _check("通过自动写有效期 valid_until", q.valid_until is not None)
        cust = (await db.execute(select(m.Customer).where(m.Customer.id == customer_id))).scalar_one()
        _check("★通过回写 customer.qualified_code", cust.qualified_code == "VENDOR-2026-001")

    # ============ 3) 一票否决：另起一单 → 任一驳回 → 放行被拦 → REJECTED ============
    print("\n[3] 一票否决（任一 REJECT → 打回 REJECTED）")
    async with factory() as db:
        u = await _user(db, "sales")
        created = await execute_transition(
            db, "CUSTOMER_QUALIFICATION", None, u, to_state="START",
            field_updates={"customer_id": customer_id, "qualification_type": "ANNUAL_REVIEW"},
        )
        qual2_id = created["doc_id"]
    async with factory() as db:
        u = await _user(db, "sales")
        await execute_transition(db, "CUSTOMER_QUALIFICATION", qual2_id, u, to_state="DRAFT")
    async with factory() as db:
        u = await _user(db, "sales")
        await execute_transition(
            db, "CUSTOMER_QUALIFICATION", qual2_id, u, to_state="UNDER_COSIGN",
            sub_updates=[
                {"table": "qualification_doc_line", "parent_fk": "qualification_id",
                 "fields": {"line_number": 1, "doc_item": "质量体系", "is_required": True, "is_ready": True}},
                {"table": "qualification_risk_line", "parent_fk": "qualification_id",
                 "fields": {"line_number": 1, "risk_type": "索赔", "presence": "PRESENT", "note": "有索赔条款"}},
            ],
        )
    async with factory() as db:
        fin_line2 = (await db.execute(select(m.CosignLine).where(
            m.CosignLine.doc_type == "CUSTOMER_QUALIFICATION", m.CosignLine.doc_id == qual2_id,
            m.CosignLine.required_role == "FINANCE",
        ))).scalar_one()
        fin_line2_id = fin_line2.id
    async with factory() as db:
        u = await _user(db, "finance")
        await execute_command(db, u, "sign_cosign",
                              {"line_id": fin_line2_id, "decision": "REJECT", "comment": "索赔条款风险高"})
        await db.commit()
    async with factory() as db:
        u = await _user(db, "pa")
        denied = await execute_transition(db, "CUSTOMER_QUALIFICATION", qual2_id, u, to_state="APPROVED")
        _check("FINANCE 一票否决 → 放行被拦", not denied.get("success"))
    async with factory() as db:
        u = await _user(db, "pa")
        r = await execute_transition(db, "CUSTOMER_QUALIFICATION", qual2_id, u, to_state="REJECTED")
        _check("一票否决可走 UNDER_COSIGN→REJECTED 打回", r.get("success"))

    # ============ 4) 售后技术工单：建单 → 全流程 + 关闭闸 + RMA 旁路 ============
    print("\n[4] 售后技术工单 SERVICE_TICKET：OPEN→IN_PROGRESS→RESOLVED→CLOSED（关闭闸）+ RMA 旁路")
    async with factory() as db:
        u = await _user(db, "sales")
        created = await execute_transition(
            db, "SERVICE_TICKET", None, u, to_state="START",
            field_updates={"customer_id": customer_id, "material_id": material_id,
                           "issue_type": "QUALITY", "issue_summary": "客户报器件失效"},
        )
        _check("销售经 execute_transition 建售后工单", created.get("success"))
        st_id = created["doc_id"]
    async with factory() as db:
        st = (await db.execute(select(m.ServiceTicket).where(m.ServiceTicket.id == st_id))).scalar_one()
        expected = f"ST-{_ym()}-001"
        _check(f"工单号 = {expected}（实 {st.ticket_number}）", st.ticket_number == expected)

    # START→OPEN 进提报态。
    async with factory() as db:
        u = await _user(db, "sales")
        r = await execute_transition(db, "SERVICE_TICKET", st_id, u, to_state="OPEN")
        _check("工单 START→OPEN 进提报", r.get("success"))

    # OPEN→IN_PROGRESS（FAE/PM 接单；用 ops 兜底 allowed_roles）。
    async with factory() as db:
        u = await _user(db, "ops")
        r = await execute_transition(
            db, "SERVICE_TICKET", st_id, u, to_state="IN_PROGRESS",
            field_updates={"assignee_id": (await _user(db, "pm")).id, "product_line": "光通信"},
        )
        _check("工单 OPEN→IN_PROGRESS 接单", r.get("success"))

    # IN_PROGRESS→RESOLVED（录处理方式/过程）。
    async with factory() as db:
        u = await _user(db, "pm")
        r = await execute_transition(
            db, "SERVICE_TICKET", st_id, u, to_state="RESOLVED",
            field_updates={"resolution_type": "REMOTE", "resolution_notes": "远程指导客户重置已解决",
                           "quality_verdict": "GOOD"},
        )
        _check("工单 IN_PROGRESS→RESOLVED（远程答疑）", r.get("success"))

    # RESOLVED→CLOSED 前缺 closure_note → 被关闭闸拦。
    async with factory() as db:
        u = await _user(db, "pm")
        denied = await execute_transition(db, "SERVICE_TICKET", st_id, u, to_state="CLOSED")
        _check("缺 closure_note → 关闭被 hard_rule 拦", not denied.get("success"))
    async with factory() as db:
        u = await _user(db, "pm")
        r = await execute_transition(
            db, "SERVICE_TICKET", st_id, u, to_state="CLOSED",
            field_updates={"closure_note": "客户确认解决，关单"},
        )
        _check("补 closure_note → RESOLVED→CLOSED 关单", r.get("success"))

    # RMA 旁路可达（另起一单走 ESCALATED_RMA）。
    async with factory() as db:
        u = await _user(db, "sales")
        created = await execute_transition(
            db, "SERVICE_TICKET", None, u, to_state="START",
            field_updates={"customer_id": customer_id, "material_id": material_id,
                           "issue_summary": "需返厂维修"},
        )
        st2_id = created["doc_id"]
    async with factory() as db:
        u = await _user(db, "sales")
        await execute_transition(db, "SERVICE_TICKET", st2_id, u, to_state="OPEN")
    async with factory() as db:
        u = await _user(db, "ops")
        await execute_transition(db, "SERVICE_TICKET", st2_id, u, to_state="IN_PROGRESS")
    async with factory() as db:
        u = await _user(db, "pm")
        r = await execute_transition(
            db, "SERVICE_TICKET", st2_id, u, to_state="ESCALATED_RMA",
            field_updates={"resolution_type": "VENDOR_REPAIR", "repair_advice": "寄原厂维修"},
        )
        _check("工单 IN_PROGRESS→ESCALATED_RMA 旁路可达", r.get("success"))

    # ============ 5) 特批发货：财务特批审 → 出库待补单 → 补 SO 勾稽 → 关闭 ============
    print("\n[5] 特批发货 SPECIAL_SHIPMENT：★财务特批审 → 待补单 → 补 SO 勾稽（强制勾稽闸）")
    async with factory() as db:
        u = await _user(db, "sa")
        created = await execute_transition(
            db, "SPECIAL_SHIPMENT", None, u, to_state="START",
            field_updates={"customer_id": customer_id, "special_reason": "URGENT"},
        )
        _check("SA 经 execute_transition 建特批发货单", created.get("success"))
        ss_id = created["doc_id"]
    async with factory() as db:
        ss = (await db.execute(select(m.SpecialShipment).where(m.SpecialShipment.id == ss_id))).scalar_one()
        expected = f"SS-{_ym()}-001"
        _check(f"特批发货单号 = {expected}（实 {ss.shipment_number}）", ss.shipment_number == expected)
    async with factory() as db:
        u = await _user(db, "sa")
        await execute_transition(db, "SPECIAL_SHIPMENT", ss_id, u, to_state="DRAFT")

    # 缺风险承诺/补单期限 → 提交被拦。
    async with factory() as db:
        u = await _user(db, "sa")
        denied = await execute_transition(
            db, "SPECIAL_SHIPMENT", ss_id, u, to_state="FINANCE_SPECIAL_APPROVAL",
            field_updates={"special_reason": "URGENT"},
        )
        _check("缺风险承诺/补单期限 → 提交特批审被 hard_rule 拦", not denied.get("success"))

    # 补齐 → 提交财务特批审 + 入仓编号明细。
    async with factory() as db:
        u = await _user(db, "sa")
        r = await execute_transition(
            db, "SPECIAL_SHIPMENT", ss_id, u, to_state="FINANCE_SPECIAL_APPROVAL",
            field_updates={"special_reason": "URGENT", "risk_commitment": "销售总监授权背书",
                           "expected_reorder_date": (date.today() + timedelta(days=30))},
            sub_updates=[{
                "table": "special_shipment_line", "parent_fk": "special_shipment_id",
                "fields": {"line_number": 1, "material_id": material_id,
                           "inbound_code": "PR2606-001", "quantity": 5},
            }],
        )
        _check("特批 DRAFT→FINANCE_SPECIAL_APPROVAL 提交财务特批审", r.get("success"))

    # 非财务角色不能特批放行（节点级 allowed_roles=[FINANCE]）。
    async with factory() as db:
        u = await _user(db, "sales")
        denied = await execute_transition(db, "SPECIAL_SHIPMENT", ss_id, u, to_state="APPROVED")
        _check("非财务角色 → 特批放行被拦（货不能出仓）", not denied.get("success"))

    # 财务特批放行 → APPROVED（置 special_approved）。
    async with factory() as db:
        u = await _user(db, "finance")
        r = await execute_transition(db, "SPECIAL_SHIPMENT", ss_id, u, to_state="APPROVED")
        _check("★FINANCE 特批放行 → APPROVED", r.get("success"))
    async with factory() as db:
        ss = (await db.execute(select(m.SpecialShipment).where(m.SpecialShipment.id == ss_id))).scalar_one()
        _check("特批放行标志 special_approved=True", ss.special_approved is True)

    # APPROVED→SHIPPED_PENDING_SO（出库挂待补单债务）。
    async with factory() as db:
        u = await _user(db, "logistics")
        r = await execute_transition(db, "SPECIAL_SHIPMENT", ss_id, u, to_state="SHIPPED_PENDING_SO")
        _check("特批 APPROVED→SHIPPED_PENDING_SO 出库", r.get("success"))
    async with factory() as db:
        ss = (await db.execute(select(m.SpecialShipment).where(m.SpecialShipment.id == ss_id))).scalar_one()
        _check("出库后挂待补单债务 pending_so=True", ss.pending_so is True)

    # 未填补单 SO → 勾稽被强制勾稽闸拦。
    async with factory() as db:
        u = await _user(db, "sa")
        denied = await execute_transition(db, "SPECIAL_SHIPMENT", ss_id, u, to_state="RECONCILED")
        _check("未填补单 SO → 勾稽被强制勾稽闸（hard_rule）拦", not denied.get("success"))

    # 填补单 SO → 勾稽（回链 SO 明细 + 抵减在途 shipped_quantity + pending_so=false）。
    async with factory() as db:
        u = await _user(db, "sa")
        r = await execute_transition(
            db, "SPECIAL_SHIPMENT", ss_id, u, to_state="RECONCILED",
            field_updates={"reorder_sales_order_id": reorder_so_id},
        )
        _check("填补单 SO → SHIPPED_PENDING_SO→RECONCILED 勾稽", r.get("success"))
    async with factory() as db:
        ss = (await db.execute(select(m.SpecialShipment).where(m.SpecialShipment.id == ss_id))).scalar_one()
        _check("勾稽后清待补单债务 pending_so=False", ss.pending_so is False)
        so_line = (await db.execute(select(m.SalesOrderLine).where(
            m.SalesOrderLine.sales_order_id == reorder_so_id))).scalars().first()
        _check("★勾稽抵减补单 SO 在途（shipped_quantity 累加 5）",
               so_line is not None and float(so_line.shipped_quantity) == 5.0)
        ship_line = (await db.execute(select(m.SpecialShipmentLine).where(
            m.SpecialShipmentLine.special_shipment_id == ss_id))).scalars().first()
        _check("特批明细回链补单 SO 明细 reconciled_so_line_id",
               ship_line is not None and ship_line.reconciled_so_line_id == so_line.id)
    async with factory() as db:
        u = await _user(db, "sa")
        r = await execute_transition(db, "SPECIAL_SHIPMENT", ss_id, u, to_state="CLOSED")
        _check("特批 RECONCILED→CLOSED 闭环", r.get("success"))

    # ============ 6) Forecast 接单占位：建单 + 滚动子表 → CONFIRMED ============
    print("\n[6] Forecast 接单占位 CUSTOMER_FORECAST：建单取号 FC + 滚动月份子表 → CONFIRMED")
    async with factory() as db:
        u = await _user(db, "sa")
        created = await execute_transition(
            db, "CUSTOMER_FORECAST", None, u, to_state="START",
            field_updates={"customer_id": customer_id, "forecast_version": "2026-06 滚动"},
        )
        _check("SA 经 execute_transition 建 Forecast 单", created.get("success"))
        fc_id = created["doc_id"]
    async with factory() as db:
        fc = (await db.execute(select(m.CustomerForecast).where(m.CustomerForecast.id == fc_id))).scalar_one()
        expected = f"FC-{_ym()}-001"
        _check(f"预测单号 = {expected}（实 {fc.forecast_number}）", fc.forecast_number == expected)
    async with factory() as db:
        u = await _user(db, "sa")
        r = await execute_transition(db, "CUSTOMER_FORECAST", fc_id, u, to_state="DRAFT")
        _check("Forecast START→DRAFT 进录入", r.get("success"))
    async with factory() as db:
        u = await _user(db, "sa")
        r = await execute_transition(
            db, "CUSTOMER_FORECAST", fc_id, u, to_state="CONFIRMED",
            field_updates={"source_system": "客户供应商系统", "product_line": "光通信"},
            sub_updates=[{
                "table": "customer_forecast_line", "parent_fk": "customer_forecast_id",
                "fields": {"line_number": 1, "material_id": material_id,
                           "forecast_month": "2026-07", "forecast_qty": 100},
            }],
        )
        _check("Forecast DRAFT→CONFIRMED 存档（滚动子表网格）", r.get("success"))

    # ============ 7) 功能开关：特批发货默认 OFF ============
    print("\n[7] 功能开关 feature.special_batch_shipment 默认 OFF（可隐藏模块依据）")
    async with factory() as db:
        flag = (await db.execute(select(m.FeatureFlag).where(
            m.FeatureFlag.company_id == company_id,
            m.FeatureFlag.flag_key == "feature.special_batch_shipment",
        ))).scalar_one_or_none()
        _check("per-company 存在 feature.special_batch_shipment 开关行", flag is not None)
        _check("特批发货开关默认 OFF（is_enabled=False）", flag is not None and flag.is_enabled is False)

    print("\n段3c 冒烟全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
