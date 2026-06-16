"""Phase 1 domain effects used by workflow transitions.

These functions replace business write hooks stored as workflow strings. They
run inside the surrounding workflow command transaction and must be idempotent.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import models as m
from services.workflow_extensions import register_transition_effect


def _num(value) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _actor_id(doc, user: m.UserAccount) -> int:
    return getattr(doc, "updated_by_id", None) or getattr(doc, "created_by_id", None) or user.id


# 货物性质 → 库存初态（PRD 03a-3 §「货物状态模型」）。样品入 SAMPLE、待检/RMA 入 QUARANTINE，
# 其余可售 AVAILABLE。值集为纯业务约定（出库占用读 inventory.status）。
def _inventory_status_for_nature(goods_nature: str | None) -> str:
    nature = (goods_nature or "").strip().upper()
    if nature in ("SAMPLE", "样品"):
        return "SAMPLE"
    if nature in ("RMA", "翻收", "待检", "QUARANTINE", "PENDING"):
        return "QUARANTINE"
    return "AVAILABLE"


async def _one(db: AsyncSession, model, *where):
    stmt = select(model)
    for clause in where:
        stmt = stmt.where(clause)
    return (await db.execute(stmt.limit(1))).scalar_one_or_none()


async def _all(db: AsyncSession, model, *where, order_by=None):
    stmt = select(model)
    for clause in where:
        stmt = stmt.where(clause)
    if order_by is not None:
        stmt = stmt.order_by(order_by)
    return (await db.execute(stmt)).scalars().all()


async def _workflow_version(db: AsyncSession, doc_type: str) -> int:
    row = await _one(
        db,
        m.WorkflowDefinition,
        m.WorkflowDefinition.doc_type == doc_type,
        m.WorkflowDefinition.is_active == True,
    )
    return row.version if row else 1


async def _status_log(
    db: AsyncSession,
    *,
    doc_type: str,
    doc_id: int,
    company_id: int,
    transition_name: str,
    from_state: str,
    to_state: str,
    triggered_by_id: int,
    comment: str,
) -> None:
    db.add(m.WorkflowLog(
        doc_type=doc_type,
        doc_id=doc_id,
        company_id=company_id,
        workflow_version=await _workflow_version(db, doc_type),
        transition_name=transition_name,
        from_state=from_state,
        to_state=to_state,
        triggered_by_id=triggered_by_id,
        changed_fields={"status": {"old": from_state, "new": to_state}},
        data_snapshot={},
        hooks_executed=[],
        comment=comment,
    ))


@register_transition_effect("crm.create_quotation_from_inquiry", auto=False)
async def create_quotation_from_inquiry(
    db: AsyncSession, doc_type: str, doc, to_state: str | None, user: m.UserAccount, command_log_id: int | None
) -> list[str]:
    existing = await _one(db, m.Quotation, m.Quotation.company_id == doc.company_id, m.Quotation.inquiry_id == doc.id)
    if existing:
        return [f"quotation already exists: {existing.id}"]

    lines = await _all(db, m.SalesInquiryLine, m.SalesInquiryLine.inquiry_id == doc.id, order_by=m.SalesInquiryLine.line_number)
    total = sum(_num(line.quantity) * _num(line.target_unit_price) for line in lines)
    quotation = m.Quotation(
        quotation_number=f"QT-I{doc.id}",
        inquiry_id=doc.id,
        customer_id=doc.customer_id,
        sales_assistant_id=doc.sales_assistant_id,
        product_manager_id=doc.product_manager_id,
        currency=doc.currency,
        total_amount=total,
        payment_terms_days=30,
        shipping_method="FOB",
        delivery_address=doc.delivery_address,
        packaging_requirements=doc.packaging_requirements,
        barcode_requirements=doc.barcode_requirements,
        company_id=doc.company_id,
        created_by_id=_actor_id(doc, user),
        status="DRAFT",
    )
    db.add(quotation)
    await db.flush()
    for line in lines:
        db.add(m.QuotationLine(
            quotation_id=quotation.id,
            line_number=line.line_number,
            material_id=line.material_id,
            product_description=line.product_description,
            quantity=line.quantity,
            unit_price=_num(line.target_unit_price),
            total_price=_num(line.quantity) * _num(line.target_unit_price),
        ))
    return [f"created quotation#{quotation.id} from inquiry#{doc.id}"]


@register_transition_effect("crm.create_sales_order_from_quotation", auto=False)
async def create_sales_order_from_quotation(
    db: AsyncSession, doc_type: str, doc, to_state: str | None, user: m.UserAccount, command_log_id: int | None
) -> list[str]:
    existing = await _one(db, m.SalesOrder, m.SalesOrder.company_id == doc.company_id, m.SalesOrder.quotation_id == doc.id)
    if existing:
        return [f"sales order already exists: {existing.id}"]

    lines = await _all(db, m.QuotationLine, m.QuotationLine.quotation_id == doc.id, order_by=m.QuotationLine.line_number)
    order = m.SalesOrder(
        order_number=f"SO-Q{doc.id}",
        customer_id=doc.customer_id,
        inquiry_id=doc.inquiry_id,
        quotation_id=doc.id,
        sales_assistant_id=doc.sales_assistant_id,
        currency=doc.currency,
        total_amount=doc.total_amount,
        payment_terms_days=doc.payment_terms_days,
        shipping_method=doc.shipping_method,
        delivery_address=doc.delivery_address,
        packaging_requirements=doc.packaging_requirements,
        barcode_requirements=doc.barcode_requirements,
        company_id=doc.company_id,
        created_by_id=_actor_id(doc, user),
        status="DRAFT",
    )
    db.add(order)
    await db.flush()
    for line in lines:
        if not line.material_id:
            continue
        db.add(m.SalesOrderLine(
            sales_order_id=order.id,
            line_number=line.line_number,
            material_id=line.material_id,
            quantity=line.quantity,
            unit_price=line.unit_price,
            total_price=line.total_price,
        ))
    return [f"created sales_order#{order.id} from quotation#{doc.id}"]


@register_transition_effect("erp.create_purchase_notice_from_sales_order", auto=False)
async def create_purchase_notice_from_sales_order(
    db: AsyncSession, doc_type: str, doc, to_state: str | None, user: m.UserAccount, command_log_id: int | None
) -> list[str]:
    existing = await _one(db, m.PurchaseNotice, m.PurchaseNotice.company_id == doc.company_id, m.PurchaseNotice.sales_order_id == doc.id)
    if existing:
        return [f"purchase notice already exists: {existing.id}"]

    lines = await _all(db, m.SalesOrderLine, m.SalesOrderLine.sales_order_id == doc.id, order_by=m.SalesOrderLine.line_number)
    notice = m.PurchaseNotice(
        notice_number=f"PN-SO{doc.id}",
        sales_order_id=doc.id,
        requested_by_id=doc.sales_assistant_id or _actor_id(doc, user),
        purchase_assistant_id=None,
        required_delivery_date=lines[0].requested_delivery_date if lines else None,
        company_id=doc.company_id,
        created_by_id=doc.sales_assistant_id or _actor_id(doc, user),
        status="DRAFT",
        notes=f"由销售订单 {doc.order_number} 自动生成",
    )
    db.add(notice)
    await db.flush()
    for line in lines:
        db.add(m.PurchaseNoticeLine(
            purchase_notice_id=notice.id,
            line_number=line.line_number,
            sales_order_line_id=line.id,
            material_id=line.material_id,
            quantity=line.quantity,
            required_delivery_date=line.requested_delivery_date,
            packaging_requirements=doc.packaging_requirements,
            barcode_requirements=doc.barcode_requirements,
        ))
    return [f"created purchase_notice#{notice.id} from sales_order#{doc.id}"]


@register_transition_effect("finance.create_advance_receipt_from_sales_order", auto=False)
async def create_advance_receipt_from_sales_order(
    db: AsyncSession, doc_type: str, doc, to_state: str | None, user: m.UserAccount, command_log_id: int | None
) -> list[str]:
    existing = await _one(db, m.AdvanceReceipt, m.AdvanceReceipt.company_id == doc.company_id, m.AdvanceReceipt.sales_order_id == doc.id)
    if existing:
        return [f"advance receipt already exists: {existing.id}"]
    row = m.AdvanceReceipt(
        receipt_number=f"AREC-SO{doc.id}",
        customer_id=doc.customer_id,
        sales_order_id=doc.id,
        amount=doc.advance_receipt_amount or doc.total_amount,
        currency=doc.currency,
        receipt_date=None,
        company_id=doc.company_id,
        created_by_id=_actor_id(doc, user),
        status="DRAFT",
        notes=f"由销售订单 {doc.order_number} 预收判断自动生成，待财务确认到账",
    )
    db.add(row)
    await db.flush()
    return [f"created advance_receipt#{row.id} from sales_order#{doc.id}"]


@register_transition_effect("erp.mark_sales_order_purchase_notice_sent", auto=False)
async def mark_sales_order_purchase_notice_sent(
    db: AsyncSession, doc_type: str, doc, to_state: str | None, user: m.UserAccount, command_log_id: int | None
) -> list[str]:
    if not doc.sales_order_id:
        return []
    order = await _one(db, m.SalesOrder, m.SalesOrder.id == doc.sales_order_id)
    if not order:
        return []
    old_status = order.status
    if old_status == "PURCHASE_NOTICE_SENT":
        return [f"sales_order#{order.id} already PURCHASE_NOTICE_SENT"]
    order.status = "PURCHASE_NOTICE_SENT"
    await _status_log(
        db,
        doc_type="SALES_ORDER",
        doc_id=order.id,
        company_id=order.company_id,
        transition_name="采购通知已提交 PA",
        from_state=old_status,
        to_state="PURCHASE_NOTICE_SENT",
        triggered_by_id=_actor_id(doc, user),
        comment=f"由采购通知 {doc.notice_number} 自动回写",
    )
    return [f"updated sales_order#{order.id} status PURCHASE_NOTICE_SENT"]


@register_transition_effect("erp.create_purchase_order_from_notice", auto=False)
async def create_purchase_order_from_notice(
    db: AsyncSession, doc_type: str, doc, to_state: str | None, user: m.UserAccount, command_log_id: int | None
) -> list[str]:
    existing = await _one(db, m.PurchaseOrder, m.PurchaseOrder.company_id == doc.company_id, m.PurchaseOrder.purchase_notice_id == doc.id)
    if existing:
        return [f"purchase order already exists: {existing.id}"]

    lines = await _all(db, m.PurchaseNoticeLine, m.PurchaseNoticeLine.purchase_notice_id == doc.id, order_by=m.PurchaseNoticeLine.line_number)
    order = m.PurchaseOrder(
        order_number=f"PO-N{doc.id}",
        supplier_id=lines[0].preferred_supplier_id if lines else None,
        purchase_assistant_id=doc.purchase_assistant_id,
        related_sales_order_id=doc.sales_order_id,
        purchase_notice_id=doc.id,
        currency="USD",
        total_amount=0,
        expected_delivery_date=doc.required_delivery_date,
        company_id=doc.company_id,
        created_by_id=_actor_id(doc, user),
        status="DRAFT",
    )
    db.add(order)
    await db.flush()
    for line in lines:
        db.add(m.PurchaseOrderLine(
            purchase_order_id=order.id,
            line_number=line.line_number,
            material_id=line.material_id,
            quantity=line.quantity,
            unit_price=0,
            total_price=0,
            sales_order_line_id=line.sales_order_line_id,
        ))
    return [f"created purchase_order#{order.id} from purchase_notice#{doc.id}"]


@register_transition_effect("finance.create_advance_payment_from_purchase_order", auto=False)
async def create_advance_payment_from_purchase_order(
    db: AsyncSession, doc_type: str, doc, to_state: str | None, user: m.UserAccount, command_log_id: int | None
) -> list[str]:
    existing = await _one(db, m.AdvancePayment, m.AdvancePayment.company_id == doc.company_id, m.AdvancePayment.purchase_order_id == doc.id)
    if existing:
        return [f"advance payment already exists: {existing.id}"]
    row = m.AdvancePayment(
        payment_number=f"APAY-PO{doc.id}",
        supplier_id=doc.supplier_id,
        purchase_order_id=doc.id,
        requested_by_id=doc.purchase_assistant_id or _actor_id(doc, user),
        amount=doc.advance_payment_amount or doc.total_amount,
        currency=doc.currency,
        payment_date=None,
        company_id=doc.company_id,
        created_by_id=_actor_id(doc, user),
        status="DRAFT",
        notes=f"由采购订单 {doc.order_number} 预付判断自动生成，待财务审核付款",
    )
    db.add(row)
    await db.flush()
    return [f"created advance_payment#{row.id} from purchase_order#{doc.id}"]


@register_transition_effect("wms.create_goods_receipt_from_purchase_order", auto=False)
async def create_goods_receipt_from_purchase_order(
    db: AsyncSession, doc_type: str, doc, to_state: str | None, user: m.UserAccount, command_log_id: int | None
) -> list[str]:
    existing = await _one(db, m.GoodsReceipt, m.GoodsReceipt.company_id == doc.company_id, m.GoodsReceipt.purchase_order_id == doc.id)
    if existing:
        return [f"goods receipt already exists: {existing.id}"]

    lines = await _all(db, m.PurchaseOrderLine, m.PurchaseOrderLine.purchase_order_id == doc.id, order_by=m.PurchaseOrderLine.line_number)
    warehouse = await _one(db, m.Warehouse, m.Warehouse.company_id == doc.company_id)
    receipt = m.GoodsReceipt(
        receipt_number=f"GR-PO{doc.id}",
        purchase_order_id=doc.id,
        warehouse_id=warehouse.id if warehouse else None,
        received_by_id=_actor_id(doc, user),
        received_date=doc.actual_delivery_date or date.today(),
        company_id=doc.company_id,
        created_by_id=_actor_id(doc, user),
        status="PENDING",
        notes=f"由采购订单 {doc.order_number} 到货动作自动生成",
    )
    db.add(receipt)
    await db.flush()
    for line in lines:
        db.add(m.GoodsReceiptLine(
            goods_receipt_id=receipt.id,
            purchase_order_line_id=line.id,
            material_id=line.material_id,
            expected_quantity=line.quantity,
            actual_quantity=line.quantity,
            batch_number=f"PO{doc.id}-L{line.line_number}",
            inbound_number=receipt.receipt_number,
            supplier_id=doc.supplier_id,
            uom=line.uom,
            source_doc_number=doc.order_number,
        ))
    return [f"created goods_receipt#{receipt.id} from purchase_order#{doc.id}"]


@register_transition_effect(
    "wms.match_goods_receipt_reviewer",
    doc_type="GOODS_RECEIPT",
    to_state="PA_REVIEW",
)
async def match_goods_receipt_reviewer(
    db: AsyncSession, doc_type: str, doc, to_state: str | None, user: m.UserAccount, command_log_id: int | None
) -> list[str]:
    """审核 PA 自动匹配（PRD 03a-1 reviewer_id）：提交审核时若头部未指定审核 PA，
    按头部供应商（或首行明细供应商）的 responsible_pa_id 自动带出（供应商-PA 对应表）。
    """
    if getattr(doc, "reviewer_id", None):
        return []
    supplier_id = getattr(doc, "supplier_id", None)
    if not supplier_id:
        first_line = await _one(
            db, m.GoodsReceiptLine, m.GoodsReceiptLine.goods_receipt_id == doc.id
        )
        supplier_id = getattr(first_line, "supplier_id", None) if first_line else None
    if not supplier_id:
        return ["审核 PA 未匹配：无供应商"]
    supplier = await _one(db, m.Supplier, m.Supplier.id == supplier_id)
    pa_id = getattr(supplier, "responsible_pa_id", None) if supplier else None
    if not pa_id:
        return ["审核 PA 未匹配：供应商无 responsible_pa"]
    doc.reviewer_id = pa_id
    return [f"matched reviewer={pa_id} from supplier={supplier_id}"]


@register_transition_effect("wms.stock_goods_receipt", auto=False)
async def stock_goods_receipt(
    db: AsyncSession, doc_type: str, doc, to_state: str | None, user: m.UserAccount, command_log_id: int | None
) -> list[str]:
    lines = await _all(db, m.GoodsReceiptLine, m.GoodsReceiptLine.goods_receipt_id == doc.id, order_by=m.GoodsReceiptLine.id)
    logs: list[str] = []
    for line in lines:
        inbound_number = line.inbound_number or doc.receipt_number
        batch_number = line.batch_number or f"GR{doc.id}-L{line.id}"
        existing = await _one(
            db,
            m.Inventory,
            m.Inventory.company_id == doc.company_id,
            m.Inventory.purchase_order_line_id == line.purchase_order_line_id,
            m.Inventory.inbound_number == inbound_number,
            m.Inventory.batch_number == batch_number,
        )
        if not existing:
            inv = m.Inventory(
                material_id=line.material_id,
                warehouse_id=doc.warehouse_id,
                batch_number=batch_number,
                inbound_number=inbound_number,
                source_doc_number=line.source_doc_number,
                serial_lot_number=line.serial_lot_number or line.batch_number,
                supplier_id=line.supplier_id,
                goods_nature=line.goods_nature,
                uom=line.uom,
                tracking_number=line.tracking_number,
                delivery_method=line.delivery_method,
                carton_number=line.carton_number,
                origin_country=line.origin_country,
                hs_code=line.hs_code,
                location_code=line.location_code,
                date_code=line.date_code,
                production_date=line.production_date,
                quantity=line.actual_quantity,
                received_date=doc.received_date or date.today(),
                purchase_order_line_id=line.purchase_order_line_id,
                reported_customer_id=getattr(doc, "customer_id", None),
                company_id=doc.company_id,
                created_by_id=_actor_id(doc, user),
                # 入库批次初态按货物性质置：样品→SAMPLE、待检/RMA→QUARANTINE、其余→可售（PRD 03a-3）。
                status=_inventory_status_for_nature(line.goods_nature),
            )
            db.add(inv)
            logs.append(f"created inventory from goods_receipt_line#{line.id}")
        if line.purchase_order_line_id:
            po_line = await _one(db, m.PurchaseOrderLine, m.PurchaseOrderLine.id == line.purchase_order_line_id)
            if po_line:
                po_line.received_quantity = line.actual_quantity
    return logs


@register_transition_effect("erp.complete_purchase_receipt_followup", auto=False)
async def complete_purchase_receipt_followup(
    db: AsyncSession, doc_type: str, doc, to_state: str | None, user: m.UserAccount, command_log_id: int | None
) -> list[str]:
    logs: list[str] = []
    purchase_order = await _one(db, m.PurchaseOrder, m.PurchaseOrder.id == doc.purchase_order_id) if doc.purchase_order_id else None
    lines = await _all(db, m.GoodsReceiptLine, m.GoodsReceiptLine.goods_receipt_id == doc.id, order_by=m.GoodsReceiptLine.id)
    if purchase_order:
        old_status = purchase_order.status
        if old_status != "STOCKED_IN":
            purchase_order.status = "STOCKED_IN"
            await _status_log(
                db,
                doc_type="PURCHASE_ORDER",
                doc_id=purchase_order.id,
                company_id=purchase_order.company_id,
                transition_name="入库单审核通过",
                from_state=old_status,
                to_state="STOCKED_IN",
                triggered_by_id=_actor_id(doc, user),
                comment=f"由入库单 {doc.receipt_number} 自动回写",
            )
            logs.append(f"updated purchase_order#{purchase_order.id} status STOCKED_IN")

        existing_invoice = await _one(db, m.PurchaseInvoice, m.PurchaseInvoice.company_id == doc.company_id, m.PurchaseInvoice.goods_receipt_id == doc.id)
        if not existing_invoice:
            amount = Decimal("0")
            po_lines_by_id = {}
            for line in lines:
                po_line = await _one(db, m.PurchaseOrderLine, m.PurchaseOrderLine.id == line.purchase_order_line_id)
                po_lines_by_id[line.purchase_order_line_id] = po_line
                amount += _num(line.actual_quantity) * _num(po_line.unit_price if po_line else 0)
            invoice = m.PurchaseInvoice(
                invoice_number=f"PI-GR{doc.id}",
                supplier_id=purchase_order.supplier_id,
                purchase_order_id=purchase_order.id,
                goods_receipt_id=doc.id,
                amount=amount,
                currency=purchase_order.currency,
                tax_rate=0,
                invoice_date=None,
                company_id=doc.company_id,
                created_by_id=_actor_id(doc, user),
                status="DRAFT",
                notes=f"由入库单 {doc.receipt_number} 自动生成，发票号待财务替换为供应商正式发票号",
            )
            db.add(invoice)
            await db.flush()
            for idx, line in enumerate(lines, start=1):
                po_line = po_lines_by_id.get(line.purchase_order_line_id)
                if not po_line:
                    continue
                db.add(m.PurchaseInvoiceLine(
                    purchase_invoice_id=invoice.id,
                    line_number=idx,
                    purchase_order_line_id=line.purchase_order_line_id,
                    goods_receipt_line_id=line.id,
                    material_id=line.material_id,
                    quantity=line.actual_quantity,
                    unit_price=po_line.unit_price,
                    total_price=_num(line.actual_quantity) * _num(po_line.unit_price),
                    tax_rate=0,
                ))
            logs.append(f"created purchase_invoice#{invoice.id} from goods_receipt#{doc.id}")
    return logs


@register_transition_effect("wms.create_shipment_from_sales_order", auto=False)
async def create_shipment_from_sales_order(
    db: AsyncSession, doc_type: str, doc, to_state: str | None, user: m.UserAccount, command_log_id: int | None
) -> list[str]:
    existing = await _one(db, m.ShipmentRequest, m.ShipmentRequest.company_id == doc.company_id, m.ShipmentRequest.sales_order_id == doc.id)
    if existing:
        return [f"shipment already exists: {existing.id}"]
    shipment = m.ShipmentRequest(
        shipment_number=f"SH-SO{doc.id}",
        sales_order_id=doc.id,
        requested_by_id=doc.sales_assistant_id or _actor_id(doc, user),
        approved_by_id=None,
        warehouse_id=None,
        shipping_method=doc.shipping_method,
        source_purchase_order_number="",
        payment_terms_text=doc.payment_terms_text,
        packaging_requirements=doc.packaging_requirements,
        barcode_requirements=doc.barcode_requirements,
        delivery_requirements=doc.delivery_address,
        company_id=doc.company_id,
        created_by_id=doc.sales_assistant_id or _actor_id(doc, user),
        status="DRAFT",
        notes=f"由销售订单 {doc.order_number} 自动生成",
    )
    db.add(shipment)
    await db.flush()
    return [f"created shipment#{shipment.id} from sales_order#{doc.id}"]


@register_transition_effect("wms.apply_shipment_stock_out", auto=False)
async def apply_shipment_stock_out(
    db: AsyncSession, doc_type: str, doc, to_state: str | None, user: m.UserAccount, command_log_id: int | None
) -> list[str]:
    logs: list[str] = []
    sales_order = await _one(db, m.SalesOrder, m.SalesOrder.id == doc.sales_order_id) if doc.sales_order_id else None
    lines = await _all(db, m.ShipmentLine, m.ShipmentLine.shipment_id == doc.id, order_by=m.ShipmentLine.id)
    for line in lines:
        already_moved = await _one(
            db,
            m.InventoryMovement,
            m.InventoryMovement.movement_type == "SHIPMENT_OUT",
            m.InventoryMovement.source_doc_type == "SHIPMENT_LINE",
            m.InventoryMovement.source_doc_id == line.id,
        )
        if already_moved:
            logs.append(f"shipment_line#{line.id} already stocked out")
            continue

        inventory = None
        if line.inventory_id:
            result = await db.execute(select(m.Inventory).where(m.Inventory.id == line.inventory_id).with_for_update())
            inventory = result.scalar_one_or_none()
        if inventory:
            remaining = _num(line.quantity)
            if sales_order:
                reservations = await _all(
                    db,
                    m.InventoryReservation,
                    m.InventoryReservation.inventory_id == line.inventory_id,
                    m.InventoryReservation.customer_id == sales_order.customer_id,
                    m.InventoryReservation.status == "ACTIVE",
                    order_by=m.InventoryReservation.id,
                )
                for reservation in reservations:
                    if remaining <= 0:
                        break
                    consume = min(_num(reservation.quantity), remaining)
                    new_qty = _num(reservation.quantity) - consume
                    if new_qty <= 0:
                        reservation.quantity = 0
                        reservation.status = "RELEASED"
                        reservation.released_at = datetime.now()
                    else:
                        reservation.quantity = new_qty
                    remaining -= consume
            inventory.quantity = _num(inventory.quantity) - _num(line.quantity)
            inventory.reserved_quantity = max(_num(inventory.reserved_quantity) - _num(line.quantity), Decimal("0"))
            inventory.status = "AVAILABLE" if _num(inventory.quantity) > _num(inventory.reserved_quantity) else "RESERVED"
            logs.append(f"reduced inventory#{inventory.id} by {line.quantity}")
        if line.sales_order_line_id:
            so_line = await _one(db, m.SalesOrderLine, m.SalesOrderLine.id == line.sales_order_line_id)
            if so_line:
                so_line.shipped_quantity = line.quantity
    return logs


@register_transition_effect("finance.create_sales_invoice_from_shipment", auto=False)
async def create_sales_invoice_from_shipment(
    db: AsyncSession, doc_type: str, doc, to_state: str | None, user: m.UserAccount, command_log_id: int | None
) -> list[str]:
    sales_order = await _one(db, m.SalesOrder, m.SalesOrder.id == doc.sales_order_id) if doc.sales_order_id else None
    if not sales_order:
        return []
    existing = await _one(db, m.SalesInvoice, m.SalesInvoice.company_id == doc.company_id, m.SalesInvoice.shipment_id == doc.id)
    if existing:
        return [f"sales invoice already exists: {existing.id}"]

    lines = await _all(db, m.ShipmentLine, m.ShipmentLine.shipment_id == doc.id, order_by=m.ShipmentLine.id)
    sales_lines_by_id = {}
    amount = Decimal("0")
    for line in lines:
        so_line = await _one(db, m.SalesOrderLine, m.SalesOrderLine.id == line.sales_order_line_id)
        sales_lines_by_id[line.sales_order_line_id] = so_line
        amount += _num(line.quantity) * _num(so_line.unit_price if so_line else 0)
    invoice = m.SalesInvoice(
        invoice_number=f"SI-SH{doc.id}",
        customer_id=sales_order.customer_id,
        sales_order_id=sales_order.id,
        shipment_id=doc.id,
        amount=amount,
        currency=sales_order.currency,
        tax_rate=0,
        invoice_date=None,
        company_id=doc.company_id,
        created_by_id=_actor_id(doc, user),
        status="DRAFT",
        notes=f"由发货单 {doc.shipment_number} 自动生成，发票号待财务替换为正式销售发票号",
    )
    db.add(invoice)
    await db.flush()
    for line in lines:
        so_line = sales_lines_by_id.get(line.sales_order_line_id)
        if not so_line:
            continue
        db.add(m.SalesInvoiceLine(
            sales_invoice_id=invoice.id,
            line_number=line.id,
            sales_order_line_id=line.sales_order_line_id,
            shipment_line_id=line.id,
            material_id=so_line.material_id,
            quantity=line.quantity,
            unit_price=so_line.unit_price,
            total_price=_num(line.quantity) * _num(so_line.unit_price),
            tax_rate=0,
            cost_amount=0,
        ))
    return [f"created sales_invoice#{invoice.id} from shipment#{doc.id}"]


@register_transition_effect("wms.create_sales_return_from_shipment", auto=False)
async def create_sales_return_from_shipment(
    db: AsyncSession, doc_type: str, doc, to_state: str | None, user: m.UserAccount, command_log_id: int | None
) -> list[str]:
    sales_order = await _one(db, m.SalesOrder, m.SalesOrder.id == doc.sales_order_id) if doc.sales_order_id else None
    if not sales_order:
        return []
    existing = await _one(db, m.SalesReturn, m.SalesReturn.company_id == doc.company_id, m.SalesReturn.shipment_id == doc.id)
    if existing:
        return [f"sales return already exists: {existing.id}"]
    lines = await _all(db, m.ShipmentLine, m.ShipmentLine.shipment_id == doc.id, order_by=m.ShipmentLine.id)
    row = m.SalesReturn(
        return_number=f"SR-SH{doc.id}",
        sales_order_id=sales_order.id,
        shipment_id=doc.id,
        customer_id=sales_order.customer_id,
        warehouse_id=doc.warehouse_id,
        return_reason="",
        logistics_tracking_number=doc.tracking_number,
        company_id=doc.company_id,
        created_by_id=_actor_id(doc, user),
        status="DRAFT",
        notes=f"由发货单 {doc.shipment_number} 客户退货动作自动生成",
    )
    db.add(row)
    await db.flush()
    for line in lines:
        so_line = await _one(db, m.SalesOrderLine, m.SalesOrderLine.id == line.sales_order_line_id)
        if not so_line:
            continue
        db.add(m.SalesReturnLine(
            sales_return_id=row.id,
            line_number=line.id,
            sales_order_line_id=line.sales_order_line_id,
            shipment_line_id=line.id,
            material_id=so_line.material_id,
            quantity=line.quantity,
            quality_status="PENDING",
            return_action="RESTOCK",
        ))
    return [f"created sales_return#{row.id} from shipment#{doc.id}"]


@register_transition_effect("finance.create_accounts_payable_from_purchase_invoice", auto=False)
async def create_accounts_payable_from_purchase_invoice(
    db: AsyncSession, doc_type: str, doc, to_state: str | None, user: m.UserAccount, command_log_id: int | None
) -> list[str]:
    existing = await _one(db, m.AccountsPayable, m.AccountsPayable.company_id == doc.company_id, m.AccountsPayable.invoice_number == doc.invoice_number)
    if existing:
        return [f"accounts payable already exists: {existing.id}"]
    row = m.AccountsPayable(
        supplier_id=doc.supplier_id,
        purchase_order_id=doc.purchase_order_id,
        invoice_number=doc.invoice_number,
        amount=doc.amount,
        currency=doc.currency,
        due_date=date.today(),
        company_id=doc.company_id,
        created_by_id=_actor_id(doc, user),
        status="PENDING",
    )
    db.add(row)
    await db.flush()
    return [f"created accounts_payable#{row.id} from purchase_invoice#{doc.id}"]


@register_transition_effect("erp.mark_purchase_order_invoice_matching", auto=False)
async def mark_purchase_order_invoice_matching(
    db: AsyncSession, doc_type: str, doc, to_state: str | None, user: m.UserAccount, command_log_id: int | None
) -> list[str]:
    if not doc.purchase_order_id:
        return []
    order = await _one(db, m.PurchaseOrder, m.PurchaseOrder.id == doc.purchase_order_id)
    if not order:
        return []
    old_status = order.status
    if old_status == "INVOICE_MATCHING":
        return [f"purchase_order#{order.id} already INVOICE_MATCHING"]
    order.status = "INVOICE_MATCHING"
    await _status_log(
        db,
        doc_type="PURCHASE_ORDER",
        doc_id=order.id,
        company_id=order.company_id,
        transition_name="采购发票已勾稽",
        from_state=old_status,
        to_state="INVOICE_MATCHING",
        triggered_by_id=_actor_id(doc, user),
        comment=f"由采购发票 {doc.invoice_number} 自动回写",
    )
    return [f"updated purchase_order#{order.id} status INVOICE_MATCHING"]


@register_transition_effect("finance.create_accounts_receivable_from_sales_invoice", auto=False)
async def create_accounts_receivable_from_sales_invoice(
    db: AsyncSession, doc_type: str, doc, to_state: str | None, user: m.UserAccount, command_log_id: int | None
) -> list[str]:
    existing = await _one(db, m.AccountsReceivable, m.AccountsReceivable.company_id == doc.company_id, m.AccountsReceivable.invoice_number == doc.invoice_number)
    if existing:
        return [f"accounts receivable already exists: {existing.id}"]
    row = m.AccountsReceivable(
        customer_id=doc.customer_id,
        sales_order_id=doc.sales_order_id,
        invoice_number=doc.invoice_number,
        amount=doc.amount,
        currency=doc.currency,
        due_date=date.today(),
        company_id=doc.company_id,
        created_by_id=_actor_id(doc, user),
        status="PENDING",
    )
    db.add(row)
    await db.flush()
    return [f"created accounts_receivable#{row.id} from sales_invoice#{doc.id}"]
