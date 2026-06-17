"""段2d-1 冒烟：备货申请单 STOCK_UP_REQUEST（04b-1）。

经唯一写入路径（execute_transition / execute_command）验证 04b-1：
  1) 阈值分流：amount=19.9万 建单 → DRAFT→PENDING_PM 边走通；同单 DRAFT→PENDING_REVIEW 被边级 hard_rule 拦。
  2) <20万单批：PM 在 PENDING_PM 批准 → APPROVED（PA 无权在该节点推进，节点级 allowed_roles=[PRODUCT_MANAGER]）。
  3) ≥20万会审：amount=20万 建单 → DRAFT→PENDING_REVIEW；进态预生成 PM+FINANCE 两行待签（cosign 标准件）。
  4) 多签放行：仅 PM 签 → APPROVED 被会签集齐校验拦；PM+FINANCE 都签 → APPROVED 放行（一票否决/未集齐均拦）。
  5) 快照：建单 START effect 拍 stock_on_hand（inventory 聚合）+ in_transit_qty（PO 明细在途）。
  6) 业务号：SU-YYMM-001 月度连号。
  7) 字段防火墙：SALES 查 stock_up_request 能看 amount（含税报价口径，§00-8 单上无成本列 → 不遮）。
  8) 架构边界：引擎核心零改；DRAFT 进 PENDING_PM/REVIEW 节点级 allowed_roles 把关。

在 backend/ 下执行（指向干净库 photonteck_p2d1，需先 alembic upgrade head + seed + seed_phase1）:
  DATABASE_URL=postgresql+asyncpg://photonteck:photonteck@localhost:5433/photonteck_p2d1 \
    python -m scripts.smoke_p2d1
"""

import asyncio
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import models as m
from core.database import get_session_factory
from services.commands import execute_command
from services.tools import query_data
from services.workflow import execute_transition


def _check(label, cond):
    print(f"  [{'OK ' if cond else 'FAIL'}] {label}")
    if not cond:
        raise SystemExit(f"冒烟失败: {label}")


def _expected_number(prefix: str) -> str:
    return f"{prefix}-{date.today().strftime('%y%m')}-001"


async def _user(db, uid):
    return (await db.execute(select(m.UserAccount).where(m.UserAccount.id == uid))).scalar_one()


