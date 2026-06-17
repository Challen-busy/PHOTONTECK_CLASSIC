"""销售路由：SO 签单大表 / 台账只读聚合（段3b 05 页面3）。

SA 核心工作台「SO 签单大表」全链全景：沿订单号 join SO 头 + SO 明细聚合（订单数量/已发货/在途）
+ 发货 shipment（发货时间/发货编号）+ 销项发票（开票时间/发票号）+ 收款 AR（收款金额/状态），
拼成一张只读台账行。在途数量 = SO 订单数量 − 已发货数量（分批发货后自动减）。

只读端点（无 db.add/commit），不走唯一写入路径——纯查询聚合（同 routers/purchase.py / reports.py 模式）。
🔒字段防火墙（总览 §8）：SO 是卖方视角，本台账**无买价/成本/利润点列**（只含 SO 卖价 total_amount、
发货数量、应收金额，均为卖方侧数据，对 SALES 可见）。不下钻报价 cost（cost 遮蔽在段3a query_data 层）。
跨公司汇总：BOSS / FINANCE_DIRECTOR（ROW_PRIVILEGED_ROLES）经 _company_filter 看全部 6 公司只读汇总
（总览 §9.2）；普通 SA 仅本公司，可按 SA / 销售 / 事业部过滤「只拉我的数据」。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import models as m
from core.auth import get_current_user
from core.database import get_db
from services.tools import _company_filter

router = APIRouter(prefix="/api/sales")


def _num(v) -> float:
    return float(v) if v is not None else 0.0


def _iso(d):
    return d.isoformat() if d else None


@router.get("/ledger")
async def sales_ledger(
    sales_assistant_id: int | None = Query(None, description="按 SA 过滤（缺省=本公司全部，受公司过滤约束）"),
    sales_engineer_id: int | None = Query(None, description="按销售（业务员）过滤"),
    business_unit: str | None = Query(None, description="按事业部（Memo）过滤"),
    status: str | None = Query(None, description="按 SO 状态过滤"),
    limit: int = Query(200, le=500),
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    """SO 签单大表 / 台账（只读聚合，沿订单号串全链一行 + 在途）。

    每行 = 一张 SO + 明细聚合（订单数量/已发货/在途）+ 发货段（发货日期/编号计数）
    + 销项发票段（最新发票号/开票日期）+ 收款段（已收金额/收款状态）。
    在途数量 = Σ订单数量 − Σ已发货（shipped_quantity，由出库 effect 回填 SO 明细）。
    无买价/成本/利润点列（卖方视角，PRD 05 页面3）。
    """
    company_ids = _company_filter(user)

    # 1) SO 头（按公司 + 可选 SA / 销售 / 事业部 / 状态过滤）。
    stmt = select(m.SalesOrder)
    if company_ids:
        stmt = stmt.where(m.SalesOrder.company_id.in_(company_ids))
    if sales_assistant_id is not None:
        stmt = stmt.where(m.SalesOrder.sales_assistant_id == sales_assistant_id)
    if sales_engineer_id is not None:
        stmt = stmt.where(m.SalesOrder.sales_engineer_id == sales_engineer_id)
    if business_unit is not None:
        stmt = stmt.where(m.SalesOrder.business_unit == business_unit)
    if status is not None:
        stmt = stmt.where(m.SalesOrder.status == status)
    stmt = stmt.order_by(m.SalesOrder.id.desc()).limit(limit)
    orders = (await db.execute(stmt)).scalars().all()
    order_ids = [o.id for o in orders]

    # 2) 明细聚合：按 SO 汇总 订单数量 / 已发货数量（沿 sales_order_id FK）。
    agg = {}
    if order_ids:
        line_stmt = (
            select(
                m.SalesOrderLine.sales_order_id,
                func.coalesce(func.sum(m.SalesOrderLine.quantity), 0),
                func.coalesce(func.sum(m.SalesOrderLine.shipped_quantity), 0),
                func.count(m.SalesOrderLine.id),
            )
            .where(m.SalesOrderLine.sales_order_id.in_(order_ids))
            .group_by(m.SalesOrderLine.sales_order_id)
        )
        for so_id, ordered_qty, shipped_qty, line_count in (await db.execute(line_stmt)).all():
            agg[so_id] = {
                "ordered_quantity": _num(ordered_qty),
                "shipped_quantity": _num(shipped_qty),
                "line_count": int(line_count),
            }

    # 3) 发货段：shipment_request（沿 sales_order_id FK）取最新发货日期 + 发货次数 + 最新发货编号。
    ship = {}
    if order_ids:
        sh_stmt = (
            select(
                m.ShipmentRequest.sales_order_id,
                func.max(m.ShipmentRequest.shipped_date),
                func.count(m.ShipmentRequest.id),
            )
            .where(m.ShipmentRequest.sales_order_id.in_(order_ids))
            .group_by(m.ShipmentRequest.sales_order_id)
        )
        for so_id, last_shipped, sh_count in (await db.execute(sh_stmt)).all():
            ship.setdefault(so_id, {})["last_shipped_date"] = _iso(last_shipped)
            ship[so_id]["shipment_count"] = int(sh_count)
        sn_stmt = (
            select(m.ShipmentRequest.sales_order_id, m.ShipmentRequest.shipment_number, m.ShipmentRequest.id)
            .where(m.ShipmentRequest.sales_order_id.in_(order_ids))
            .order_by(m.ShipmentRequest.id.desc())
        )
        for so_id, sh_no, _sh_id in (await db.execute(sn_stmt)).all():
            ship.setdefault(so_id, {}).setdefault("shipment_number", sh_no)

    # 4) 销项发票段：sales_invoice（沿 sales_order_id FK）取最新发票号 + 开票日期。
    inv = {}
    if order_ids:
        inv_stmt = (
            select(
                m.SalesInvoice.sales_order_id, m.SalesInvoice.invoice_number,
                m.SalesInvoice.invoice_date, m.SalesInvoice.id,
            )
            .where(m.SalesInvoice.sales_order_id.in_(order_ids))
            .order_by(m.SalesInvoice.id.desc())
        )
        for so_id, inv_no, inv_date, _inv_id in (await db.execute(inv_stmt)).all():
            if so_id not in inv:
                inv[so_id] = {"invoice_number": inv_no, "invoice_date": _iso(inv_date)}

    # 5) 收款段：accounts_receivable（沿 sales_order_id FK）聚合应收 / 已收 + 收款状态。
    recv = {}
    if order_ids:
        ar_stmt = (
            select(
                m.AccountsReceivable.sales_order_id,
                func.coalesce(func.sum(m.AccountsReceivable.amount), 0),
                func.coalesce(func.sum(m.AccountsReceivable.paid_amount), 0),
                func.count(m.AccountsReceivable.id),
            )
            .where(m.AccountsReceivable.sales_order_id.in_(order_ids))
            .group_by(m.AccountsReceivable.sales_order_id)
        )
        for so_id, ar_amount, ar_paid, ar_count in (await db.execute(ar_stmt)).all():
            recv[so_id] = {
                "receivable_amount": _num(ar_amount),
                "received_amount": _num(ar_paid),
                "ar_count": int(ar_count),
            }

    rows = []
    for o in orders:
        a = agg.get(o.id, {"ordered_quantity": 0.0, "shipped_quantity": 0.0, "line_count": 0})
        in_transit = a["ordered_quantity"] - a["shipped_quantity"]
        s = ship.get(o.id, {})
        iv = inv.get(o.id, {})
        rc = recv.get(o.id, {"receivable_amount": 0.0, "received_amount": 0.0, "ar_count": 0})
        ar_amt = rc["receivable_amount"]
        ar_paid = rc["received_amount"]
        row = {
            # SO 段（卖方视角，含卖价 total_amount，无买价/成本/利润点列）
            "sales_order_id": o.id,
            "order_number": o.order_number,                # 内部订单号（合同号）
            "external_order_no": o.external_order_no,       # 编号（客户订单号）
            "customer_po_number": o.customer_po_number,
            "customer_id": o.customer_id,
            "sales_engineer_id": o.sales_engineer_id,
            "sales_assistant_id": o.sales_assistant_id,
            "customer_region": o.customer_region,
            "business_unit": o.business_unit,
            "research_sub_market": o.research_sub_market,
            "currency": o.currency,
            "total_amount": _num(o.total_amount),           # SO 卖价合计（卖方侧，对 SALES 可见）
            "payment_terms_text": o.payment_terms_text,
            "requires_advance_receipt": o.requires_advance_receipt,
            "advance_receipt_confirmed": o.advance_receipt_confirmed,
            "signature_status": o.signature_status,
            "status": o.status,
            # 数量 / 在途段（订单 − 已发货 = 在途；分批发货后自动减）
            "line_count": a["line_count"],
            "ordered_quantity": a["ordered_quantity"],
            "shipped_quantity": a["shipped_quantity"],
            "in_transit_quantity": in_transit,
            # 发货段
            "shipment_count": s.get("shipment_count", 0),
            "last_shipped_date": s.get("last_shipped_date"),
            "shipment_number": s.get("shipment_number"),
            # 销项发票段
            "invoice_number": iv.get("invoice_number"),
            "invoice_date": iv.get("invoice_date"),
            # 收款段（到账口径，做账在金蝶，决策④）
            "receivable_amount": ar_amt,
            "received_amount": ar_paid,
            "receipt_status": (
                "RECEIVED" if (ar_amt > 0 and ar_paid >= ar_amt) else
                "PARTIAL" if ar_paid > 0 else "UNRECEIVED"
            ),
            # 派生完成状态：在途=0 即 Finished（PRD 页面3 状态列）。
            "ledger_status": "FINISHED" if (a["ordered_quantity"] > 0 and in_transit <= 0) else "OPEN",
        }
        rows.append(row)

    return {
        "rows": rows,
        "count": len(rows),
        "cross_company": company_ids is None,  # BOSS/FINANCE_DIRECTOR 跨公司只读汇总
    }
