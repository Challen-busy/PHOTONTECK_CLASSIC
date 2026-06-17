"""段2b 冒烟：采购订单主链（PO 重构流程 + 推金蝶 + Q18 防火墙 + PO 总表聚合）。

经唯一写入路径（execute_transition）验证：
  1) PA 经 execute_transition 建 PO（START 创建 + 明细子表）→ 验业务号 PO-YYMM-001 +
     PO 头扩列（factory_so_number/product_manager_id/notice_date/stock_*）落库。
  2) 重构主链推进：DRAFT →提交→ PENDING_APPROVAL →递交→ FINANCE_APPROVAL
     →★FINANCE 采购审批通过→ ORDERED；验 kingdee_outbox 入队一行（幂等键 order_number+company）。
  3) ★Q18 防火墙：SALES / SA 查 purchase_order / purchase_order_line —— 看不到买价
     （total_amount/advance_payment_amount/stock_amount_*/unit_price/total_price）；PA 可见。
  4) PO 总表聚合端点（/api/purchase/ledger）按 PA 过滤出本人 PO + 在途列（订单-已收）。

在 backend/ 下执行（指向干净库 photonteck_p2b，需先 alembic upgrade head + seed + seed_phase1）:
  DATABASE_URL=postgresql+asyncpg://photonteck:photonteck@localhost:5433/photonteck_p2b \
    python -m scripts.smoke_p2b
"""

import asyncio
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import models as m
from core.database import get_session_factory
from routers.data import get_schema
from routers.purchase import purchase_ledger
from services.tools import query_data
from services.workflow import execute_transition


def _check(label, cond):
    print(f"  [{'OK ' if cond else 'FAIL'}] {label}")
    if not cond:
        raise SystemExit(f"冒烟失败: {label}")


def _expected_number(prefix: str) -> str:
    """本期首单业务号：prefix-YYMM-001（与 NumberingRule MONTH/pad3/sep- 一致）。"""
    return f"{prefix}-{date.today().strftime('%y%m')}-001"