async def main():
    factory = get_session_factory()

    # ============ 0) 取演示用户/主数据 + 建库存与在途锚点（让快照非零）============
    async with factory() as db:
        sales = (await db.execute(select(m.UserAccount).where(m.UserAccount.username == "sales"))).scalar_one()
        pm = (await db.execute(select(m.UserAccount).where(m.UserAccount.username == "pm"))).scalar_one()
        pa = (await db.execute(select(m.UserAccount).where(m.UserAccount.username == "pa"))).scalar_one()
        finance = (await db.execute(select(m.UserAccount).where(m.UserAccount.username == "finance"))).scalar_one()
        customer = (await db.execute(select(m.Customer).where(m.Customer.company_id == sales.company_id))).scalars().first()
        material = (await db.execute(select(m.Material))).scalars().first()
        warehouse = (await db.execute(select(m.Warehouse).where(m.Warehouse.company_id == sales.company_id))).scalars().first()
        supplier = (await db.execute(select(m.Supplier).where(m.Supplier.company_id == sales.company_id))).scalars().first()
        sales_id, pm_id, pa_id, finance_id = sales.id, pm.id, pa.id, finance.id
        company_id = sales.company_id
        customer_id, material_id = customer.id, material.id
        warehouse_id, supplier_id = (warehouse.id if warehouse else None), supplier.id

        # 库存：material 在该公司有 300 在库（快照 stock_on_hand 期望 300）。
        inv = m.Inventory(
            company_id=company_id, material_id=material_id, warehouse_id=warehouse_id,
            batch_number="SU-SMOKE-BATCH", quantity=Decimal("300"), status="AVAILABLE",
            received_date=date.today(),
        )
        db.add(inv)
        await db.flush()

        # 在途：一张 PO（同公司）明细 material 订 200、已收 50 → 在途 150（快照 in_transit_qty 期望 150）。
        po = m.PurchaseOrder(
            company_id=company_id, order_number="SU-SMOKE-PO", supplier_id=supplier_id,
            currency="USD", total_amount=Decimal("0"), po_date=date.today(), status="ORDERED",
        )
        db.add(po)
        await db.flush()
        db.add(m.PurchaseOrderLine(
            purchase_order_id=po.id, line_number=1, material_id=material_id,
            quantity=Decimal("200"), received_quantity=Decimal("50"),
            unit_price=Decimal("1"), total_price=Decimal("200"),
        ))
        await db.commit()

    # ============ 1) <20万：建单 → 阈值分流 → PENDING_PM → PM 单批 APPROVED ============
    print("\n[1] <20万 单批路径 + 快照 + 业务号")
    async with factory() as db:
        u_sales = await _user(db, sales_id)
        created = await execute_transition(
            db, "STOCK_UP_REQUEST", None, u_sales, to_state="START",
            field_updates={
                "requested_by_id": sales_id, "requester_role": "SALES",
                "material_id": material_id, "stockup_quantity": 100,
                "intended_customer_id": customer_id, "signing_company_id": company_id,
                "reason": "客户有囤货需求", "risk_notes": "客户欠款可控",
                "amount": 199000, "currency": "USD",
            },
        )
        _check("SALES 经 execute_transition 建备货单", created.get("success"))
        su1_id = created["doc_id"]

    async with factory() as db:
        su1 = (await db.execute(select(m.StockUpRequest).where(m.StockUpRequest.id == su1_id))).scalar_one()
        _check(f"备货业务号 = {_expected_number('SU')}（实 {su1.request_number}）",
               su1.request_number == _expected_number("SU"))
        _check(f"快照 stock_on_hand=300（实 {su1.stock_on_hand}）", su1.stock_on_hand == Decimal("300.00"))
        _check(f"快照 in_transit_qty=150（实 {su1.in_transit_qty}）", su1.in_transit_qty == Decimal("150.00"))
        _check("建单落初始 START 态", su1.status == "START")

    # START → DRAFT（开始业务录入）。
    async with factory() as db:
        u_sales = await _user(db, sales_id)
        r = await execute_transition(db, "STOCK_UP_REQUEST", su1_id, u_sales, to_state="DRAFT")
        _check("START→DRAFT 开始录入", r.get("success"))

    # ≥20万边对 19.9万单被边级 hard_rule 拦（amount<20万不满足 doc.amount>=200000）。
    async with factory() as db:
        u_sales = await _user(db, sales_id)
        blocked = await execute_transition(db, "STOCK_UP_REQUEST", su1_id, u_sales, to_state="PENDING_REVIEW")
        _check("19.9万走会审边被边级 hard_rule 拦（amount<20万）", not blocked.get("success"))

    # <20万边走通 → PENDING_PM。
    async with factory() as db:
        u_sales = await _user(db, sales_id)
        r = await execute_transition(db, "STOCK_UP_REQUEST", su1_id, u_sales, to_state="PENDING_PM")
        _check("19.9万走 PM 单批边 DRAFT→PENDING_PM", r.get("success"))

    # PA 无权在 PENDING_PM 推进（节点级 allowed_roles=[PRODUCT_MANAGER]）。
    async with factory() as db:
        u_pa = await _user(db, pa_id)
        denied = await execute_transition(db, "STOCK_UP_REQUEST", su1_id, u_pa, to_state="APPROVED")
        _check("PA 无权在 PENDING_PM 批准（节点级 allowed_roles=[PM]）", not denied.get("success"))

    # PM 单批 → APPROVED。
    async with factory() as db:
        u_pm = await _user(db, pm_id)
        r = await execute_transition(db, "STOCK_UP_REQUEST", su1_id, u_pm, to_state="APPROVED")
        _check("PM 单批 PENDING_PM→APPROVED", r.get("success"))
    async with factory() as db:
        su1 = (await db.execute(select(m.StockUpRequest).where(m.StockUpRequest.id == su1_id))).scalar_one()
        _check("单批后状态 = APPROVED", su1.status == "APPROVED")

    # ============ 2) ≥20万：建单 → PENDING_REVIEW → 会签预生成 → 多签放行 ============
    print("\n[2] ≥20万 会审多签路径（PM+FINANCE 都签才放行）")
    async with factory() as db:
        u_pm = await _user(db, pm_id)
        created = await execute_transition(
            db, "STOCK_UP_REQUEST", None, u_pm, to_state="START",
            field_updates={
                "requested_by_id": pm_id, "requester_role": "PRODUCT_MANAGER",
                "material_id": material_id, "stockup_quantity": 500,
                "intended_customer_id": customer_id, "signing_company_id": company_id,
                "reason": "大额战略囤货", "risk_notes": "资金占用大，需财务会签",
                "amount": 200000, "currency": "USD",
            },
        )
        _check("PM 建 ≥20万 备货单", created.get("success"))
        su2_id = created["doc_id"]

    async with factory() as db:
        su2 = (await db.execute(select(m.StockUpRequest).where(m.StockUpRequest.id == su2_id))).scalar_one()
        _check(f"第二张备货号 = SU-...-002（实 {su2.request_number}）",
               su2.request_number == f"SU-{date.today().strftime('%y%m')}-002")

    async with factory() as db:
        u_pm = await _user(db, pm_id)
        r = await execute_transition(db, "STOCK_UP_REQUEST", su2_id, u_pm, to_state="DRAFT")
        _check("START→DRAFT（≥20万单）", r.get("success"))

    # <20万边对 20万单被边级 hard_rule 拦。
    async with factory() as db:
        u_pm = await _user(db, pm_id)
        blocked = await execute_transition(db, "STOCK_UP_REQUEST", su2_id, u_pm, to_state="PENDING_PM")
        _check("20万走单批边被边级 hard_rule 拦（amount>=20万）", not blocked.get("success"))

    # ≥20万边走通 → PENDING_REVIEW，进态预生成 PM+FINANCE 待签行。
    async with factory() as db:
        u_pm = await _user(db, pm_id)
        r = await execute_transition(db, "STOCK_UP_REQUEST", su2_id, u_pm, to_state="PENDING_REVIEW")
        _check("20万走会审边 DRAFT→PENDING_REVIEW", r.get("success"))
    async with factory() as db:
        lines = (await db.execute(select(m.CosignLine).where(
            m.CosignLine.doc_type == "STOCK_UP_REQUEST", m.CosignLine.doc_id == su2_id,
            m.CosignLine.cosign_group == "STOCK_REVIEW",
        ))).scalars().all()
        roles = sorted(ln.required_role for ln in lines)
        _check(f"进会审预生成 PM+FINANCE 两行待签（实 {roles}）", roles == ["FINANCE", "PRODUCT_MANAGER"])
        pm_line_id = next(ln.id for ln in lines if ln.required_role == "PRODUCT_MANAGER")
        fin_line_id = next(ln.id for ln in lines if ln.required_role == "FINANCE")

    # 未签 → 放行被拦。
    async with factory() as db:
        u_pm = await _user(db, pm_id)
        denied = await execute_transition(db, "STOCK_UP_REQUEST", su2_id, u_pm, to_state="APPROVED")
        _check("未签时放行被会签集齐校验拦", not denied.get("success"))

    # 仅 PM 签 → 仍未集齐，放行被拦。
    async with factory() as db:
        u_pm = await _user(db, pm_id)
        sig = await execute_command(db, u_pm, "sign_cosign", {"line_id": pm_line_id, "decision": "AGREE"})
        await db.commit()
        _check("PM 签字落库", sig.get("success"))
    async with factory() as db:
        u_pm = await _user(db, pm_id)
        denied = await execute_transition(db, "STOCK_UP_REQUEST", su2_id, u_pm, to_state="APPROVED")
        _check("仅 PM 单签 → 放行仍被拦（未集齐 FINANCE）", not denied.get("success"))

    # FINANCE 也签 → 集齐 → 放行通过。
    async with factory() as db:
        u_fin = await _user(db, finance_id)
        sig = await execute_command(db, u_fin, "sign_cosign", {"line_id": fin_line_id, "decision": "AGREE"})
        await db.commit()
        _check("FINANCE 签字落库", sig.get("success"))
    async with factory() as db:
        u_pm = await _user(db, pm_id)
        r = await execute_transition(db, "STOCK_UP_REQUEST", su2_id, u_pm, to_state="APPROVED",
                                     field_updates={"draft_po_id": None})
        _check("PM+FINANCE 都签 → 会审放行 PENDING_REVIEW→APPROVED", r.get("success"))
    async with factory() as db:
        su2 = (await db.execute(select(m.StockUpRequest).where(m.StockUpRequest.id == su2_id))).scalar_one()
        _check("会审通过后状态 = APPROVED", su2.status == "APPROVED")

    # ============ 2b) 一票否决：建第三张 → FINANCE 驳回 → 放行被拦 ============
    print("\n[2b] 一票否决（任一 REJECT → 打回）")
    async with factory() as db:
        u_pm = await _user(db, pm_id)
        created = await execute_transition(
            db, "STOCK_UP_REQUEST", None, u_pm, to_state="START",
            field_updates={
                "requested_by_id": pm_id, "requester_role": "PRODUCT_MANAGER",
                "material_id": material_id, "stockup_quantity": 800,
                "intended_customer_id": customer_id, "signing_company_id": company_id,
                "reason": "再囤", "risk_notes": "财务认为欠款过高", "amount": 300000, "currency": "USD",
            },
        )
        su3_id = created["doc_id"]
    async with factory() as db:
        u_pm = await _user(db, pm_id)
        await execute_transition(db, "STOCK_UP_REQUEST", su3_id, u_pm, to_state="DRAFT")
    async with factory() as db:
        u_pm = await _user(db, pm_id)
        await execute_transition(db, "STOCK_UP_REQUEST", su3_id, u_pm, to_state="PENDING_REVIEW")
    async with factory() as db:
        fin_line = (await db.execute(select(m.CosignLine).where(
            m.CosignLine.doc_type == "STOCK_UP_REQUEST", m.CosignLine.doc_id == su3_id,
            m.CosignLine.required_role == "FINANCE",
        ))).scalar_one()
        fin_line3_id = fin_line.id
    async with factory() as db:
        u_fin = await _user(db, finance_id)
        await execute_command(db, u_fin, "sign_cosign", {"line_id": fin_line3_id, "decision": "REJECT", "comment": "欠款过高"})
        await db.commit()
    async with factory() as db:
        u_pm = await _user(db, pm_id)
        denied = await execute_transition(db, "STOCK_UP_REQUEST", su3_id, u_pm, to_state="APPROVED")
        _check("FINANCE 一票否决 → 放行被拦（打回）", not denied.get("success"))

    # ============ 3) 字段防火墙：SALES 查 stock_up_request 能看 amount（含税报价口径）============
    print("\n[3] 字段防火墙（amount 含税报价口径对 SALES 可见）")
    async with factory() as db:
        u_sales = await _user(db, sales_id)
        res = await query_data(db, u_sales, {"table": "stock_up_request", "filters": {"id": su1_id}})
        _check("SALES 有权查 stock_up_request 表", "error" not in res and res.get("count", 0) == 1)
        row = res["data"][0]
        _check(f"SALES 能看到 amount（含税报价口径，实 {row.get('amount')}）", row.get("amount") == 199000.0)
        # 单上无成本/买价列（模型层即不含）→ 防火墙天然满足，不需遮蔽列存在。
        _check("备货单无成本/买价列（模型层不含 unit_cost/buy_price）",
               not any(k in row for k in ("unit_cost", "buy_price", "purchase_cost")))

    print("\n段2d-1 备货申请冒烟全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
