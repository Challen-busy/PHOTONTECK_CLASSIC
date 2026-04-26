"""单据链路监控：统一查看 CRM / ERP / WMS / 财务单据状态。"""

from collections import defaultdict
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

import models as m
from core.auth import get_current_user
from core.database import get_db
from services.tools import _company_filter, _serialize_row, _user_can_access_table

router = APIRouter()


DOC_NUMBERS = {
    "sales_inquiry": "inquiry_number",
    "quotation": "quotation_number",
    "sales_order": "order_number",
    "purchase_notice": "notice_number",
    "purchase_order": "order_number",
    "goods_receipt": "receipt_number",
    "shipment_request": "shipment_number",
    "sales_return": "return_number",
    "advance_receipt": "receipt_number",
    "advance_payment": "payment_number",
    "purchase_invoice": "invoice_number",
    "sales_invoice": "invoice_number",
    "accounts_payable": "invoice_number",
    "accounts_receivable": "invoice_number",
}

GROUPS = [
    {"key": "crm", "name": "CRM", "tables": ["sales_inquiry", "quotation"]},
    {"key": "erp_sales", "name": "ERP 销售", "tables": ["sales_order", "advance_receipt", "purchase_notice"]},
    {"key": "erp_purchase", "name": "ERP 采购", "tables": ["purchase_order", "advance_payment"]},
    {"key": "wms", "name": "WMS", "tables": ["goods_receipt", "shipment_request", "sales_return"]},
    {"key": "finance", "name": "财务", "tables": ["purchase_invoice", "sales_invoice", "accounts_payable", "accounts_receivable"]},
]

STAGE_LABELS = {
    "all": "全部阶段",
    "crm": "CRM 售前",
    "erp_sales": "ERP 销售",
    "erp_purchase": "ERP 采购",
    "wms": "WMS 仓储",
    "finance": "财务勾稽",
    "completed": "已完成",
    "exception": "异常/取消",
}

TERMINAL_OK = {
    "QUOTATION_CREATED",
    "SALES_ORDER_CREATED",
    "PURCHASE_ORDER_CREATED",
    "CONFIRMED",
    "PAID",
    "STOCKED_IN",
    "CUSTOMER_RECEIVED",
    "AP_CREATED",
    "AR_CREATED",
    "COMPLETED",
    "DONE",
    "CLOSED",
}
TERMINAL_BAD = {
    "REJECTED",
    "CANCELLED",
    "CUSTOMER_REJECTED",
    "RETURN_REQUESTED",
    "CREDIT_PROCESSING",
}


def _first_doc_type(row, fallback: str) -> str:
    doc_types = getattr(row, "__doc_types__", None) or ()
    return doc_types[0] if doc_types else fallback.upper()


def _status_labels_by_doc_type(workflows: list[m.WorkflowDefinition]) -> dict[str, dict[str, str]]:
    labels: dict[str, dict[str, str]] = {}
    for wf in workflows:
        labels.setdefault(wf.doc_type, {})
        for state in wf.states or []:
            if not isinstance(state, dict):
                continue
            code = state.get("code")
            if code:
                labels[wf.doc_type][code] = state.get("name") or code
    return labels


def _doc_payload(row, table_name: str, user: m.UserAccount, status_labels: dict[str, dict[str, str]]) -> dict:
    data = _serialize_row(row, table_name, user)
    doc_type = _first_doc_type(row, table_name)
    status = data.get("status")
    number_field = DOC_NUMBERS.get(table_name)
    amount = data.get("total_amount", data.get("amount"))
    return {
        "id": data.get("id"),
        "doc_type": doc_type,
        "table": table_name,
        "number": data.get(number_field) if number_field else None,
        "status": status,
        "status_name": status_labels.get(doc_type, {}).get(status, status),
        "amount": amount,
        "currency": data.get("currency"),
        "updated_at": data.get("updated_at"),
        "data": data,
    }


def _group_by(rows: list, field: str) -> dict[Any, list]:
    grouped: dict[Any, list] = defaultdict(list)
    for row in rows:
        key = getattr(row, field, None)
        if key is not None:
            grouped[key].append(row)
    return grouped


