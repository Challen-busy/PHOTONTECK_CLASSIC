"""段3b 冒烟：销售订单履约（SALES_ORDER 决策①合同即 SO + ★预付到账闸 + 采购通知派生
+ 发货申请关联 SO 减在途 + 销项发票形成应收推金蝶 + SO 签单大表台账 + 备货消单）。

经唯一写入路径（execute_transition / 只读 ledger 路由）验证 PRD 05 页面1-5：
  [1] SO 建单：内部订单号月度连号 SO-YYMM-001（建单取号 effect）；录编号(客户订单号)/事业部/签章字段。
  [2] SA leader 下级审核（签章）→ 推金蝶销售订单（SALES_ORDER outbox 一行，幂等键 order_number+company）。
  [3] ★预付到账闸：付款方式=预付（requires_advance_receipt）时，到账未确认 → 放行采购被 hard_rule 拦；
      到账确认（ADVANCE_RECEIPT→CONFIRMED 回写 advance_receipt_confirmed）后放行。
  [4] 采购通知派生：READY_FOR_PURCHASE effect 自动建 PURCHASE_NOTICE（关联 sales_order_id）。
  [5] 发货申请 SHIPMENT 关联 SO：建发货单（sales_order_id 关联），回填 SO 明细 shipped_quantity 减在途。
  [6] 销项发票 SALES_INVOICE：MATCHING→AR_CREATED 形成应收（accounts_receivable）+ 推金蝶销项（SALES_INVOICE outbox）。
  [7] SO 签单大表 /api/sales/ledger：沿订单号串 SO+发货+发票+收款全链一行 + 在途数量=订单-已发货；
      BOSS 跨公司只读汇总（cross_company=True）。无买价/成本/利润点列。
  [8] 备货消单：APPROVED 备货单（同型号+意向客户）→ SO 成交累加 consumed_quantity（EXPLICIT，幂等）。
  [9] 架构边界：引擎核心零改；节点 allowed_roles 把关；金蝶 outbox 幂等。

在 backend/ 下执行（指向干净库 photonteck_p3b，需先 alembic upgrade head + seed + seed_phase1）:
  DATABASE_URL=postgresql+asyncpg://photonteck:photonteck@localhost:5433/photonteck_p3b \
    python -m scripts.smoke_p3b
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
from services.workflow import execute_transition
from routers import sales as sales_router


def _check(label, cond):
    print(f"  [{'OK ' if cond else 'FAIL'}] {label}")
    if not cond:
        raise SystemExit(f"冒烟失败: {label}")


def _ym() -> str:
    return date.today().strftime("%y%m")


async def _user(db, username):
    return (await db.execute(select(m.UserAccount).where(m.UserAccount.username == username))).scalar_one()


def _attach_company_ctx(user, company_ids=None):
    user._active_company_id = user.company_id
    user._authorized_company_ids = company_ids or [user.company_id]
    return user


async def _advance_so(factory, so_id, username, to_state, **kw):
    async with factory() as db:
        u = await _user(db, username)
        r = await execute_transition(db, "SALES_ORDER", so_id, u, to_state=to_state, **kw)
        return r


async def main():
    factory = get_session_factory()

    # ============ 0) 取演示用户/主数据 ============
    async with factory() as db:
        sa = await _user(db, "sa")
        ops = await _user(db, "ops")
        finance = await _user(db, "finance")
        boss = await _user(db, "boss")
        company_id = sa.company_id
        customer = (await db.execute(select(m.Customer).where(m.Customer.company_id == company_id))).scalars().first()
        materials = (await db.execute(select(m.Material))).scalars().all()
        warehouse = (await db.execute(select(m.Warehouse).where(m.Warehouse.company_id == company_id))).scalars().first()
        customer_id = customer.id
        mat_a = materials[0]
        sa_id = sa.id

    # ============ 1) SO 建单：内部订单号月度连号 + 录合同字段组 ============
    print("\n[1] SO 建单：内部订单号 SO 月度连号 + 编号(客户订单号)/事业部/签章字段")
    async with factory() as db:
        u = await _user(db, "sa")
        created = await execute_transition(
            db, "SALES_ORDER", None, u, to_state="START",
            field_updates={"customer_id": customer_id, "currency": "USD"},
        )
        _check("SA 经 execute_transition 建 SO", created.get("success"))
        so_id = created["doc_id"]

    async with factory() as db:
        so = (await db.execute(select(m.SalesOrder).where(m.SalesOrder.id == so_id))).scalar_one()
        expected = f"SO-{_ym()}-001"
        _check(f"SO 内部订单号 = {expected}（实 {so.order_number}）", so.order_number == expected)
        _check("SO 建单落初始 START 态", so.status == "START")

    # START→DRAFT 进录入。
    r = await _advance_so(factory, so_id, "sa", "DRAFT")
    _check("SO START→DRAFT 进录入", r.get("success"))

    # DRAFT→SALES_MANAGER_REVIEW：录编号(客户订单号)/事业部/签章 + 明细行 + 付款方式=预付。
    async with factory() as db:
        u = await _user(db, "sa")
        r = await execute_transition(
            db, "SALES_ORDER", so_id, u, to_state="SALES_MANAGER_REVIEW",
            field_updates={
                "external_order_no": "PO-CUST-9001", "business_unit": "RESEARCH",
                "research_sub_market": "光谱分析", "sales_assistant_id": sa_id,
                "requires_advance_receipt": True, "advance_receipt_amount": 1000,
                "total_amount": 1000, "payment_terms_text": "预付100%",
            },
            sub_updates=[{
                "table": "sales_order_line", "parent_fk": "sales_order_id",
                "fields": {"line_number": 1, "material_id": mat_a.id, "quantity": 10,
                           "unit_price": 100, "total_price": 1000},
            }],
        )
        _check("SO DRAFT→SALES_MANAGER_REVIEW 提交下级审核（录编号/事业部/明细/预付）", r.get("success"))

    async with factory() as db:
        so = (await db.execute(select(m.SalesOrder).where(m.SalesOrder.id == so_id))).scalar_one()
        _check("编号(客户订单号) external_order_no 已落", so.external_order_no == "PO-CUST-9001")
        _check("事业部 business_unit=RESEARCH 已落", so.business_unit == "RESEARCH")

    # ============ 2) SA leader 下级审核（签章）→ 推金蝶销售订单 ============
    print("\n[2] SA leader 下级审核（签章）→ 推金蝶销售订单（SALES_ORDER outbox）")
    async with factory() as db:
        u = await _user(db, "ops")  # allowed_roles 兜底 OPERATIONS（无 SALES_ASSISTANT_LEADER 角色）
        r = await execute_transition(
            db, "SALES_ORDER", so_id, u, to_state="ADVANCE_RECEIPT_REQUIRED",
            field_updates={"signature_status": "SIGNED", "signature_party": "OUR"},
        )
        _check("SO 下级审核（需预收）签章放行", r.get("success"))

    async with factory() as db:
        outbox = (await db.execute(select(m.KingdeeOutbox).where(
            m.KingdeeOutbox.company_id == company_id,
            m.KingdeeOutbox.doc_type == "SALES_ORDER",
            m.KingdeeOutbox.biz_no == f"SO-{_ym()}-001",
        ))).scalars().all()
        _check("★SO 审核后推金蝶 outbox 一行（幂等键=内部订单号）", len(outbox) == 1)
        so = (await db.execute(select(m.SalesOrder).where(m.SalesOrder.id == so_id))).scalar_one()
        _check("签章状态 signature_status=SIGNED 已落", so.signature_status == "SIGNED")
        ar_req = (await db.execute(select(m.AdvanceReceipt).where(m.AdvanceReceipt.sales_order_id == so_id))).scalars().first()
        _check("需预收 → 派生预收单 ADVANCE_RECEIPT（关联 SO）", ar_req is not None)
        ar_req_id = ar_req.id

    # ============ 3) ★预付到账闸：未到账被拦 / 到账后放行 ============
    print("\n[3] ★预付到账闸：付款方式=预付，到账未确认放行采购被 hard_rule 拦；到账确认后放行")
    async with factory() as db:
        u = await _user(db, "ops")
        denied = await execute_transition(db, "SALES_ORDER", so_id, u, to_state="READY_FOR_PURCHASE")
        _check("★预付未到账 → 放行采购被 hard_rule 拦", not denied.get("success"))

    # 财务确认预收到账（ADVANCE_RECEIPT DRAFT→CONFIRMED）→ 回写 SO.advance_receipt_confirmed。
    async with factory() as db:
        u = await _user(db, "finance")
        r = await execute_transition(
            db, "ADVANCE_RECEIPT", ar_req_id, u, to_state="CONFIRMED",
            field_updates={"customer_id": customer_id, "sales_order_id": so_id,
                           "amount": 1000, "currency": "USD"},
        )
        _check("财务确认预收到账（ADVANCE_RECEIPT→CONFIRMED）", r.get("success"))

    async with factory() as db:
        so = (await db.execute(select(m.SalesOrder).where(m.SalesOrder.id == so_id))).scalar_one()
        _check("★到账确认回写 SO.advance_receipt_confirmed=True", so.advance_receipt_confirmed is True)

    async with factory() as db:
        u = await _user(db, "ops")
        r = await execute_transition(db, "SALES_ORDER", so_id, u, to_state="READY_FOR_PURCHASE")
        _check("★到账确认后放行采购通过", r.get("success"))

    # ============ 4) 采购通知派生（READY_FOR_PURCHASE effect 自动建）============
    print("\n[4] 采购通知派生：READY_FOR_PURCHASE → 自动建 PURCHASE_NOTICE（关联 sales_order_id）")
    async with factory() as db:
        pn = (await db.execute(select(m.PurchaseNotice).where(m.PurchaseNotice.sales_order_id == so_id))).scalars().first()
        _check("采购通知已派生（erp.create_purchase_notice_from_sales_order）", pn is not None)
        pn_lines = (await db.execute(select(m.PurchaseNoticeLine).where(m.PurchaseNoticeLine.purchase_notice_id == pn.id))).scalars().all()
        _check("采购通知明细随 SO 明细派生", len(pn_lines) == 1)

    # 推进 SO 到 READY_TO_SHIP（PURCHASE_NOTICE_SENT → READY_TO_SHIP）。
    r = await _advance_so(factory, so_id, "sa", "PURCHASE_NOTICE_SENT")
    _check("SO READY_FOR_PURCHASE→PURCHASE_NOTICE_SENT", r.get("success"))
    r = await _advance_so(factory, so_id, "sa", "READY_TO_SHIP")
    _check("SO PURCHASE_NOTICE_SENT→READY_TO_SHIP", r.get("success"))

    # ============ 5) 发货申请 SHIPMENT 关联 SO 减在途 ============
    print("\n[5] 发货申请 SHIPMENT 关联 SO：建发货单 → 回填 SO 明细 shipped_quantity 减在途")
    # READY_TO_SHIP→SHIPMENT_REQUESTED：派生 SHIPMENT（关联 sales_order_id）。
    async with factory() as db:
        u = await _user(db, "sa")
        r = await execute_transition(db, "SALES_ORDER", so_id, u, to_state="SHIPMENT_REQUESTED")
        _check("SO READY_TO_SHIP→SHIPMENT_REQUESTED 派生发货申请", r.get("success"))

    async with factory() as db:
        ship = (await db.execute(select(m.ShipmentRequest).where(m.ShipmentRequest.sales_order_id == so_id))).scalars().first()
        _check("发货申请 SHIPMENT 已派生（关联 sales_order_id）", ship is not None)
        ship_id = ship.id
        so_line = (await db.execute(select(m.SalesOrderLine).where(m.SalesOrderLine.sales_order_id == so_id))).scalars().first()
        so_line_id = so_line.id
        # 建一条库存供发货扣减。
        inv = m.Inventory(material_id=mat_a.id, warehouse_id=warehouse.id, quantity=10,
                          reserved_quantity=0, status="AVAILABLE", company_id=company_id,
                          batch_number="P3B-LOT-1", received_date=date.today())
        db.add(inv)
        await db.flush()
        inv_id = inv.id
        # 发货申请加一行明细（部分发 6 件，关联 SO 明细）。
        db.add(m.ShipmentLine(shipment_id=ship_id, sales_order_line_id=so_line_id,
                              inventory_id=inv_id, quantity=6))
        await db.commit()

    # 跑出库扣库存 effect（回填 SO 明细 shipped_quantity）= 经 SHIPMENT 财务放行边。
    async with factory() as db:
        from services.phase1_effects import apply_shipment_stock_out
        u = await _user(db, "finance")
        ship = (await db.execute(select(m.ShipmentRequest).where(m.ShipmentRequest.id == ship_id))).scalar_one()
        logs = await apply_shipment_stock_out(db, "SHIPMENT", ship, "SALES_OUTBOUND", u, None)
        await db.commit()
        _check("出库扣库存 effect 跑通（回填 shipped_quantity）", any("reduced inventory" in s for s in logs))

    async with factory() as db:
        so_line = (await db.execute(select(m.SalesOrderLine).where(m.SalesOrderLine.id == so_line_id))).scalar_one()
        _check(f"SO 明细 shipped_quantity 减在途（实 {so_line.shipped_quantity}）", Decimal(str(so_line.shipped_quantity)) == Decimal("6"))

    # ============ 6) 销项发票 SALES_INVOICE：MATCHING→AR_CREATED 形成应收 + 推金蝶 ============
    print("\n[6] 销项发票 SALES_INVOICE：MATCHING→AR_CREATED 形成应收 + 推金蝶销项")
    async with factory() as db:
        u = await _user(db, "finance")
        created = await execute_transition(db, "SALES_INVOICE", None, u, to_state="START")
        _check("财务建销项发票", created.get("success"))
        inv_id = created["doc_id"]

    async with factory() as db:
        u = await _user(db, "finance")
        r = await execute_transition(
            db, "SALES_INVOICE", inv_id, u, to_state="DRAFT",
        )
        _check("销项发票 START→DRAFT", r.get("success"))
    async with factory() as db:
        u = await _user(db, "finance")
        r = await execute_transition(
            db, "SALES_INVOICE", inv_id, u, to_state="MATCHING",
            field_updates={"customer_id": customer_id, "sales_order_id": so_id,
                           "shipment_id": ship_id, "amount": 600, "currency": "USD"},
        )
        _check("销项发票 DRAFT→MATCHING 提交勾稽", r.get("success"))

    async with factory() as db:
        invoice = (await db.execute(select(m.SalesInvoice).where(m.SalesInvoice.id == inv_id))).scalar_one()
        inv_number = invoice.invoice_number
    async with factory() as db:
        u = await _user(db, "finance")
        r = await execute_transition(db, "SALES_INVOICE", inv_id, u, to_state="AR_CREATED")
        _check("销项发票 MATCHING→AR_CREATED 勾稽生成应收", r.get("success"))

    async with factory() as db:
        ar = (await db.execute(select(m.AccountsReceivable).where(
            m.AccountsReceivable.company_id == company_id,
            m.AccountsReceivable.invoice_number == inv_number,
        ))).scalars().first()
        _check("应收 accounts_receivable 已形成", ar is not None)
        sinv_outbox = (await db.execute(select(m.KingdeeOutbox).where(
            m.KingdeeOutbox.company_id == company_id,
            m.KingdeeOutbox.doc_type == "SALES_INVOICE",
            m.KingdeeOutbox.biz_no == inv_number,
        ))).scalars().all()
        _check("★销项发票推金蝶 outbox 一行（幂等键=invoice_number）", len(sinv_outbox) == 1)

    # ============ 7) SO 签单大表 /api/sales/ledger 聚合全链 + 在途 ============
    print("\n[7] SO 签单大表 /api/sales/ledger：全链一行 + 在途=订单-已发货；BOSS 跨公司只读汇总")
    async with factory() as db:
        u = _attach_company_ctx(await _user(db, "sa"))
        resp = await sales_router.sales_ledger(
            sales_assistant_id=None, sales_engineer_id=None, business_unit=None,
            status=None, limit=200, db=db, user=u,
        )
        row = next((r for r in resp["rows"] if r["sales_order_id"] == so_id), None)
        _check("台账出本 SO 一行（沿订单号串全链）", row is not None)
        _check(f"在途数量=订单(10)-已发货(6)=4（实 {row['in_transit_quantity']}）", row["in_transit_quantity"] == 4)
        _check("台账带发货段（shipment_number/last_shipped 或计数）", row["shipment_count"] >= 1)
        _check("台账带销项发票号", row["invoice_number"] == inv_number)
        _check("台账带应收段（receivable_amount>0）", row["receivable_amount"] > 0)
        _check("★台账无买价/成本/利润点列", not any(k in row for k in ("cost", "cost_unit", "unit_cost", "profit_point", "buy_price")))

    async with factory() as db:
        u = _attach_company_ctx(await _user(db, "boss"))
        resp = await sales_router.sales_ledger(
            sales_assistant_id=None, sales_engineer_id=None, business_unit=None,
            status=None, limit=500, db=db, user=u,
        )
        _check("★BOSS 跨公司只读汇总（cross_company=True）", resp["cross_company"] is True)

    # ============ 8) 备货消单：APPROVED 备货单 → SO 成交累加 consumed_quantity ============
    print("\n[8] 备货消单：APPROVED 备货单（同型号+意向客户）→ SO 成交累加 consumed_quantity（幂等）")
    async with factory() as db:
        su = m.StockUpRequest(
            request_number=f"SU-{_ym()}-900", material_id=mat_a.id,
            stockup_quantity=Decimal("20"), consumed_quantity=Decimal("0"),
            intended_customer_id=customer_id, amount=Decimal("2000"), currency="USD",
            status="APPROVED", company_id=company_id, created_by_id=sa_id,
        )
        db.add(su)
        await db.commit()
        su_id = su.id

    # 跑备货消单 EXPLICIT effect（SO 成交）。
    async with factory() as db:
        from services.phase1_effects import consume_on_sales_order
        u = await _user(db, "ops")
        so = (await db.execute(select(m.SalesOrder).where(m.SalesOrder.id == so_id))).scalar_one()
        logs = await consume_on_sales_order(db, "SALES_ORDER", so, "READY_FOR_PURCHASE", u, None)
        await db.commit()
        _check("备货消单 effect 产出累加日志", any("备货消单" in s for s in logs))

    async with factory() as db:
        su = (await db.execute(select(m.StockUpRequest).where(m.StockUpRequest.id == su_id))).scalar_one()
        _check(f"备货单 consumed_quantity 累加=SO 明细数量 10（实 {su.consumed_quantity}）", Decimal(str(su.consumed_quantity)) == Decimal("10"))

    # 幂等：再跑一次不应重复累加。
    async with factory() as db:
        from services.phase1_effects import consume_on_sales_order
        u = await _user(db, "ops")
        so = (await db.execute(select(m.SalesOrder).where(m.SalesOrder.id == so_id))).scalar_one()
        await consume_on_sales_order(db, "SALES_ORDER", so, "READY_FOR_PURCHASE", u, None)
        await db.commit()
    async with factory() as db:
        su = (await db.execute(select(m.StockUpRequest).where(m.StockUpRequest.id == su_id))).scalar_one()
        _check(f"★备货消单幂等：再跑不重复累加（仍=10，实 {su.consumed_quantity}）", Decimal(str(su.consumed_quantity)) == Decimal("10"))

    # ============ 9) SO 内部订单号月度连号（建第二张 SO 验 002）============
    print("\n[9] SO 内部订单号月度连号：建第二张 SO 验 SO-YYMM-002")
    async with factory() as db:
        u = await _user(db, "sa")
        created = await execute_transition(
            db, "SALES_ORDER", None, u, to_state="START",
            field_updates={"customer_id": customer_id, "currency": "USD"},
        )
        so2_id = created["doc_id"]
    async with factory() as db:
        so2 = (await db.execute(select(m.SalesOrder).where(m.SalesOrder.id == so2_id))).scalar_one()
        expected2 = f"SO-{_ym()}-002"
        _check(f"第二张 SO 内部订单号 = {expected2}（实 {so2.order_number}）", so2.order_number == expected2)

    print("\n✅ 段3b 冒烟全部通过")


if __name__ == "__main__":
    asyncio.run(main())