async def main():
    factory = get_session_factory()

    # ============ 0) 取演示用户/主数据 ============
    async with factory() as db:
        pa = (await db.execute(select(m.UserAccount).where(m.UserAccount.username == "pa"))).scalar_one()
        finance = (await db.execute(select(m.UserAccount).where(m.UserAccount.username == "finance"))).scalar_one()
        sa = (await db.execute(select(m.UserAccount).where(m.UserAccount.username == "sa"))).scalar_one()
        sales = (await db.execute(select(m.UserAccount).where(m.UserAccount.username == "sales"))).scalar_one()
        pm = (await db.execute(select(m.UserAccount).where(m.UserAccount.username == "pm"))).scalar_one()
        supplier = (await db.execute(select(m.Supplier).where(m.Supplier.company_id == pa.company_id))).scalars().first()
        material = (await db.execute(select(m.Material))).scalars().first()
        pa_id, finance_id, pm_id = pa.id, finance.id, pm.id
        supplier_id, material_id = supplier.id, material.id

    # ============ 1) PA 经 execute_transition 建 PO（START 创建 + 明细子表 + 扩列）============
    async with factory() as db:
        u_pa = (await db.execute(select(m.UserAccount).where(m.UserAccount.id == pa_id))).scalar_one()
        created = await execute_transition(
            db, "PURCHASE_ORDER", None, u_pa, to_state="START",
            field_updates={
                "supplier_id": supplier_id, "purchase_assistant_id": pa_id,
                "currency": "USD", "total_amount": 8200,
                "po_date": date.today().isoformat(),
                # 段2b 扩列
                "factory_so_number": "OSI-SO-77881", "product_manager_id": pm_id,
                "notice_date": date.today().isoformat(),
                "is_stock_order": True, "stock_quantity": 1000,
                "stock_amount_original": 8200, "stock_amount_latest": 8200,
                "stock_reason": "OSI 平销返利产线备货，等客户 SO",
                "requires_advance_payment": False,
            },
            sub_updates=[
                {"table": "purchase_order_line", "parent_fk": "purchase_order_id",
                 "fields": {"line_number": 1, "material_id": material_id, "quantity": 1000,
                            "uom": "pcs", "unit_price": 8.20, "total_price": 8200}},
            ],
        )
        _check("PA 经 execute_transition 建 PO 成功", created.get("success"))
        po_id = created["doc_id"]
        await db.commit()

    # B 模型：建单入 START，首业务态 DRAFT 经显式「开始录入」边到达（同 smoke_p2a 模式）。
    async with factory() as db:
        u_pa = (await db.execute(select(m.UserAccount).where(m.UserAccount.id == pa_id))).scalar_one()
        adv = await execute_transition(db, "PURCHASE_ORDER", po_id, u_pa, to_state="DRAFT")
        _check("PO START→DRAFT（PA 经 execute_transition 推进）", adv.get("success"))
        await db.commit()

    async with factory() as db:
        po = (await db.execute(select(m.PurchaseOrder).where(m.PurchaseOrder.id == po_id))).scalar_one()
        _check(f"PO 业务号 = {_expected_number('PO')}（实得 {po.order_number}）",
               po.order_number == _expected_number("PO"))
        _check("PO 进入首业务态 DRAFT", po.status == "DRAFT")
        _check("扩列 factory_so_number 落库", po.factory_so_number == "OSI-SO-77881")
        _check("扩列 product_manager_id 落库", po.product_manager_id == pm_id)
        _check("扩列 notice_date 落库", po.notice_date == date.today())
        _check("扩列 stock_amount_original/latest 落库",
               float(po.stock_amount_original) == 8200 and float(po.stock_amount_latest) == 8200)
        _check("扩列 stock_quantity/stock_reason 落库",
               float(po.stock_quantity) == 1000 and "备货" in (po.stock_reason or ""))
        lines = (await db.execute(select(m.PurchaseOrderLine).where(
            m.PurchaseOrderLine.purchase_order_id == po_id))).scalars().all()
        _check("PO 明细行落库（unit_price=8.20）", len(lines) == 1 and float(lines[0].unit_price) == 8.20)

    # ============ 2) 重构主链推进：DRAFT→PENDING_APPROVAL→FINANCE_APPROVAL→★FINANCE 审→ORDERED ============
    print("\n  --- PO 主链重构推进（DRAFT→PENDING_APPROVAL→FINANCE_APPROVAL→ORDERED）---")
    async with factory() as db:
        u_pa = (await db.execute(select(m.UserAccount).where(m.UserAccount.id == pa_id))).scalar_one()
        r1 = await execute_transition(db, "PURCHASE_ORDER", po_id, u_pa, to_state="PENDING_APPROVAL")
        _check("PA 提交采购审批 DRAFT→PENDING_APPROVAL", r1.get("success"))
        await db.commit()

    async with factory() as db:
        u_pa = (await db.execute(select(m.UserAccount).where(m.UserAccount.id == pa_id))).scalar_one()
        r2 = await execute_transition(db, "PURCHASE_ORDER", po_id, u_pa, to_state="FINANCE_APPROVAL")
        _check("PA 递交财务采购审批 PENDING_APPROVAL→FINANCE_APPROVAL", r2.get("success"))
        await db.commit()

    # ★非财务不能在 FINANCE_APPROVAL 推进（节点级 allowed_roles=[FINANCE]）。
    async with factory() as db:
        u_pa = (await db.execute(select(m.UserAccount).where(m.UserAccount.id == pa_id))).scalar_one()
        denied = await execute_transition(
            db, "PURCHASE_ORDER", po_id, u_pa, to_state="ORDERED",
            action_label="审核通过并下单",
        )
        _check("★PA 无权在 FINANCE_APPROVAL 推进（节点级 FINANCE 角色闸）", not denied.get("success"))
        await db.rollback()

    # ★FINANCE 审批通过 → ORDERED（action_label 区分两条到 ORDERED 的边：走非预付边）。
    async with factory() as db:
        u_fin = (await db.execute(select(m.UserAccount).where(m.UserAccount.id == finance_id))).scalar_one()
        r3 = await execute_transition(
            db, "PURCHASE_ORDER", po_id, u_fin, to_state="ORDERED",
            action_label="审核通过并下单",
            field_updates={"expected_delivery_date": date.today().isoformat()},
        )
        _check("★FINANCE 采购审批通过 FINANCE_APPROVAL→ORDERED", r3.get("success"))
        await db.commit()

    async with factory() as db:
        po = (await db.execute(select(m.PurchaseOrder).where(m.PurchaseOrder.id == po_id))).scalar_one()
        _check("PO 状态 = ORDERED（已下单）", po.status == "ORDERED")
        # 推金蝶：ORDERED 边挂 kingdee.enqueue_push（默认 OFF → RUNNING dry-run），幂等键 order_number+company。
        outbox = (await db.execute(select(m.KingdeeOutbox).where(
            m.KingdeeOutbox.company_id == po.company_id,
            m.KingdeeOutbox.doc_type == "PURCHASE_ORDER",
            m.KingdeeOutbox.biz_no == po.order_number))).scalars().all()
        _check("kingdee_outbox 入队 1 行（PURCHASE_ORDER，幂等键=order_number）", len(outbox) == 1)
        _check("outbox 状态 RUNNING（默认 OFF dry-run）+ form_id=pm_purorderbill",
               outbox[0].status == "RUNNING" and outbox[0].form_id == "pm_purorderbill")

    # ============ 3) ★Q18 防火墙：SALES / SA 看不到买价，PA 可见 ============
    print("\n  --- Q18 字段防火墙（purchase_order / purchase_order_line）---")
    HEAD_HIDDEN = {"total_amount", "advance_payment_amount", "stock_amount_original", "stock_amount_latest"}
    LINE_HIDDEN = {"unit_price", "total_price"}

    async with factory() as db:
        for label, role_user in (("SALES", sales), ("SA", sa)):
            u = (await db.execute(select(m.UserAccount).where(m.UserAccount.id == role_user.id))).scalar_one()
            # schema 路：两表的买价列定义被剥（即便 table-level 也无权，确认买价绝不外泄）。
            sch_head = await get_schema("purchase_order", user=u)
            leaked_h = HEAD_HIDDEN & {f["name"] for f in sch_head["fields"]}
            _check(f"{label} purchase_order schema 无买价 {sorted(HEAD_HIDDEN)}（泄漏: {sorted(leaked_h)}）", not leaked_h)
            sch_line = await get_schema("purchase_order_line", user=u)
            leaked_l = LINE_HIDDEN & {f["name"] for f in sch_line["fields"]}
            _check(f"{label} purchase_order_line schema 无买价 {sorted(LINE_HIDDEN)}（泄漏: {sorted(leaked_l)}）", not leaked_l)

        # PA 两路都看得到买价。
        u_pa = (await db.execute(select(m.UserAccount).where(m.UserAccount.id == pa_id))).scalar_one()
        sch_head_pa = await get_schema("purchase_order", user=u_pa)
        _check("PA purchase_order schema 可见买价", HEAD_HIDDEN <= {f["name"] for f in sch_head_pa["fields"]})
        qr_line_pa = await query_data(db, u_pa, {"table": "purchase_order_line", "limit": 50})
        pa_keys = set().union(*[set(r.keys()) for r in qr_line_pa["data"]]) if qr_line_pa["data"] else set()
        _check("PA query purchase_order_line 可见 unit_price/total_price", LINE_HIDDEN <= pa_keys)

    # ============ 4) PO 总表聚合端点：按 PA 过滤出本人 PO + 在途列 ============
    print("\n  --- PO 总表 / 采购台账聚合（/api/purchase/ledger）---")
    async with factory() as db:
        u_pa = (await db.execute(select(m.UserAccount).where(m.UserAccount.id == pa_id))).scalar_one()
        led = await purchase_ledger(purchase_assistant_id=pa_id, is_stock_order=None, limit=200, db=db, user=u_pa)
        my_row = next((r for r in led["rows"] if r["purchase_order_id"] == po_id), None)
        _check("PA 台账含本人 PO 行", my_row is not None)
        _check("台账 在途列 in_transit_quantity = 订单-已收 = 1000", my_row["in_transit_quantity"] == 1000)
        _check("台账 PA 视角含买价列 total_amount", "total_amount" in my_row and led["buy_price_visible"] is True)
        _check("台账标记备货段 is_stock_order=True + stock_quantity=1000",
               my_row["is_stock_order"] is True and my_row["stock_quantity"] == 1000)

        # SALES 经台账端点：买价列整体剔除（Q18），且 buy_price_visible=False。
        u_sales = (await db.execute(select(m.UserAccount).where(m.UserAccount.id == sales.id))).scalar_one()
        led_s = await purchase_ledger(purchase_assistant_id=pa_id, is_stock_order=None, limit=200, db=db, user=u_sales)
        leaked_led = HEAD_HIDDEN & set().union(*[set(r.keys()) for r in led_s["rows"]]) if led_s["rows"] else set()
        _check(f"SALES 台账无买价列 {sorted(HEAD_HIDDEN)}（泄漏: {sorted(leaked_led)}）", not leaked_led)
        _check("SALES 台账 buy_price_visible=False", led_s["buy_price_visible"] is False)

    print("\n段2b 冒烟全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