def _ids(rows: list) -> list[int]:
    return [row.id for row in rows if getattr(row, "id", None) is not None]


def _unique(rows: list) -> list:
    return list({row.id: row for row in rows if getattr(row, "id", None) is not None}.values())


def _apply_company_scope(stmt, user: m.UserAccount, model):
    company_ids = _company_filter(user)
    if company_ids and hasattr(model, "company_id"):
        stmt = stmt.where(model.company_id.in_(company_ids))
    return stmt


async def _select_visible(
    db: AsyncSession,
    user: m.UserAccount,
    model,
    table_name: str,
    *where_clauses,
    limit: int | None = None,
) -> list:
    if not _user_can_access_table(user, table_name):
        return []
    stmt = _apply_company_scope(select(model), user, model)
    for clause in where_clauses:
        stmt = stmt.where(clause)
    if hasattr(model, "updated_at"):
        stmt = stmt.order_by(model.updated_at.desc(), model.id.desc())
    else:
        stmt = stmt.order_by(model.id.desc())
    if limit:
        stmt = stmt.limit(limit)
    return (await db.execute(stmt)).scalars().all()


async def _load_status_labels(db: AsyncSession) -> dict[str, dict[str, str]]:
    result = await db.execute(select(m.WorkflowDefinition).where(m.WorkflowDefinition.is_active == True))
    return _status_labels_by_doc_type(result.scalars().all())


async def _load_customer_names(db: AsyncSession, user: m.UserAccount, customer_ids: set[int]) -> dict[int, str]:
    if not customer_ids or not _user_can_access_table(user, "customer"):
        return {}
    stmt = _apply_company_scope(select(m.Customer).where(m.Customer.id.in_(customer_ids)), user, m.Customer)
    rows = (await db.execute(stmt)).scalars().all()
    names = {}
    for row in rows:
        names[row.id] = row.short_name or row.name or row.code or f"#{row.id}"
    return names


