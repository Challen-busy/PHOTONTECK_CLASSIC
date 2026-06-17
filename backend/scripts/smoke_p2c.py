"""段2c 冒烟：采购收尾（进项发票★审核 + 付款申请 + 采购在途 + PO 总表发货/付款段）。

经唯一写入路径（execute_transition）验证 04a-6/7/8：
  1) 进项发票：PA 建单（START 取号 PI-YYMM-001）→ 提交 PENDING_REVIEW →
     ★PA 无权审核（节点级 allowed_roles=[FINANCE]）→ FINANCE 审核通过 AP_CREATED；
     验 accounts_payable 生成 + kingdee_outbox 入队（PURCHASE_INVOICE，幂等键 invoice_number+company）+
     reviewed_by/at 留痕。
  2) 付款申请（货后）：PA 发起（关联已审进项发票）→ 提交 PENDING_FINANCE → FINANCE 执行 PAID
     （推金蝶 PAYMENT_REQUEST）→ 确认到账 CONFIRMED；验 confirmed=True + 应付 paid_amount 递减。
  3) 采购在途：/api/purchase/intransit 按 PA 出在途行（in_transit=订单-已收）+ alert_flag；
     提醒命令 run_notification_scan 产出在途 IN_TRANSIT 通知。
  4) PO 总表 ledger 扩发货/付款段（到库日期/发票号/付款状态/应付余额）；买价/应付列对 SALES 遮蔽。

在 backend/ 下执行（指向干净库 photonteck_p2c，需先 alembic upgrade head + seed + seed_phase1）:
  DATABASE_URL=postgresql+asyncpg://photonteck:photonteck@localhost:5433/photonteck_p2c \
    python -m scripts.smoke_p2c
"""

