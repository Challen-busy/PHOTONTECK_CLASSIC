"""采购路由：PO 总表 / 采购台账只读聚合（段2b 04a-4）。

PA 核心工作台的「跟单消单」全景：把 PO 头 + PO 明细 + 已收（received_quantity）
沿 FK 聚合成一张只读台账行，按 PA / 产线（purchase_assistant_id）过滤——PA「只拉我的数据」。
本段先出 PO 段 + 已收段（在途=订单-已收）；发货/付款段待段2c（标 TODO）。

只读端点（无 db.add/commit），不走唯一写入路径——纯查询聚合（同 routers/reports.py 模式）。
🔒Q18 字段防火墙：买价列（unit_price/total_price/total_amount/advance_payment_amount/
stock_amount_*）对销售端 SALES+SA 遮蔽（复用 services/tools._can_view_buy_price + BUY_PRICE_FIELDS）。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import models as m
from core.auth import get_current_user
from core.database import get_db
from services.tools import _company_filter, _can_view_buy_price, BUY_PRICE_FIELDS

router = APIRouter(prefix="/api/purchase")


def _num(v) -> float:
    return float(v) if v is not None else 0.0


# PO 头上属采购进价/成本、需对销售端遮蔽的列（与 BUY_PRICE_FIELDS 取交集，单一事实源）。
_PO_BUY_FIELDS = {"total_amount", "advance_payment_amount", "stock_amount_original", "stock_amount_latest"}


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
    hidden = _PO_BUY_FIELDS & BUY_PRICE_FIELDS if not show_buy else set()

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
        for f in hidden:
            row.pop(f, None)
        rows.append(row)

    return {
        "rows": rows,
        "count": len(rows),
        "buy_price_visible": show_buy,
        # 段2c TODO：发货/到库/付款段（聚合 shipment + advance_payment）尚未接入本台账。
        "todo": "发货/付款段（Shipping total）待段2c 接入：发货日期/到库日期/付款状态/应付余额。",
    }