async def _load_sales_orders(
    db: AsyncSession,
    user: m.UserAccount,
    search: str,
    limit: int,
) -> tuple[list[m.SalesOrder], set[int], set[int]]:
    """返回销售订单，以及搜索命中的售前单据 ID。

    命中任意下游单据时，先反查到关联销售订单；如果命中的是还没有生成
    销售订单的询价/报价，则作为售前链路返回。
    """

    sales_order_ids: set[int] = set()
    matched_inquiry_ids: set[int] = set()
    matched_quotation_ids: set[int] = set()

    if not search:
        sales_orders = await _select_visible(db, user, m.SalesOrder, "sales_order", limit=limit)
        return sales_orders, matched_inquiry_ids, matched_quotation_ids

    kw = f"%{search.strip()}%"
    purchase_order_ids: set[int] = set()
    purchase_notice_ids: set[int] = set()
    goods_receipt_ids: set[int] = set()
    shipment_ids: set[int] = set()

    sales_orders = await _select_visible(
        db,
        user,
        m.SalesOrder,
        "sales_order",
        or_(
            m.SalesOrder.order_number.ilike(kw),
            m.SalesOrder.customer_po_number.ilike(kw),
            m.SalesOrder.quotation_reference.ilike(kw),
        ),
    )
    sales_order_ids.update(row.id for row in sales_orders)

    inquiries = await _select_visible(db, user, m.SalesInquiry, "sales_inquiry", m.SalesInquiry.inquiry_number.ilike(kw))
    matched_inquiry_ids.update(row.id for row in inquiries)

    quotations = await _select_visible(db, user, m.Quotation, "quotation", m.Quotation.quotation_number.ilike(kw))
    matched_quotation_ids.update(row.id for row in quotations)
    matched_inquiry_ids.update(row.inquiry_id for row in quotations if row.inquiry_id)

    purchase_notices = await _select_visible(db, user, m.PurchaseNotice, "purchase_notice", m.PurchaseNotice.notice_number.ilike(kw))
    sales_order_ids.update(row.sales_order_id for row in purchase_notices if row.sales_order_id)
    purchase_notice_ids.update(row.id for row in purchase_notices)

    purchase_orders = await _select_visible(db, user, m.PurchaseOrder, "purchase_order", m.PurchaseOrder.order_number.ilike(kw))
    sales_order_ids.update(row.related_sales_order_id for row in purchase_orders if row.related_sales_order_id)
    purchase_notice_ids.update(row.purchase_notice_id for row in purchase_orders if row.purchase_notice_id)
    purchase_order_ids.update(row.id for row in purchase_orders)

    goods_receipts = await _select_visible(db, user, m.GoodsReceipt, "goods_receipt", m.GoodsReceipt.receipt_number.ilike(kw))
    purchase_order_ids.update(row.purchase_order_id for row in goods_receipts if row.purchase_order_id)
    goods_receipt_ids.update(row.id for row in goods_receipts)

    shipments = await _select_visible(db, user, m.ShipmentRequest, "shipment_request", m.ShipmentRequest.shipment_number.ilike(kw))
    sales_order_ids.update(row.sales_order_id for row in shipments if row.sales_order_id)
    shipment_ids.update(row.id for row in shipments)

    sales_returns = await _select_visible(db, user, m.SalesReturn, "sales_return", m.SalesReturn.return_number.ilike(kw))
    sales_order_ids.update(row.sales_order_id for row in sales_returns if row.sales_order_id)
    shipment_ids.update(row.shipment_id for row in sales_returns if row.shipment_id)

    advance_receipts = await _select_visible(db, user, m.AdvanceReceipt, "advance_receipt", m.AdvanceReceipt.receipt_number.ilike(kw))
    sales_order_ids.update(row.sales_order_id for row in advance_receipts if row.sales_order_id)

    advance_payments = await _select_visible(db, user, m.AdvancePayment, "advance_payment", m.AdvancePayment.payment_number.ilike(kw))
    purchase_order_ids.update(row.purchase_order_id for row in advance_payments if row.purchase_order_id)

    purchase_invoices = await _select_visible(db, user, m.PurchaseInvoice, "purchase_invoice", m.PurchaseInvoice.invoice_number.ilike(kw))
    purchase_order_ids.update(row.purchase_order_id for row in purchase_invoices if row.purchase_order_id)
    goods_receipt_ids.update(row.goods_receipt_id for row in purchase_invoices if row.goods_receipt_id)

    sales_invoices = await _select_visible(db, user, m.SalesInvoice, "sales_invoice", m.SalesInvoice.invoice_number.ilike(kw))
    sales_order_ids.update(row.sales_order_id for row in sales_invoices if row.sales_order_id)
    shipment_ids.update(row.shipment_id for row in sales_invoices if row.shipment_id)

    accounts_payable = await _select_visible(db, user, m.AccountsPayable, "accounts_payable", m.AccountsPayable.invoice_number.ilike(kw))
    purchase_order_ids.update(row.purchase_order_id for row in accounts_payable if row.purchase_order_id)

    accounts_receivable = await _select_visible(db, user, m.AccountsReceivable, "accounts_receivable", m.AccountsReceivable.invoice_number.ilike(kw))
    sales_order_ids.update(row.sales_order_id for row in accounts_receivable if row.sales_order_id)

    if shipment_ids:
        rows = await _select_visible(db, user, m.ShipmentRequest, "shipment_request", m.ShipmentRequest.id.in_(shipment_ids))
        sales_order_ids.update(row.sales_order_id for row in rows if row.sales_order_id)

    if goods_receipt_ids:
        rows = await _select_visible(db, user, m.GoodsReceipt, "goods_receipt", m.GoodsReceipt.id.in_(goods_receipt_ids))
        purchase_order_ids.update(row.purchase_order_id for row in rows if row.purchase_order_id)

    if purchase_order_ids:
        rows = await _select_visible(db, user, m.PurchaseOrder, "purchase_order", m.PurchaseOrder.id.in_(purchase_order_ids))
        sales_order_ids.update(row.related_sales_order_id for row in rows if row.related_sales_order_id)
        purchase_notice_ids.update(row.purchase_notice_id for row in rows if row.purchase_notice_id)

    if purchase_notice_ids:
        rows = await _select_visible(db, user, m.PurchaseNotice, "purchase_notice", m.PurchaseNotice.id.in_(purchase_notice_ids))
        sales_order_ids.update(row.sales_order_id for row in rows if row.sales_order_id)

    if matched_quotation_ids or matched_inquiry_ids:
        conditions = []
        if matched_quotation_ids:
            conditions.append(m.SalesOrder.quotation_id.in_(matched_quotation_ids))
        if matched_inquiry_ids:
            conditions.append(m.SalesOrder.inquiry_id.in_(matched_inquiry_ids))
        if conditions:
            rows = await _select_visible(db, user, m.SalesOrder, "sales_order", or_(*conditions))
            sales_order_ids.update(row.id for row in rows)

    if sales_order_ids:
        sales_orders = await _select_visible(db, user, m.SalesOrder, "sales_order", m.SalesOrder.id.in_(sales_order_ids))
    else:
        sales_orders = []

    return sales_orders[:limit], matched_inquiry_ids, matched_quotation_ids