import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import models as m
from core.database import get_session_factory
from routers.purchase import purchase_ledger, purchase_in_transit
from services.command_context import CommandContext
from services.commands import execute_command
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

    # ============ 0) 取演示用户/主数据 + 建一张已下单 PO（在途/发票/付款锚点）============
    async with factory() as db:
        pa = (await db.execute(select(m.UserAccount).where(m.UserAccount.username == "pa"))).scalar_one()
        finance = (await db.execute(select(m.UserAccount).where(m.UserAccount.username == "finance"))).scalar_one()
        sales = (await db.execute(select(m.UserAccount).where(m.UserAccount.username == "sales"))).scalar_one()
        supplier = (await db.execute(select(m.Supplier).where(m.Supplier.company_id == pa.company_id))).scalars().first()
        material = (await db.execute(select(m.Material))).scalars().first()
        pa_id, finance_id, sales_id = pa.id, finance.id, sales.id
        company_id = pa.company_id
        supplier_id, material_id = supplier.id, material.id

    # 建 PO + 推到 ORDERED（作为在途/发票/付款的关联锚点）。
    async with factory() as db:
        u_pa = await _user(db, pa_id)
        created = await execute_transition(
            db, "PURCHASE_ORDER", None, u_pa, to_state="START",
            field_updates={
                "supplier_id": supplier_id, "purchase_assistant_id": pa_id,
                "currency": "USD", "total_amount": 5000, "po_date": date.today().isoformat(),
                "requires_advance_payment": False,
            },
            sub_updates=[{"table": "purchase_order_line", "parent_fk": "purchase_order_id",
                          "fields": {"line_number": 1, "material_id": material_id, "quantity": 100,
                                     "uom": "pcs", "unit_price": 50, "total_price": 5000}}],
        )
        po_id = created["doc_id"]
        await db.commit()
    for to, lbl in (("DRAFT", None), ("PENDING_APPROVAL", None), ("FINANCE_APPROVAL", None)):
        async with factory() as db:
            actor = await _user(db, pa_id)
            r = await execute_transition(db, "PURCHASE_ORDER", po_id, actor, to_state=to)
            _check(f"PO 推进 → {to}", r.get("success"))
            await db.commit()
    async with factory() as db:
        u_fin = await _user(db, finance_id)
        r = await execute_transition(db, "PURCHASE_ORDER", po_id, u_fin, to_state="ORDERED",
                                     action_label="审核通过并下单",
                                     field_updates={"expected_delivery_date": date.today().isoformat()})
        _check("PO FINANCE_APPROVAL→ORDERED（已下单，在途锚点）", r.get("success"))
        await db.commit()
    async with factory() as db:
        po = (await db.execute(select(m.PurchaseOrder).where(m.PurchaseOrder.id == po_id))).scalar_one()
        po_number = po.order_number

    # ============ 1) 进项发票：PA 录单→提交→★FINANCE 审核→AP_CREATED ============
    print("\n  --- 04a-7 进项发票录入 + ★FINANCE 审核 ---")
    async with factory() as db:
        u_pa = await _user(db, pa_id)
        created = await execute_transition(
            db, "PURCHASE_INVOICE", None, u_pa, to_state="START",
            field_updates={
                "supplier_id": supplier_id, "purchase_order_id": po_id,
                "amount": 5000, "currency": "USD", "tax_rate": 13,
                "invoice_date": date.today().isoformat(),
                "due_date": (date.today() + timedelta(days=30)).isoformat(),
            },
        )
        _check("PA 经 execute_transition 建进项发票", created.get("success"))
        inv_id = created["doc_id"]
        await db.commit()

    # B 模型：建单入 START，首业务态 DRAFT 经显式「开始录入」边到达（同 smoke_p2b 模式）。
    async with factory() as db:
        u_pa = await _user(db, pa_id)
        r = await execute_transition(db, "PURCHASE_INVOICE", inv_id, u_pa, to_state="DRAFT")
        _check("进项发票 START→DRAFT（开始录入）", r.get("success"))
        await db.commit()

    async with factory() as db:
        inv = (await db.execute(select(m.PurchaseInvoice).where(m.PurchaseInvoice.id == inv_id))).scalar_one()
        _check(f"进项发票业务号 = {_expected_number('PI')}（实得 {inv.invoice_number}）",
               inv.invoice_number == _expected_number("PI"))
        inv_number = inv.invoice_number

    async with factory() as db:
        u_pa = await _user(db, pa_id)
        r = await execute_transition(db, "PURCHASE_INVOICE", inv_id, u_pa, to_state="PENDING_REVIEW")
        _check("PA 提交财务审核 DRAFT→PENDING_REVIEW", r.get("success"))
        await db.commit()

    # ★PA 无权在 PENDING_REVIEW 推进（节点级 allowed_roles=[FINANCE]）。
    async with factory() as db:
        u_pa = await _user(db, pa_id)
        denied = await execute_transition(db, "PURCHASE_INVOICE", inv_id, u_pa, to_state="AP_CREATED",
                                          action_label="审核通过并生成应付")
        _check("★PA 无权审核进项发票（节点级 FINANCE 角色闸）", not denied.get("success"))
        await db.rollback()

    # ★FINANCE 审核通过 → AP_CREATED（形成应付 + 回写 PO + 推金蝶）。
    async with factory() as db:
        u_fin = await _user(db, finance_id)
        r = await execute_transition(db, "PURCHASE_INVOICE", inv_id, u_fin, to_state="AP_CREATED",
                                     action_label="审核通过并生成应付")
        _check("★FINANCE 审核通过 PENDING_REVIEW→AP_CREATED", r.get("success"))
        await db.commit()

    async with factory() as db:
        inv = (await db.execute(select(m.PurchaseInvoice).where(m.PurchaseInvoice.id == inv_id))).scalar_one()
        _check("进项发票状态 = AP_CREATED", inv.status == "AP_CREATED")
        _check("进项发票 reviewed_by_id 留痕（FINANCE）", inv.reviewed_by_id == finance_id)
        _check("进项发票 reviewed_at 留痕", inv.reviewed_at is not None)
        ap = (await db.execute(select(m.AccountsPayable).where(
            m.AccountsPayable.company_id == company_id,
            m.AccountsPayable.invoice_number == inv_number))).scalars().all()
        _check("应付账款生成 1 行（accounts_payable）", len(ap) == 1 and float(ap[0].amount) == 5000)
        outbox = (await db.execute(select(m.KingdeeOutbox).where(
            m.KingdeeOutbox.company_id == company_id,
            m.KingdeeOutbox.doc_type == "PURCHASE_INVOICE",
            m.KingdeeOutbox.biz_no == inv_number))).scalars().all()
        _check("kingdee_outbox 入队 1 行（PURCHASE_INVOICE，幂等键 invoice_number）", len(outbox) == 1)
        _check("outbox 状态 RUNNING（OFF dry-run）+ form_id=ap_finapbill",
               outbox[0].status == "RUNNING" and outbox[0].form_id == "ap_finapbill")

    # ============ 2) 付款申请（货后）：PA 发起→FINANCE 执行→确认到账 ============
    print("\n  --- 04a-8 付款申请（货后，发起在采购、执行在财务）---")
    async with factory() as db:
        u_pa = await _user(db, pa_id)
        created = await execute_transition(
            db, "PAYMENT_REQUEST", None, u_pa, to_state="START",
            field_updates={
                "payment_type": "POST_DELIVERY", "supplier_id": supplier_id,
                "purchase_order_id": po_id, "purchase_invoice_id": inv_id,
                "requested_by_id": pa_id, "amount": 5000, "currency": "USD",
                "payee_name": "原厂收款方",
                "due_date": (date.today() + timedelta(days=30)).isoformat(),
            },
        )
        _check("PA 经 execute_transition 发起付款申请", created.get("success"))
        pay_id = created["doc_id"]
        await db.commit()

    # B 模型：建单入 START，首业务态 DRAFT 经显式边到达。
    async with factory() as db:
        u_pa = await _user(db, pa_id)
        r = await execute_transition(db, "PAYMENT_REQUEST", pay_id, u_pa, to_state="DRAFT")
        _check("付款申请 START→DRAFT（开始录入）", r.get("success"))
        await db.commit()

    async with factory() as db:
        pr = (await db.execute(select(m.PaymentRequest).where(m.PaymentRequest.id == pay_id))).scalar_one()
        _check(f"付款申请业务号 = {_expected_number('PAY')}（实得 {pr.payment_number}）",
               pr.payment_number == _expected_number("PAY"))
        pay_number = pr.payment_number

    async with factory() as db:
        u_pa = await _user(db, pa_id)
        r = await execute_transition(db, "PAYMENT_REQUEST", pay_id, u_pa, to_state="PENDING_FINANCE")
        _check("PA 提交财务执行 DRAFT→PENDING_FINANCE", r.get("success"))
        await db.commit()

    # ★PA 无权执行付款（节点级 FINANCE）。
    async with factory() as db:
        u_pa = await _user(db, pa_id)
        denied = await execute_transition(db, "PAYMENT_REQUEST", pay_id, u_pa, to_state="PAID",
                                          action_label="财务执行付款")
        _check("★PA 无权执行付款（节点级 FINANCE 角色闸）", not denied.get("success"))
        await db.rollback()

    async with factory() as db:
        u_fin = await _user(db, finance_id)
        r = await execute_transition(db, "PAYMENT_REQUEST", pay_id, u_fin, to_state="PAID",
                                     action_label="财务执行付款",
                                     field_updates={"approved_by_id": finance_id,
                                                    "payment_date": date.today().isoformat()})
        _check("★FINANCE 执行付款 PENDING_FINANCE→PAID", r.get("success"))
        await db.commit()

    async with factory() as db:
        outbox = (await db.execute(select(m.KingdeeOutbox).where(
            m.KingdeeOutbox.company_id == company_id,
            m.KingdeeOutbox.doc_type == "PAYMENT_REQUEST",
            m.KingdeeOutbox.biz_no == pay_number))).scalars().all()
        _check("kingdee_outbox 入队 1 行（PAYMENT_REQUEST，幂等键 payment_number）+ form_id=cas_paybill",
               len(outbox) == 1 and outbox[0].form_id == "cas_paybill")

    async with factory() as db:
        u_fin = await _user(db, finance_id)
        r = await execute_transition(db, "PAYMENT_REQUEST", pay_id, u_fin, to_state="CONFIRMED",
                                     action_label="确认到账")
        _check("FINANCE 确认到账 PAID→CONFIRMED", r.get("success"))
        await db.commit()

    async with factory() as db:
        pr = (await db.execute(select(m.PaymentRequest).where(m.PaymentRequest.id == pay_id))).scalar_one()
        _check("付款申请 confirmed=True（到账确认）", pr.confirmed is True and pr.status == "CONFIRMED")
        ap = (await db.execute(select(m.AccountsPayable).where(
            m.AccountsPayable.company_id == company_id,
            m.AccountsPayable.invoice_number == inv_number))).scalar_one()
        _check("应付余额递减：paid_amount=5000 且 status=PAID",
               float(ap.paid_amount) == 5000 and ap.status == "PAID")

    # ============ 3) 采购在途端点 + 提醒命令 ============
    print("\n  --- 04a-6 采购在途台账 + 货期提醒 ---")
    # 录一行在途跟踪（过期承诺货期未发货 → 触发提醒），经 PURCHASE_IN_TRANSIT 视为辅助表，
    # 直接由 PA 录入（__queryable__）；此处经轻量 upsert（用 ORM 直写，模拟 PA 录货期）。
    async with factory() as db:
        it = m.PurchaseInTransit(
            company_id=company_id, purchase_order_id=po_id,
            promised_eta=date.today() - timedelta(days=3),  # 已过期
            track_status="ETA_GIVEN",  # 已给货期但未发货
            created_by_id=pa_id,
        )
        db.add(it)
        await db.commit()

    async with factory() as db:
        u_pa = await _user(db, pa_id)
        res = await purchase_in_transit(purchase_assistant_id=pa_id, open_only=True, limit=200, db=db, user=u_pa)
        my = next((r for r in res["rows"] if r["purchase_order_id"] == po_id), None)
        _check("采购在途台账含本 PO 在途行", my is not None)
        _check("在途数量 in_transit_qty = 订单-已收 = 100", my["in_transit_qty"] == 100)
        _check("提醒标记 alert_flag=OVERDUE（承诺货期过期未发货）", my["alert_flag"] == "OVERDUE")

    # 提醒命令：扫在途 → 写 IN_TRANSIT 通知给 PA。
    async with factory() as db:
        u_pa = await _user(db, pa_id)
        result = await execute_command(db, u_pa, "run_notification_scan", {})
        await db.commit()
        _check("run_notification_scan 成功", result.get("success"))
        _check("扫出在途提醒 in_transit >= 1", result.get("in_transit", 0) >= 1)

    async with factory() as db:
        notes = (await db.execute(select(m.Notification).where(
            m.Notification.company_id == company_id,
            m.Notification.category == "IN_TRANSIT"))).scalars().all()
        _check("生成 IN_TRANSIT 站内通知（派给 PA）",
               len(notes) >= 1 and any(n.recipient_id == pa_id for n in notes))

    # ============ 4) PO 总表 ledger 发货/付款段 + 买价对 SALES 遮蔽 ============
    print("\n  --- 04a-4 PO 总表发货/付款段（段2c 扩展）---")
    async with factory() as db:
        u_pa = await _user(db, pa_id)
        led = await purchase_ledger(purchase_assistant_id=pa_id, is_stock_order=None, limit=200, db=db, user=u_pa)
        row = next((r for r in led["rows"] if r["purchase_order_id"] == po_id), None)
        _check("PA 台账含本 PO 行", row is not None)
        _check("发货段：发票号回填进台账", row.get("invoice_number") == inv_number)
        _check("付款段：付款状态 payment_status=PAID（已付满）", row.get("payment_status") == "PAID")
        _check("付款段：已付 paid_amount=5000", row.get("paid_amount") == 5000)
        _check("付款段：应付余额 payable_balance=0", row.get("payable_balance") == 0)
        _check("PA 视角可见买价/应付列", "total_amount" in row and "payable_balance" in row and led["buy_price_visible"])

    async with factory() as db:
        u_sales = await _user(db, sales_id)
        led_s = await purchase_ledger(purchase_assistant_id=pa_id, is_stock_order=None, limit=200, db=db, user=u_sales)
        keys = set().union(*[set(r.keys()) for r in led_s["rows"]]) if led_s["rows"] else set()
        leaked = {"total_amount", "paid_amount", "payable_balance"} & keys
        _check(f"SALES 台账无买价/应付列（泄漏: {sorted(leaked)}）", not leaked)
        _check("SALES 台账 buy_price_visible=False + 仍可见数量/发货段",
               led_s["buy_price_visible"] is False and (not led_s["rows"] or "invoice_number" in keys))

    print("\n段2c 冒烟全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
