"""采购路由：PO 总表 / 采购台账 + 采购在途只读聚合（段2b 04a-4 / 段2c 04a-6）。

PA 核心工作台的「跟单消单」全景：把 PO 头 + PO 明细 + 已收（received_quantity）
沿 FK 聚合成一张只读台账行，按 PA / 产线（purchase_assistant_id）过滤——PA「只拉我的数据」。
段2b 出 PO 段 + 已收段（在途=订单-已收）；段2c 扩发货/付款段（聚合 goods_receipt + 进项发票 +
advance_payment/payment_request）+ 采购在途端点 /api/purchase/intransit。

只读端点（无 db.add/commit），不走唯一写入路径——纯查询聚合（同 routers/reports.py 模式）。
🔒Q18 字段防火墙：买价列（unit_price/total_price/total_amount/advance_payment_amount/
stock_amount_*/付款 amount/应付余额）对销售端 SALES+SA 遮蔽（复用 _can_view_buy_price + BUY_PRICE_FIELDS）。
"""

from datetime import date

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import models as m
from core.auth import get_current_user
from core.database import get_db
from services.commands import execute_command
from services.tools import _company_filter, _can_view_buy_price, BUY_PRICE_FIELDS

router = APIRouter(prefix="/api/purchase")


def _num(v) -> float:
    return float(v) if v is not None else 0.0


def _iso(d):
    return d.isoformat() if d else None


# PO 头上属采购进价/成本、需对销售端遮蔽的列（与 BUY_PRICE_FIELDS 取交集，单一事实源）。
_PO_BUY_FIELDS = {"total_amount", "advance_payment_amount", "stock_amount_original", "stock_amount_latest"}
# 段2c 付款段买价/应付列（与 BUY_PRICE_FIELDS amount 同源；应付余额=发货额-已付亦属采购成本）。
_PAY_BUY_FIELDS = {"paid_amount", "payable_balance"}