async def _load_default_presales(
    db: AsyncSession,
    user: m.UserAccount,
    limit: int,
) -> tuple[list[m.SalesInquiry], list[m.Quotation]]:
    linked_quote_ids = select(m.SalesOrder.quotation_id).where(m.SalesOrder.quotation_id.is_not(None))
    linked_inquiry_ids_by_so = select(m.SalesOrder.inquiry_id).where(m.SalesOrder.inquiry_id.is_not(None))
    linked_inquiry_ids_by_quote = select(m.Quotation.inquiry_id).where(m.Quotation.inquiry_id.is_not(None))

    quotations = await _select_visible(
        db,
        user,
        m.Quotation,
        "quotation",
        ~m.Quotation.id.in_(linked_quote_ids),
        limit=limit,
    )
    inquiries = await _select_visible(
        db,
        user,
        m.SalesInquiry,
        "sales_inquiry",
        ~m.SalesInquiry.id.in_(linked_inquiry_ids_by_so),
        ~m.SalesInquiry.id.in_(linked_inquiry_ids_by_quote),
        limit=limit,
    )
    return inquiries, quotations


async def _load_presales_by_ids(
    db: AsyncSession,
    user: m.UserAccount,
    inquiry_ids: set[int],
    quotation_ids: set[int],
) -> tuple[list[m.SalesInquiry], list[m.Quotation]]:
    quotations = await _select_visible(db, user, m.Quotation, "quotation", m.Quotation.id.in_(quotation_ids)) if quotation_ids else []
    inquiry_ids = set(inquiry_ids)
    inquiry_ids.update(row.inquiry_id for row in quotations if row.inquiry_id)
    inquiries = await _select_visible(db, user, m.SalesInquiry, "sales_inquiry", m.SalesInquiry.id.in_(inquiry_ids)) if inquiry_ids else []
    return inquiries, quotations


def _is_bad_status(status: str | None) -> bool:
    if not status:
        return False
    return status in TERMINAL_BAD or "CANCEL" in status or "REJECT" in status


def _is_ok_terminal(status: str | None) -> bool:
    return bool(status and status in TERMINAL_OK)


def _has_active(rows: list) -> bool:
    for row in rows:
        status = getattr(row, "status", None)
        if not _is_ok_terminal(status) and not _is_bad_status(status):
            return True
    return False


def _stage_for_chain(sales_order: m.SalesOrder | None, docs_by_group: dict[str, list]) -> tuple[str, str]:
    all_docs = [doc for docs in docs_by_group.values() for doc in docs]
    if any(_is_bad_status(getattr(doc, "status", None)) for doc in all_docs):
        return "exception", STAGE_LABELS["exception"]

    if sales_order is None:
        return "crm", STAGE_LABELS["crm"]

    if sales_order.status == "COMPLETED":
        return "completed", STAGE_LABELS["completed"]

    if _has_active(docs_by_group.get("finance", [])):
        return "finance", STAGE_LABELS["finance"]
    if sales_order.status == "SHIPMENT_REQUESTED" or _has_active(docs_by_group.get("wms", [])):
        return "wms", STAGE_LABELS["wms"]
    if sales_order.status == "PURCHASE_NOTICE_SENT" or _has_active(docs_by_group.get("erp_purchase", [])):
        return "erp_purchase", STAGE_LABELS["erp_purchase"]
    return "erp_sales", STAGE_LABELS["erp_sales"]


