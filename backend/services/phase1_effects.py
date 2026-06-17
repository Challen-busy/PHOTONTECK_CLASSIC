"""Phase 1 domain effects used by workflow transitions.

These functions replace business write hooks stored as workflow strings. They
run inside the surrounding workflow command transaction and must be idempotent.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
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
            # 出库数量负数口径（出庫登記沿用），扣结存取 abs（PRD 03b 第7点）。
            qty_abs = abs(_num(line.quantity))
            remaining = qty_abs
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
            inventory.quantity = _num(inventory.quantity) - qty_abs
            inventory.reserved_quantity = max(_num(inventory.reserved_quantity) - qty_abs, Decimal("0"))
            inventory.status = "AVAILABLE" if _num(inventory.quantity) > _num(inventory.reserved_quantity) else "RESERVED"
            logs.append(f"reduced inventory#{inventory.id} by {qty_abs}")
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
    # 04a-7 ★审核留痕：财务审核通过这一刻回写 reviewed_by/at（editable_fields 已放行该两列）。
    if getattr(doc, "reviewed_by_id", None) is None:
        doc.reviewed_by_id = _actor_id(doc, user)
    if getattr(doc, "reviewed_at", None) is None:
        doc.reviewed_at = datetime.now()
    existing = await _one(db, m.AccountsPayable, m.AccountsPayable.company_id == doc.company_id, m.AccountsPayable.invoice_number == doc.invoice_number)
    if existing:
        return [f"accounts payable already exists: {existing.id}"]
    row = m.AccountsPayable(
        supplier_id=doc.supplier_id,
        purchase_order_id=doc.purchase_order_id,
        invoice_number=doc.invoice_number,
        amount=doc.amount,
        currency=doc.currency,
        due_date=getattr(doc, "due_date", None) or date.today(),
        company_id=doc.company_id,
        created_by_id=_actor_id(doc, user),
        status="PENDING",
    )
    db.add(row)
    await db.flush()
    return [f"created accounts_payable#{row.id} from purchase_invoice#{doc.id}"]


@register_transition_effect("finance.confirm_payment_request_settlement", auto=False)
async def confirm_payment_request_settlement(
    db: AsyncSession, doc_type: str, doc, to_state: str | None, user: m.UserAccount, command_log_id: int | None
) -> list[str]:
    """付款申请到账确认（04a-8 决策④）：打到账确认标记 + 应付余额递减。

    本系统只记到账确认 + 台账（做账/付款执行在金蝶）：confirmed=True，并把已审进项发票对应的
    accounts_payable.paid_amount 累加本次付款额（递减应付余额=amount-paid_amount），结清置 PAID。
    幂等：confirmed 已为 True 则 no-op（防退回再触发重复递减）。
    """
    if getattr(doc, "confirmed", False):
        return [f"payment_request#{doc.id} already confirmed"]
    doc.confirmed = True
    logs = [f"payment_request#{doc.id} confirmed (到账确认)"]

    # 沿 purchase_invoice → invoice_number 定位应付，递减余额（货后付款须关联已审进项发票）。
    ap = None
    if getattr(doc, "purchase_invoice_id", None):
        inv = await _one(db, m.PurchaseInvoice, m.PurchaseInvoice.id == doc.purchase_invoice_id)
        if inv:
            ap = await _one(
                db, m.AccountsPayable,
                m.AccountsPayable.company_id == doc.company_id,
                m.AccountsPayable.invoice_number == inv.invoice_number,
            )
    if ap is not None:
        ap.paid_amount = _num(ap.paid_amount) + _num(doc.amount)
        ap.paid_date = doc.payment_date or date.today()
        if _num(ap.paid_amount) >= _num(ap.amount):
            ap.status = "PAID"
        logs.append(f"accounts_payable#{ap.id} paid_amount={ap.paid_amount} status={ap.status}")
    return logs


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


# ============================================================
# 段2d-1 备货申请（04b-1 STOCK_UP_REQUEST）domain effects
# ============================================================

@register_transition_effect(
    "stockup.snapshot_stock_and_transit",
    doc_type="STOCK_UP_REQUEST",
    to_state="START",
)
async def snapshot_stock_and_transit(
    db: AsyncSession, doc_type: str, doc, to_state: str | None, user: m.UserAccount, command_log_id: int | None
) -> list[str]:
    """建单（进 START）时拍下当时库存 + 在途快照（只读列，04b-1 字段表）。

    - stock_on_hand = Σ inventory.quantity（按 material + company 聚合，全状态结存）。
    - in_transit_qty = Σ(PO 明细 quantity − received_quantity)（同 material+company 的未到货在途，
      口径对齐 routers/purchase.py 在途 = 订单数量 − 已收）。
    幂等守卫：仅在快照列为空时拍（防退回初态/再触发覆盖原始快照）。material_id 缺则 no-op。
    """
    if doc.material_id is None or doc.company_id is None:
        return []
    if doc.stock_on_hand is not None or doc.in_transit_qty is not None:
        return []  # 已有快照，跳过

    on_hand = (await db.execute(
        select(func.coalesce(func.sum(m.Inventory.quantity), 0)).where(
            m.Inventory.material_id == doc.material_id,
            m.Inventory.company_id == doc.company_id,
        )
    )).scalar() or 0

    # 在途 = Σ(订单数量 − 已收)，按 PO→明细 沿 material+company 关联（只算 material 命中的明细行）。
    in_transit = (await db.execute(
        select(
            func.coalesce(
                func.sum(m.PurchaseOrderLine.quantity - m.PurchaseOrderLine.received_quantity), 0
            )
        )
        .select_from(m.PurchaseOrderLine)
        .join(m.PurchaseOrder, m.PurchaseOrderLine.purchase_order_id == m.PurchaseOrder.id)
        .where(
            m.PurchaseOrderLine.material_id == doc.material_id,
            m.PurchaseOrder.company_id == doc.company_id,
        )
    )).scalar() or 0

    doc.stock_on_hand = _num(on_hand)
    doc.in_transit_qty = max(_num(in_transit), Decimal("0"))
    await db.flush()
    return [f"备货快照 material#{doc.material_id} 库存={doc.stock_on_hand} 在途={doc.in_transit_qty}"]


@register_transition_effect(
    "stockup.open_review_cosign",
    doc_type="STOCK_UP_REQUEST",
    to_state="PENDING_REVIEW",
)
async def open_review_cosign(
    db: AsyncSession, doc_type: str, doc, to_state: str | None, user: m.UserAccount, command_log_id: int | None
) -> list[str]:
    """≥20万进会审态（PENDING_REVIEW）时预生成 PM+FINANCE 待签行（并行会签标准件）。

    集齐放行校验器由 services/cosign.register_cosign_checkpoint 注册（PENDING_REVIEW→APPROVED 前跑）。
    幂等：generate_cosign_lines 对已存在的角色行跳过。
    """
    from services.cosign import generate_cosign_lines

    created = await generate_cosign_lines(
        db,
        doc_type="STOCK_UP_REQUEST",
        doc_id=doc.id,
        company_id=doc.company_id,
        required_roles=["PRODUCT_MANAGER", "FINANCE"],
        cosign_group="STOCK_REVIEW",
        created_by_id=_actor_id(doc, user),
    )
    return [f"备货会审预生成待签行 {len(created)} 条（PM+FINANCE）"]


# ============================================================
# 段2d-2 样品 SDN（04b-3）domain effects
# ============================================================

@register_transition_effect(
    "sample.assign_sdn_number",
    doc_type="SAMPLE_SDN",
    to_state="START",
)
async def assign_sdn_number(
    db: AsyncSession, doc_type: str, doc, to_state: str | None, user: m.UserAccount, command_log_id: int | None
) -> list[str]:
    """建单（进 START）时取 SDN 号 SDN-{C/L}-YYMM-NNN（04b-3，§00-7 供应商线字母在中间）。

    引擎通用编号 allocator 只产 prefix-period-seq（SDN-YYMM-NNN）；本 effect 复用它取月度连号后，
    把 supplier_line（C/L…）拼进 prefix 与 period 之间，得 SDN-C-2606-001。
    幂等守卫：仅当 sdn_number 为空或仍是引擎默认兜底号时取号（防退回初态/再触发重号）。
    """
    from services.numbering import allocate_next_number
    from services.numbering_effect import _is_overwritable

    if doc.company_id is None:
        return []
    if not _is_overwritable(doc.sdn_number):
        return []  # 已是业务号，跳过

    allocated = await allocate_next_number(db, doc.company_id, "SAMPLE_SDN", updated_by_id=user.id)
    if not allocated:
        return []  # 无规则 → 留引擎默认号

    line = (doc.supplier_line or "").strip().upper()
    number = allocated["number"]
    if line:
        # 在 prefix 后插线字母：SDN-2606-001 → SDN-C-2606-001（按首个分隔符切，稳）。
        parts = number.split("-", 1)
        number = f"{parts[0]}-{line}-{parts[1]}" if len(parts) == 2 else f"{number}-{line}"
    doc.sdn_number = number
    await db.flush()
    return [f"分配样品单号 SAMPLE_SDN.sdn_number={number}"]


@register_transition_effect(
    "sample.convert_to_available",
    doc_type="SAMPLE_SDN",
    to_state="CONVERTED",
    auto=False,
)
async def sample_convert_to_available(
    db: AsyncSession, doc_type: str, doc, to_state: str | None, user: m.UserAccount, command_log_id: int | None
) -> list[str]:
    """样品测试通过转正（进 CONVERTED）：该批库存 SAMPLE→AVAILABLE（§5.4 / 03，可下正式单）。

    按 SDN 子表型号匹配该公司 status=SAMPLE 的库存批次置 AVAILABLE。幂等：已 AVAILABLE 的不重置。
    """
    lines = await _all(db, m.SampleSdnLine, m.SampleSdnLine.sample_sdn_id == doc.id, order_by=m.SampleSdnLine.id)
    material_ids = {ln.material_id for ln in lines}
    if not material_ids:
        return []
    converted = 0
    for material_id in material_ids:
        rows = await _all(
            db, m.Inventory,
            m.Inventory.company_id == doc.company_id,
            m.Inventory.material_id == material_id,
            m.Inventory.status == "SAMPLE",
        )
        for inv in rows:
            inv.status = "AVAILABLE"
            inv.updated_by_id = _actor_id(doc, user)
            converted += 1
    return [f"样品转正：material{sorted(material_ids)} 共 {converted} 批 SAMPLE→AVAILABLE"]


# ============================================================
# 段2d-2 RMA 退货统一单（04b-5/04b-6）domain effects
# ============================================================

def _add_months(d: date, months: int) -> date:
    """质保到期 = 发货日 + warranty_months（纯日期算，无 dateutil）。"""
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    # 防 2/30 越界：取该月最后一天兜底（28~31）。
    for day in (d.day, 28, 29, 30, 31):
        try:
            return date(year, month, min(day, 31))
        except ValueError:
            continue
    return date(year, month, 28)


@register_transition_effect(
    "rma.assess_warranty_and_origin",
    doc_type="RMA",
    to_state="ESCALATED_PM",
    auto=False,
)
async def rma_assess_warranty_and_origin(
    db: AsyncSession, doc_type: str, doc, to_state: str | None, user: m.UserAccount, command_log_id: int | None
) -> list[str]:
    """PA 核料判定（进 ESCALATED_PM 成立边）：自动倒查写 sold_by_us + under_warranty（gap-7 给建议）。

    - sold_by_us：按 RMA 子表 SN/LOT 倒查同公司 shipment_line 是否有我方出库记录（命中即我方卖）。
    - under_warranty：ship_date + material.warranty_months vs today（在保=True，过保=False）。
      ship_date 缺或 warranty_months 缺则留 None（PA 人工判，不强拦）。
    判定为建议，PA 据此走成立(ESCALATED_PM)/驳回(REJECTED 边)；本 effect 只写判定列，不改状态。
    """
    lines = await _all(db, m.RmaLine, m.RmaLine.rma_id == doc.id, order_by=m.RmaLine.id)
    sns = [ln.serial_lot_number for ln in lines if (ln.serial_lot_number or "").strip()]

    # sold_by_us：任一行 SN 命中同公司出库记录即判我方卖。
    sold = None
    if sns:
        hit = await _one(
            db, m.ShipmentLine,
            m.ShipmentLine.serial_lot_number.in_(sns),
        )
        # 出库行经 shipment 落公司：用子查询过滤同公司更稳，这里子表无 company_id → 经 inventory 兜底。
        sold = hit is not None
    doc.sold_by_us = sold

    # under_warranty：ship_date + warranty_months（取子表首型号质保期）vs today。
    warranty = None
    if doc.ship_date and lines:
        mat = await _one(db, m.Material, m.Material.id == lines[0].material_id)
        months = getattr(mat, "warranty_months", None) if mat else None
        if months:
            warranty = _add_months(doc.ship_date, int(months)) >= date.today()
    doc.under_warranty = warranty

    await db.flush()
    return [f"RMA 核料：sold_by_us={doc.sold_by_us} under_warranty={doc.under_warranty}（PA 据此判成立/驳回）"]


@register_transition_effect(
    "rma.create_return_inbound",
    doc_type="RMA",
    to_state="RETURN_TO_CUSTOMER",
    auto=False,
)
async def rma_create_return_inbound(
    db: AsyncSession, doc_type: str, doc, to_state: str | None, user: m.UserAccount, command_log_id: int | None
) -> list[str]:
    """货回入库（GOODS_RETURNED→RETURN_TO_CUSTOMER 推进）：生成退货入库批次带 source_marker（04b-6）。

    按 RMA 子表逐行建 inventory 批次：inbound 走退货入库语义（goods_nature=RETURN），
    source_marker={rma来源, 品质好坏, 原厂}（§5.4 来源/品质标记，可叠加筛选）；
    好货（quality_result!=BAD）status=AVAILABLE 混回可售，坏货 status=NG 不可售。
    幂等：同 RMA 号 + 子表行号已建过的批次跳过（batch_number = RMA{号}-L{line}）。
    """
    lines = await _all(db, m.RmaLine, m.RmaLine.rma_id == doc.id, order_by=m.RmaLine.id)
    logs: list[str] = []
    for line in lines:
        batch_number = f"{doc.rma_number}-L{line.line_number}"
        existing = await _one(
            db, m.Inventory,
            m.Inventory.company_id == doc.company_id,
            m.Inventory.batch_number == batch_number,
        )
        if existing:
            continue
        quality = (line.quality_result or "").strip().upper()
        is_bad = quality == "BAD"
        marker = {
            "rma_source": doc.pm_decision or "RMA",   # VENDOR 原厂换/退/修 / INTERNAL 客退（决策来源）
            "quality": "BAD" if is_bad else "GOOD",
            "supplier_id": doc.supplier_id,
            "rma_number": doc.rma_number,
        }
        inv = m.Inventory(
            company_id=doc.company_id,
            material_id=line.material_id,
            inbound_number=doc.rma_number,
            source_doc_number=doc.rma_number,
            batch_number=batch_number,
            serial_lot_number=line.serial_lot_number,
            supplier_id=doc.supplier_id,
            goods_nature="RETURN",
            quantity=_num(line.quantity),
            received_date=date.today(),
            reported_customer_id=doc.customer_id,
            created_by_id=_actor_id(doc, user),
            # 好货混回可售 AVAILABLE（保留 source_marker，人工决策不自动拦截，§5.4）；坏货 NG 不可售。
            status="NG" if is_bad else "AVAILABLE",
            source_marker=marker,
        )
        db.add(inv)
        await db.flush()
        logs.append(f"RMA 货回入库 batch={batch_number} status={inv.status} source={marker['rma_source']}/{marker['quality']}")
    return logs