@router.get("/ledger")
async def purchase_ledger(
    purchase_assistant_id: int | None = Query(None, description="按 PA 过滤（缺省=本公司全部，受公司过滤约束）"),
    is_stock_order: bool | None = Query(None, description="按是否备货过滤"),
    limit: int = Query(200, le=500),
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    """PO 总表 / 采购台账（只读聚合）。

    每行 = 一张 PO + 其明细聚合（订单数量/已收/在途）+ 备货消单段。
    在途 = Σ订单数量 - Σ已收（received_quantity，由入库 effect 回填）。
    买价列对无 buy-price 权限者（SALES/SA）整体不返回（Q18）。
    """
    company_ids = _company_filter(user)
    show_buy = _can_view_buy_price(user)
    hidden = (_PO_BUY_FIELDS | _PAY_BUY_FIELDS) & BUY_PRICE_FIELDS if not show_buy else set()
    if not show_buy:
        # 应付余额/已付 = 采购成本派生列，对销售端整体剔除（不在 BUY_PRICE_FIELDS 也要遮蔽）。
        hidden = hidden | _PAY_BUY_FIELDS

    # 1) PO 头（按公司 + 可选 PA / 备货过滤）。
    stmt = select(m.PurchaseOrder)
    if company_ids:
        stmt = stmt.where(m.PurchaseOrder.company_id.in_(company_ids))
    if purchase_assistant_id is not None:
        stmt = stmt.where(m.PurchaseOrder.purchase_assistant_id == purchase_assistant_id)
    if is_stock_order is not None:
        stmt = stmt.where(m.PurchaseOrder.is_stock_order == is_stock_order)
    stmt = stmt.order_by(m.PurchaseOrder.id.desc()).limit(limit)
    orders = (await db.execute(stmt)).scalars().all()
    order_ids = [o.id for o in orders]

    # 2) 明细聚合：按 PO 汇总 订单数量 / 已收数量（沿 purchase_order_id FK）。
    agg = {}
    if order_ids:
        line_stmt = (
            select(
                m.PurchaseOrderLine.purchase_order_id,
                func.coalesce(func.sum(m.PurchaseOrderLine.quantity), 0),
                func.coalesce(func.sum(m.PurchaseOrderLine.received_quantity), 0),
                func.count(m.PurchaseOrderLine.id),
            )
            .where(m.PurchaseOrderLine.purchase_order_id.in_(order_ids))
            .group_by(m.PurchaseOrderLine.purchase_order_id)
        )
        for po_id, ordered_qty, received_qty, line_count in (await db.execute(line_stmt)).all():
            agg[po_id] = {
                "ordered_quantity": _num(ordered_qty),
                "received_quantity": _num(received_qty),
                "line_count": int(line_count),
            }

    # 3) 段2c 发货段：goods_receipt（原厂→我方到库，沿 purchase_order_id FK）取最新到库日期 + 在途发货日期。
    ship = {}
    if order_ids:
        gr_stmt = (
            select(
                m.GoodsReceipt.purchase_order_id,
                func.max(m.GoodsReceipt.received_date),
                func.count(m.GoodsReceipt.id),
            )
            .where(m.GoodsReceipt.purchase_order_id.in_(order_ids))
            .group_by(m.GoodsReceipt.purchase_order_id)
        )
        for po_id, last_received, gr_count in (await db.execute(gr_stmt)).all():
            ship.setdefault(po_id, {})["warehouse_in_date"] = _iso(last_received)
            ship[po_id]["receipt_count"] = int(gr_count)
        it_stmt = (
            select(m.PurchaseInTransit.purchase_order_id, m.PurchaseInTransit.shipped_date, m.PurchaseInTransit.track_status)
            .where(m.PurchaseInTransit.purchase_order_id.in_(order_ids))
        )
        for po_id, shipped_date, track_status in (await db.execute(it_stmt)).all():
            ship.setdefault(po_id, {})["shipped_date"] = _iso(shipped_date)
            ship[po_id]["track_status"] = track_status
        # 发票号（进项发票，沿 purchase_order_id FK）：取最新一张发票号。
        inv_stmt = (
            select(m.PurchaseInvoice.purchase_order_id, m.PurchaseInvoice.invoice_number, m.PurchaseInvoice.id)
            .where(m.PurchaseInvoice.purchase_order_id.in_(order_ids))
            .order_by(m.PurchaseInvoice.id.desc())
        )
        for po_id, inv_no, _inv_id in (await db.execute(inv_stmt)).all():
            ship.setdefault(po_id, {}).setdefault("invoice_number", inv_no)

    # 4) 段2c 付款段：advance_payment（预付）+ payment_request（货后），按 PO 聚合已付/付款状态。
    pay = {}
    if order_ids:
        for model, label in ((m.AdvancePayment, "advance"), (m.PaymentRequest, "post")):
            confirmed_col = getattr(model, "confirmed", None)
            stmt_p = (
                select(model.purchase_order_id, func.coalesce(func.sum(model.amount), 0),
                       func.max(model.payment_date), func.count(model.id))
                .where(model.purchase_order_id.in_(order_ids))
                .group_by(model.purchase_order_id)
            )
            for po_id, amt, last_pay_date, cnt in (await db.execute(stmt_p)).all():
                p = pay.setdefault(po_id, {"paid_amount": 0.0, "last_payment_date": None, "payment_count": 0})
                p["paid_amount"] += _num(amt)
                p["payment_count"] += int(cnt)
                if last_pay_date and (p["last_payment_date"] is None or _iso(last_pay_date) > p["last_payment_date"]):
                    p["last_payment_date"] = _iso(last_pay_date)

    rows = []
    for o in orders:
        a = agg.get(o.id, {"ordered_quantity": 0.0, "received_quantity": 0.0, "line_count": 0})
        in_transit = a["ordered_quantity"] - a["received_quantity"]
        row = {
            # PO 段（源 PO total）
            "purchase_order_id": o.id,
            "order_number": o.order_number,
            "po_date": o.po_date.isoformat() if o.po_date else None,
            "factory_so_number": o.factory_so_number,
            "supplier_id": o.supplier_id,
            "end_user": o.end_user,
            "product_manager_id": o.product_manager_id,
            "pd_id": o.pd_id,
            "purchase_assistant_id": o.purchase_assistant_id,
            "currency": o.currency,
            "status": o.status,
            "payment_terms_text": o.payment_terms_text,
            "notice_date": o.notice_date.isoformat() if o.notice_date else None,
            "expected_delivery_date": o.expected_delivery_date.isoformat() if o.expected_delivery_date else None,
            "actual_delivery_date": o.actual_delivery_date.isoformat() if o.actual_delivery_date else None,
            # 备货消单段
            "is_stock_order": o.is_stock_order,
            "stock_quantity": _num(o.stock_quantity) if o.stock_quantity is not None else None,
            "stock_reason": o.stock_reason,
            # 数量/在途段
            "line_count": a["line_count"],
            "ordered_quantity": a["ordered_quantity"],
            "received_quantity": a["received_quantity"],
            "in_transit_quantity": in_transit,
            # 买价段（🔒Q18：无权限者整列剔除）
            "total_amount": _num(o.total_amount),
            "advance_payment_amount": _num(o.advance_payment_amount),
            "stock_amount_original": _num(o.stock_amount_original) if o.stock_amount_original is not None else None,
            "stock_amount_latest": _num(o.stock_amount_latest) if o.stock_amount_latest is not None else None,
        }

        # 段2c 发货段（源 Shipping total）：发货日期 / 到库日期 / 发票号 / 跟踪状态。
        s = ship.get(o.id, {})
        row["shipped_date"] = s.get("shipped_date")
        row["warehouse_in_date"] = s.get("warehouse_in_date")
        row["invoice_number"] = s.get("invoice_number")
        row["track_status"] = s.get("track_status")
        # 段2c 付款段：付款状态 / 已付金额 / 应付余额（=发货额-已付，此处近似=订单额-已付）/ 付款日。
        p = pay.get(o.id, {"paid_amount": 0.0, "last_payment_date": None, "payment_count": 0})
        paid = p["paid_amount"]
        po_amount = _num(o.total_amount)
        row["paid_amount"] = paid
        row["payable_balance"] = po_amount - paid
        row["payment_status"] = (
            "PAID" if (po_amount > 0 and paid >= po_amount) else
            "PARTIAL" if paid > 0 else "UNPAID"
        )
        row["last_payment_date"] = p["last_payment_date"]

        for f in hidden:
            row.pop(f, None)
        rows.append(row)

    return {
        "rows": rows,
        "count": len(rows),
        "buy_price_visible": show_buy,
        # 段2c 已接入发货/付款段：发货日期/到库日期/发票号/付款状态/应付余额（买价列对销售端遮蔽）。
    }


@router.get("/intransit")
async def purchase_in_transit(
    purchase_assistant_id: int | None = Query(None, description="按 PA 过滤（缺省=本公司全部）"),
    open_only: bool = Query(True, description="只看未全到货的在途行（in_transit>0）"),
    limit: int = Query(200, le=500),
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    """采购在途台账（04a-6，只读聚合）。

    每行 = 一张「已下单未全到货」PO：订单/已收/在途数量（=订单-已收，实时聚合 PO 明细）+
    PA 录的承诺/最新货期 + 跟踪状态 + 提醒标记（alert_flag：超期未给货期/未发货）。
    在途数量列不涉买价（数量非金额），全角色可见；按 PA 过滤「只拉我的数据」。
    """
    today = date.today()
    company_ids = _company_filter(user)

    # 在途 = 已下单（过了财务审批）且未全到货。用 denylist 排「未下单 / 已闭环」状态，
    # 不用 allowlist（ORDERED/PARTIAL）——进项发票勾稽会把 PO 叠加成 INVOICE_MATCHING，
    # 但货可能仍在途（分批到货），不该因发票状态把在途行漏掉。最终由 in_transit>0 + open_only 把关。
    _NOT_IN_TRANSIT = ("START", "DRAFT", "PENDING_APPROVAL", "FINANCE_APPROVAL",
                       "REJECTED", "CANCELLED", "RECEIVED", "CLOSED")
    stmt = select(m.PurchaseOrder).where(m.PurchaseOrder.status.notin_(_NOT_IN_TRANSIT))
    if company_ids:
        stmt = stmt.where(m.PurchaseOrder.company_id.in_(company_ids))
    if purchase_assistant_id is not None:
        stmt = stmt.where(m.PurchaseOrder.purchase_assistant_id == purchase_assistant_id)
    stmt = stmt.order_by(m.PurchaseOrder.id.desc()).limit(limit)
    orders = (await db.execute(stmt)).scalars().all()
    order_ids = [o.id for o in orders]

    qty = {}
    if order_ids:
        line_stmt = (
            select(
                m.PurchaseOrderLine.purchase_order_id,
                func.coalesce(func.sum(m.PurchaseOrderLine.quantity), 0),
                func.coalesce(func.sum(m.PurchaseOrderLine.received_quantity), 0),
            )
            .where(m.PurchaseOrderLine.purchase_order_id.in_(order_ids))
            .group_by(m.PurchaseOrderLine.purchase_order_id)
        )
        for po_id, ordered, received in (await db.execute(line_stmt)).all():
            qty[po_id] = (_num(ordered), _num(received))

    track = {}
    if order_ids:
        it_stmt = select(m.PurchaseInTransit).where(m.PurchaseInTransit.purchase_order_id.in_(order_ids))
        for it in (await db.execute(it_stmt)).scalars().all():
            track[it.purchase_order_id] = it

    rows = []
    for o in orders:
        ordered, received = qty.get(o.id, (0.0, 0.0))
        in_transit = ordered - received
        if open_only and in_transit <= 0:
            continue
        it = track.get(o.id)
        promised_eta = it.promised_eta if it else None
        latest_eta = it.latest_eta if it else None
        track_status = it.track_status if it else "PENDING_ACCEPT"
        eta = promised_eta or latest_eta
        # 提醒标记：超期未发货 / 未给货期（与 notifications.scan_purchase_in_transit_alerts 同口径）。
        if track_status in ("PENDING_ACCEPT", "ACCEPTED") and not eta:
            alert_flag = "NO_ETA"
        elif eta is not None and eta < today and track_status not in ("SHIPPED", "PARTIAL", "RECEIVED"):
            alert_flag = "OVERDUE"
        else:
            alert_flag = "OK"
        rows.append({
            "purchase_order_id": o.id,
            "order_number": o.order_number,
            "supplier_id": o.supplier_id,
            "purchase_assistant_id": o.purchase_assistant_id,
            "po_date": _iso(o.po_date),
            "ordered_quantity": ordered,
            "received_quantity": received,
            "in_transit_qty": in_transit,
            "promised_eta": _iso(promised_eta),
            "latest_eta": _iso(latest_eta),
            "track_status": track_status,
            "shipped_date": _iso(it.shipped_date) if it else None,
            "alert_flag": alert_flag,
        })

    return {"rows": rows, "count": len(rows)}


@router.post("/intransit/scan-alerts")
async def scan_intransit_alerts(
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    """手动触发采购在途货期提醒扫描（承诺 ETA 过期且未发货 / 未给货期 → 写站内提醒派 PA）。
    写入在命令层 run_notification_scan，本路由保持只读不 db.add（守架构边界）。"""
    result = await execute_command(db, user, "run_notification_scan", {})
    if not result.get("success"):
        raise HTTPException(status_code=result.get("status_code", 400), detail=result.get("error") or "扫描失败")
    return {"success": True, **result}