def _updated_sort_value(item: dict) -> datetime:
    raw = item.get("summary", {}).get("updated_at")
    if isinstance(raw, datetime):
        return raw
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return datetime.min
    return datetime.min


def _visible_groups(
    docs_by_group: dict[str, list],
    user: m.UserAccount,
    status_labels: dict[str, dict[str, str]],
) -> list[dict]:
    permissions = {table: _user_can_access_table(user, table) for group in GROUPS for table in group["tables"]}
    groups = []
    for group in GROUPS:
        rows = docs_by_group.get(group["key"], [])
        docs = []
        for row in rows:
            table_name = row.__tablename__
            if table_name in group["tables"]:
                docs.append(_doc_payload(row, table_name, user, status_labels))
        groups.append({
            "key": group["key"],
            "name": group["name"],
            "visible": any(permissions.get(table) for table in group["tables"]),
            "docs": docs,
        })
    return groups


def _sales_order_item(
    so: m.SalesOrder,
    docs_by_group: dict[str, list],
    user: m.UserAccount,
    status_labels: dict[str, dict[str, str]],
    customer_names: dict[int, str],
) -> dict:
    stage_key, stage_name = _stage_for_chain(so, docs_by_group)
    summary = _doc_payload(so, "sales_order", user, status_labels)
    summary.update({
        "root_doc_type": "SALES_ORDER",
        "root_table": "sales_order",
        "root_id": so.id,
        "root_number": summary.get("number"),
        "root_label": "销售订单",
        "sales_order_id": so.id,
        "order_number": summary.get("number"),
        "customer_po_number": summary["data"].get("customer_po_number"),
        "customer_name": customer_names.get(so.customer_id),
        "stage_key": stage_key,
        "stage_name": stage_name,
    })
    return {"summary": summary, "groups": _visible_groups(docs_by_group, user, status_labels)}


def _presales_item(
    root,
    docs_by_group: dict[str, list],
    table_name: str,
    user: m.UserAccount,
    status_labels: dict[str, dict[str, str]],
    customer_names: dict[int, str],
) -> dict:
    summary = _doc_payload(root, table_name, user, status_labels)
    doc_type = _first_doc_type(root, table_name)
    stage_key, stage_name = _stage_for_chain(None, docs_by_group)
    summary.update({
        "root_doc_type": doc_type,
        "root_table": table_name,
        "root_id": root.id,
        "root_number": summary.get("number"),
        "root_label": "报价单" if table_name == "quotation" else "客户询价",
        "sales_order_id": None,
        "order_number": None,
        "customer_po_number": "",
        "customer_name": customer_names.get(getattr(root, "customer_id", None)),
        "stage_key": stage_key,
        "stage_name": stage_name,
    })
    return {"summary": summary, "groups": _visible_groups(docs_by_group, user, status_labels)}


@router.get("/api/order-chains")
async def order_chains(
    search: str = "",
    stage: str = "all",
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    limit = max(1, min(limit, 100))
    search = search.strip()
    stage = stage if stage in STAGE_LABELS else "all"
    query_limit = min(limit * 5, 500) if stage != "all" and not search else limit

    sales_orders, matched_inquiry_ids, matched_quotation_ids = await _load_sales_orders(db, user, search, query_limit)
    sales_order_ids = _ids(sales_orders)
    sales_order_inquiry_ids = {row.inquiry_id for row in sales_orders if row.inquiry_id}
    sales_order_quotation_ids = {row.quotation_id for row in sales_orders if row.quotation_id}

    if search:
        presales_inquiries, presales_quotations = await _load_presales_by_ids(db, user, matched_inquiry_ids, matched_quotation_ids)
        presales_quotations = [row for row in presales_quotations if row.id not in sales_order_quotation_ids]
        presales_inquiries = [row for row in presales_inquiries if row.id not in sales_order_inquiry_ids]
    else:
        presales_inquiries, presales_quotations = await _load_default_presales(db, user, query_limit)

    inquiry_ids = set(sales_order_inquiry_ids)
    inquiry_ids.update(row.id for row in presales_inquiries)
    inquiry_ids.update(row.inquiry_id for row in presales_quotations if row.inquiry_id)
    quotation_ids = set(sales_order_quotation_ids)
    quotation_ids.update(row.id for row in presales_quotations)
    customer_ids = {row.customer_id for row in sales_orders if row.customer_id}
    customer_ids.update(row.customer_id for row in presales_inquiries if row.customer_id)
    customer_ids.update(row.customer_id for row in presales_quotations if row.customer_id)

    status_labels = await _load_status_labels(db)
    inquiries = await _select_visible(db, user, m.SalesInquiry, "sales_inquiry", m.SalesInquiry.id.in_(inquiry_ids)) if inquiry_ids else []
    quotations = await _select_visible(db, user, m.Quotation, "quotation", m.Quotation.id.in_(quotation_ids)) if quotation_ids else []

    purchase_notices = await _select_visible(
        db, user, m.PurchaseNotice, "purchase_notice", m.PurchaseNotice.sales_order_id.in_(sales_order_ids)
    ) if sales_order_ids else []
    purchase_notice_ids = _ids(purchase_notices)

    po_conditions = []
    if sales_order_ids:
        po_conditions.append(m.PurchaseOrder.related_sales_order_id.in_(sales_order_ids))
    if purchase_notice_ids:
        po_conditions.append(m.PurchaseOrder.purchase_notice_id.in_(purchase_notice_ids))
    purchase_orders = await _select_visible(db, user, m.PurchaseOrder, "purchase_order", or_(*po_conditions)) if po_conditions else []
    purchase_order_ids = _ids(purchase_orders)

    goods_receipts = await _select_visible(
        db, user, m.GoodsReceipt, "goods_receipt", m.GoodsReceipt.purchase_order_id.in_(purchase_order_ids)
    ) if purchase_order_ids else []
    goods_receipt_ids = _ids(goods_receipts)

    purchase_invoice_conditions = []
    if purchase_order_ids:
        purchase_invoice_conditions.append(m.PurchaseInvoice.purchase_order_id.in_(purchase_order_ids))
    if goods_receipt_ids:
        purchase_invoice_conditions.append(m.PurchaseInvoice.goods_receipt_id.in_(goods_receipt_ids))
    purchase_invoices = await _select_visible(
        db, user, m.PurchaseInvoice, "purchase_invoice", or_(*purchase_invoice_conditions)
    ) if purchase_invoice_conditions else []

    advance_receipts = await _select_visible(
        db, user, m.AdvanceReceipt, "advance_receipt", m.AdvanceReceipt.sales_order_id.in_(sales_order_ids)
    ) if sales_order_ids else []
    advance_payments = await _select_visible(
        db, user, m.AdvancePayment, "advance_payment", m.AdvancePayment.purchase_order_id.in_(purchase_order_ids)
    ) if purchase_order_ids else []

    shipments = await _select_visible(
        db, user, m.ShipmentRequest, "shipment_request", m.ShipmentRequest.sales_order_id.in_(sales_order_ids)
    ) if sales_order_ids else []
    shipment_ids = _ids(shipments)

    sales_invoice_conditions = []
    if sales_order_ids:
        sales_invoice_conditions.append(m.SalesInvoice.sales_order_id.in_(sales_order_ids))
    if shipment_ids:
        sales_invoice_conditions.append(m.SalesInvoice.shipment_id.in_(shipment_ids))
    sales_invoices = await _select_visible(db, user, m.SalesInvoice, "sales_invoice", or_(*sales_invoice_conditions)) if sales_invoice_conditions else []

    sales_return_conditions = []
    if sales_order_ids:
        sales_return_conditions.append(m.SalesReturn.sales_order_id.in_(sales_order_ids))
    if shipment_ids:
        sales_return_conditions.append(m.SalesReturn.shipment_id.in_(shipment_ids))
    sales_returns = await _select_visible(db, user, m.SalesReturn, "sales_return", or_(*sales_return_conditions)) if sales_return_conditions else []

    purchase_invoice_numbers = {row.invoice_number for row in purchase_invoices if row.invoice_number}
    accounts_payable_conditions = []
    if purchase_order_ids:
        accounts_payable_conditions.append(m.AccountsPayable.purchase_order_id.in_(purchase_order_ids))
    if purchase_invoice_numbers:
        accounts_payable_conditions.append(m.AccountsPayable.invoice_number.in_(purchase_invoice_numbers))
    accounts_payable = await _select_visible(
        db, user, m.AccountsPayable, "accounts_payable", or_(*accounts_payable_conditions)
    ) if accounts_payable_conditions else []

    sales_invoice_numbers = {row.invoice_number for row in sales_invoices if row.invoice_number}
    accounts_receivable_conditions = []
    if sales_order_ids:
        accounts_receivable_conditions.append(m.AccountsReceivable.sales_order_id.in_(sales_order_ids))
    if sales_invoice_numbers:
        accounts_receivable_conditions.append(m.AccountsReceivable.invoice_number.in_(sales_invoice_numbers))
    accounts_receivable = await _select_visible(
        db, user, m.AccountsReceivable, "accounts_receivable", or_(*accounts_receivable_conditions)
    ) if accounts_receivable_conditions else []

    customer_names = await _load_customer_names(db, user, customer_ids)

    inquiry_by_id = {row.id: row for row in inquiries}
    quotation_by_id = {row.id: row for row in quotations}
    quotations_by_inquiry = _group_by(quotations, "inquiry_id")
    purchase_notices_by_so = _group_by(purchase_notices, "sales_order_id")
    purchase_orders_by_so = _group_by(purchase_orders, "related_sales_order_id")
    for row in purchase_orders:
        if row.purchase_notice_id:
            for notice in purchase_notices:
                if notice.id == row.purchase_notice_id and notice.sales_order_id:
                    purchase_orders_by_so[notice.sales_order_id].append(row)
                    break
    purchase_orders_by_so = {so_id: _unique(rows) for so_id, rows in purchase_orders_by_so.items()}

    goods_receipts_by_po = _group_by(goods_receipts, "purchase_order_id")
    purchase_invoices_by_po = _group_by(purchase_invoices, "purchase_order_id")
    purchase_invoices_by_gr = _group_by(purchase_invoices, "goods_receipt_id")
    advance_payments_by_po = _group_by(advance_payments, "purchase_order_id")
    accounts_payable_by_po = _group_by(accounts_payable, "purchase_order_id")
    accounts_payable_by_invoice = _group_by(accounts_payable, "invoice_number")
    advance_receipts_by_so = _group_by(advance_receipts, "sales_order_id")
    shipments_by_so = _group_by(shipments, "sales_order_id")
    sales_invoices_by_so = _group_by(sales_invoices, "sales_order_id")
    sales_invoices_by_shipment = _group_by(sales_invoices, "shipment_id")
    sales_returns_by_so = _group_by(sales_returns, "sales_order_id")
    sales_returns_by_shipment = _group_by(sales_returns, "shipment_id")
    accounts_receivable_by_so = _group_by(accounts_receivable, "sales_order_id")
    accounts_receivable_by_invoice = _group_by(accounts_receivable, "invoice_number")

    items = []
    for so in sales_orders:
        so_purchase_orders = purchase_orders_by_so.get(so.id, [])
        so_purchase_order_ids = {row.id for row in so_purchase_orders}
        so_goods_receipts = [
            receipt
            for po_id in so_purchase_order_ids
            for receipt in goods_receipts_by_po.get(po_id, [])
        ]
        so_goods_receipt_ids = {row.id for row in so_goods_receipts}
        so_purchase_invoices = [
            invoice
            for po_id in so_purchase_order_ids
            for invoice in purchase_invoices_by_po.get(po_id, [])
        ] + [
            invoice
            for gr_id in so_goods_receipt_ids
            for invoice in purchase_invoices_by_gr.get(gr_id, [])
        ]
        so_purchase_invoices = _unique(so_purchase_invoices)

        so_advance_payments = [
            payment
            for po_id in so_purchase_order_ids
            for payment in advance_payments_by_po.get(po_id, [])
        ]
        so_accounts_payable = [
            payable
            for po_id in so_purchase_order_ids
            for payable in accounts_payable_by_po.get(po_id, [])
        ] + [
            payable
            for invoice in so_purchase_invoices
            for payable in accounts_payable_by_invoice.get(invoice.invoice_number, [])
        ]
        so_accounts_payable = _unique(so_accounts_payable)

        so_shipments = shipments_by_so.get(so.id, [])
        so_shipment_ids = {row.id for row in so_shipments}
        so_sales_invoices = sales_invoices_by_so.get(so.id, []) + [
            invoice
            for shipment_id in so_shipment_ids
            for invoice in sales_invoices_by_shipment.get(shipment_id, [])
        ]
        so_sales_invoices = _unique(so_sales_invoices)
        so_sales_returns = sales_returns_by_so.get(so.id, []) + [
            ret
            for shipment_id in so_shipment_ids
            for ret in sales_returns_by_shipment.get(shipment_id, [])
        ]
        so_sales_returns = _unique(so_sales_returns)
        so_accounts_receivable = accounts_receivable_by_so.get(so.id, []) + [
            receivable
            for invoice in so_sales_invoices
            for receivable in accounts_receivable_by_invoice.get(invoice.invoice_number, [])
        ]
        so_accounts_receivable = _unique(so_accounts_receivable)

        docs_by_group = {
            "crm": (
                ([inquiry_by_id[so.inquiry_id]] if so.inquiry_id in inquiry_by_id else [])
                + ([quotation_by_id[so.quotation_id]] if so.quotation_id in quotation_by_id else [])
            ),
            "erp_sales": [so] + advance_receipts_by_so.get(so.id, []) + purchase_notices_by_so.get(so.id, []),
            "erp_purchase": so_purchase_orders + so_advance_payments,
            "wms": so_goods_receipts + so_shipments + so_sales_returns,
            "finance": so_purchase_invoices + so_sales_invoices + so_accounts_payable + so_accounts_receivable,
        }
        items.append(_sales_order_item(so, docs_by_group, user, status_labels, customer_names))

    sales_order_quotation_ids = {row.quotation_id for row in sales_orders if row.quotation_id}
    presales_quotation_ids = set()
    for quote in presales_quotations:
        if quote.id in sales_order_quotation_ids:
            continue
        docs_by_group = {
            "crm": ([inquiry_by_id[quote.inquiry_id]] if quote.inquiry_id in inquiry_by_id else []) + [quote],
            "erp_sales": [],
            "erp_purchase": [],
            "wms": [],
            "finance": [],
        }
        items.append(_presales_item(quote, docs_by_group, "quotation", user, status_labels, customer_names))
        presales_quotation_ids.add(quote.id)

    inquiry_ids_with_quote = {quote.inquiry_id for quote in presales_quotations if quote.inquiry_id}
    for inquiry in presales_inquiries:
        if inquiry.id in sales_order_inquiry_ids or inquiry.id in inquiry_ids_with_quote:
            continue
        docs_by_group = {
            "crm": [inquiry] + [quote for quote in quotations_by_inquiry.get(inquiry.id, []) if quote.id not in presales_quotation_ids],
            "erp_sales": [],
            "erp_purchase": [],
            "wms": [],
            "finance": [],
        }
        items.append(_presales_item(inquiry, docs_by_group, "sales_inquiry", user, status_labels, customer_names))

    if stage != "all":
        items = [item for item in items if item.get("summary", {}).get("stage_key") == stage]

    items.sort(key=_updated_sort_value, reverse=True)
    items = items[:limit]

    permissions = {table: _user_can_access_table(user, table) for group in GROUPS for table in group["tables"]}
    return {
        "items": items,
        "total": len(items),
        "stage": stage,
        "stage_options": [{"key": key, "name": name} for key, name in STAGE_LABELS.items()],
        "permissions": permissions,
    }
