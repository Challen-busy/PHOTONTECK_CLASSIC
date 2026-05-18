"""初始化甲方演示用端到端 Demo 流程。

在 backend/ 下执行:
    python -m scripts.seed_demo_flow

如需清掉旧 Demo 后重建:
    python -m scripts.seed_demo_flow --reset-demo
"""

import argparse
import asyncio
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import delete, select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import models as m
from core.auth import hash_password
from core.database import get_session_factory
from scripts.seed_phase1 import seed_phase1
from services.workflow import execute_transition


DEMO_CUSTOMER_PO = "7200001510"
DEMO_INQUIRY_NO = "DEMO-INQ-7200001510"
DEMO_QUOTATION_NO = "DEMO-QT-7200001510"
DEMO_SALES_ORDER_NO = "DEMO-SO-7200001510"
DEMO_PURCHASE_NOTICE_NO = "DEMO-PN-7200001510"
DEMO_PURCHASE_ORDER_NO = "2510138"
DEMO_PURCHASE_INVOICE_NO = "PI-2510138-DEMO"
DEMO_RECEIPT_NO = "PR2603-026"
DEMO_INBOUND_LINE_NO = "PR2603-026-01"
DEMO_SHIPMENT_NO = "PD2603-033"
DEMO_SALES_INVOICE_NO = "I-2603-054"
DEMO_SN_LOT = "25KHN5012BG100"
DEMO_MATERIAL_SKU = "HL13E1CP50-G0"


def money(value: str) -> Decimal:
    return Decimal(value)


async def one(db, model, *where):
    result = await db.execute(select(model).where(*where))
    return result.scalar_one_or_none()


async def all_rows(db, model, *where):
    result = await db.execute(select(model).where(*where))
    return result.scalars().all()


async def get_or_create(db, model, defaults: dict | None = None, **filters):
    row = await one(db, model, *[getattr(model, k) == v for k, v in filters.items()])
    created = False
    if row is None:
        row = model(**filters)
        db.add(row)
        created = True
    for k, v in (defaults or {}).items():
        if hasattr(row, k):
            setattr(row, k, v)
    await db.flush()
    return row, created


async def ensure_user(db, username: str, full_name: str, role: str, company_id: int, is_admin: bool = False):
    user = await one(db, m.UserAccount, m.UserAccount.username == username)
    if user:
        user.full_name = user.full_name or full_name
        user.role = user.role or role
        user.company_id = user.company_id or company_id
        return user

    user = m.UserAccount(
        username=username,
        password_hash=hash_password("admin1234" if username == "admin" else "demo1234"),
        full_name=full_name,
        role=role,
        company_id=company_id,
        is_admin=is_admin,
    )
    db.add(user)
    await db.flush()
    return user


async def ensure_demo_master_data(db):
    company, _ = await get_or_create(
        db,
        m.Company,
        code="HK_MAIN",
        defaults={
            "name": "PHOTONTECK (HK) Limited",
            "short_name": "香港主体",
            "currency": "USD",
            "tax_type": "NONE",
            "country": "香港",
        },
    )

    users = {
        "admin": await ensure_user(db, "admin", "系统管理员", "ADMIN", company.id, True),
        "peyton": await ensure_user(db, "peyton", "Peyton", "OPERATIONS", company.id),
        "jerry": await ensure_user(db, "jerry", "Jerry毛总", "BOSS", company.id),
        "cathy": await ensure_user(db, "cathy", "Cathy", "FINANCE", company.id),
        "sa_li": await ensure_user(db, "sa_li", "李助理(SA)", "SALES_ASSISTANT", company.id),
        "pm_zhang": await ensure_user(db, "pm_zhang", "张经理(产品)", "PRODUCT_MANAGER", company.id),
        "pa_chen": await ensure_user(db, "pa_chen", "陈助理(PA)", "PRODUCT_ASSISTANT", company.id),
        "wh_liu": await ensure_user(db, "wh_liu", "刘师傅(物流)", "LOGISTICS", company.id),
    }

    category, _ = await get_or_create(
        db,
        m.MaterialCategory,
        code="OPTCOMM",
        defaults={"name": "光通信器件"},
    )
    supplier, _ = await get_or_create(
        db,
        m.Supplier,
        company_id=company.id,
        code="LUMENTUM_EDGE",
        defaults={
            "name": "LumentumEdge GmbH",
            "short_name": "LUMENTUM",
            "country": "德国",
            "contact_person": "Ruby",
            "contact_phone": "852-26876541",
            "created_by_id": users["admin"].id,
            "notes": "Demo supplier from PO-2510138 Google-Innolight",
        },
    )
    material, _ = await get_or_create(
        db,
        m.Material,
        sku=DEMO_MATERIAL_SKU,
        defaults={
            "name": "200G EML chip / DFB with EA modulator, 1281nm",
            "supplier_id": supplier.id,
            "category_id": category.id,
            "product_line": "OPTCOMM",
            "unit": "PCS",
            "description": "Lumentum HL13E1CP50-G0, sample material for Innolight demo",
            "technical_specs": {"wavelength_nm": "1281", "source": "7200001510 / PO-2510138"},
        },
    )
    customer, _ = await get_or_create(
        db,
        m.Customer,
        company_id=company.id,
        code="INNOLIGHT",
        defaults={
            "name": "Innolight Technology (Suzhou) Ltd / 苏州旭创科技有限公司",
            "short_name": "Innolight / 苏州旭创",
            "country": "中国",
            "city": "苏州",
            "address": "8 Xiasheng Road, Suzhou Industrial Park, Suzhou, Jiangsu 215126, China",
            "contact_person": "杨凯",
            "contact_phone": "13951334033",
            "payment_terms_days": 60,
            "default_currency": "USD",
            "default_shipping_method": "FCA",
            "created_by_id": users["admin"].id,
        },
    )
    warehouse, _ = await get_or_create(
        db,
        m.Warehouse,
        company_id=company.id,
        code="WH-HK",
        defaults={
            "name": "香港主仓",
            "warehouse_type": "MAIN",
            "city": "香港",
            "created_by_id": users["admin"].id,
        },
    )
    location, _ = await get_or_create(
        db,
        m.WarehouseLocation,
        warehouse_id=warehouse.id,
        code="AD05",
        defaults={"zone": "AD", "shelf": "05", "position": "DEMO"},
    )

    await db.commit()
    return {
        "company": company,
        "users": users,
        "supplier": supplier,
        "material": material,
        "customer": customer,
        "warehouse": warehouse,
        "location": location,
    }


async def demo_exists(db):
    inquiry = await one(db, m.SalesInquiry, m.SalesInquiry.inquiry_number == DEMO_INQUIRY_NO)
    sales_order = await one(db, m.SalesOrder, m.SalesOrder.customer_po_number == DEMO_CUSTOMER_PO)
    return inquiry or sales_order


async def delete_if_any(db, model, ids):
    ids = [i for i in ids if i]
    if ids:
        await db.execute(delete(model).where(model.id.in_(ids)))


async def reset_demo_data(db):
    inquiries = await all_rows(db, m.SalesInquiry, m.SalesInquiry.inquiry_number == DEMO_INQUIRY_NO)
    inquiry_ids = [row.id for row in inquiries]

    quotations = await all_rows(
        db,
        m.Quotation,
        (m.Quotation.quotation_number == DEMO_QUOTATION_NO) | (m.Quotation.inquiry_id.in_(inquiry_ids or [-1])),
    )
    quotation_ids = [row.id for row in quotations]

    sales_orders = await all_rows(
        db,
        m.SalesOrder,
        (m.SalesOrder.order_number == DEMO_SALES_ORDER_NO)
        | (m.SalesOrder.customer_po_number == DEMO_CUSTOMER_PO)
        | (m.SalesOrder.inquiry_id.in_(inquiry_ids or [-1]))
        | (m.SalesOrder.quotation_id.in_(quotation_ids or [-1])),
    )
    sales_order_ids = [row.id for row in sales_orders]

    purchase_notices = await all_rows(
        db,
        m.PurchaseNotice,
        (m.PurchaseNotice.notice_number == DEMO_PURCHASE_NOTICE_NO)
        | (m.PurchaseNotice.sales_order_id.in_(sales_order_ids or [-1])),
    )
    purchase_notice_ids = [row.id for row in purchase_notices]

    purchase_orders = await all_rows(
        db,
        m.PurchaseOrder,
        (m.PurchaseOrder.order_number == DEMO_PURCHASE_ORDER_NO)
        | (m.PurchaseOrder.related_sales_order_id.in_(sales_order_ids or [-1]))
        | (m.PurchaseOrder.purchase_notice_id.in_(purchase_notice_ids or [-1])),
    )
    purchase_order_ids = [row.id for row in purchase_orders]

    goods_receipts = await all_rows(
        db,
        m.GoodsReceipt,
        (m.GoodsReceipt.receipt_number == DEMO_RECEIPT_NO)
        | (m.GoodsReceipt.purchase_order_id.in_(purchase_order_ids or [-1])),
    )
    goods_receipt_ids = [row.id for row in goods_receipts]

    shipments = await all_rows(
        db,
        m.ShipmentRequest,
        (m.ShipmentRequest.shipment_number == DEMO_SHIPMENT_NO)
        | (m.ShipmentRequest.sales_order_id.in_(sales_order_ids or [-1])),
    )
    shipment_ids = [row.id for row in shipments]

    purchase_invoices = await all_rows(
        db,
        m.PurchaseInvoice,
        (m.PurchaseInvoice.invoice_number == DEMO_PURCHASE_INVOICE_NO)
        | (m.PurchaseInvoice.purchase_order_id.in_(purchase_order_ids or [-1]))
        | (m.PurchaseInvoice.goods_receipt_id.in_(goods_receipt_ids or [-1])),
    )
    purchase_invoice_ids = [row.id for row in purchase_invoices]

    sales_invoices = await all_rows(
        db,
        m.SalesInvoice,
        (m.SalesInvoice.invoice_number == DEMO_SALES_INVOICE_NO)
        | (m.SalesInvoice.sales_order_id.in_(sales_order_ids or [-1]))
        | (m.SalesInvoice.shipment_id.in_(shipment_ids or [-1])),
    )
    sales_invoice_ids = [row.id for row in sales_invoices]

    accounts_payable = await all_rows(
        db,
        m.AccountsPayable,
        (m.AccountsPayable.invoice_number == DEMO_PURCHASE_INVOICE_NO)
        | (m.AccountsPayable.purchase_order_id.in_(purchase_order_ids or [-1])),
    )
    accounts_receivable = await all_rows(
        db,
        m.AccountsReceivable,
        (m.AccountsReceivable.invoice_number == DEMO_SALES_INVOICE_NO)
        | (m.AccountsReceivable.sales_order_id.in_(sales_order_ids or [-1])),
    )
    inventories = await all_rows(
        db,
        m.Inventory,
        (m.Inventory.inbound_number == DEMO_INBOUND_LINE_NO)
        | (m.Inventory.batch_number == DEMO_INBOUND_LINE_NO)
        | (m.Inventory.serial_lot_number == DEMO_SN_LOT),
    )
    inventory_ids = [row.id for row in inventories]

    sales_returns = await all_rows(
        db,
        m.SalesReturn,
        (m.SalesReturn.sales_order_id.in_(sales_order_ids or [-1]))
        | (m.SalesReturn.shipment_id.in_(shipment_ids or [-1])),
    )
    sales_return_ids = [row.id for row in sales_returns]

    await delete_if_any(db, m.WorkflowLog, [])  # keep helper symmetrical; real log cleanup below
    for doc_type, ids in [
        ("SALES_INQUIRY", inquiry_ids),
        ("QUOTATION", quotation_ids),
        ("SALES_ORDER", sales_order_ids),
        ("PURCHASE_NOTICE", purchase_notice_ids),
        ("PURCHASE_ORDER", purchase_order_ids),
        ("GOODS_RECEIPT", goods_receipt_ids),
        ("SHIPMENT", shipment_ids),
        ("PURCHASE_INVOICE", purchase_invoice_ids),
        ("SALES_INVOICE", sales_invoice_ids),
        ("SALES_RETURN", sales_return_ids),
    ]:
        if ids:
            await db.execute(delete(m.WorkflowLog).where(m.WorkflowLog.doc_type == doc_type, m.WorkflowLog.doc_id.in_(ids)))

    await delete_if_any(db, m.AccountsReceivable, [row.id for row in accounts_receivable])
    await delete_if_any(db, m.AccountsPayable, [row.id for row in accounts_payable])
    await delete_if_any(db, m.SalesInvoiceLine, [row.id for row in await all_rows(db, m.SalesInvoiceLine, m.SalesInvoiceLine.sales_invoice_id.in_(sales_invoice_ids or [-1]))])
    await delete_if_any(db, m.PurchaseInvoiceLine, [row.id for row in await all_rows(db, m.PurchaseInvoiceLine, m.PurchaseInvoiceLine.purchase_invoice_id.in_(purchase_invoice_ids or [-1]))])
    await delete_if_any(db, m.SalesReturnLine, [row.id for row in await all_rows(db, m.SalesReturnLine, m.SalesReturnLine.sales_return_id.in_(sales_return_ids or [-1]))])
    await delete_if_any(db, m.ShipmentLine, [row.id for row in await all_rows(db, m.ShipmentLine, m.ShipmentLine.shipment_id.in_(shipment_ids or [-1]))])
    await delete_if_any(db, m.Inventory, inventory_ids)
    await delete_if_any(db, m.GoodsReceiptLine, [row.id for row in await all_rows(db, m.GoodsReceiptLine, m.GoodsReceiptLine.goods_receipt_id.in_(goods_receipt_ids or [-1]))])
    await delete_if_any(db, m.PurchaseOrderLine, [row.id for row in await all_rows(db, m.PurchaseOrderLine, m.PurchaseOrderLine.purchase_order_id.in_(purchase_order_ids or [-1]))])
    await delete_if_any(db, m.PurchaseNoticeLine, [row.id for row in await all_rows(db, m.PurchaseNoticeLine, m.PurchaseNoticeLine.purchase_notice_id.in_(purchase_notice_ids or [-1]))])
    await delete_if_any(db, m.SalesOrderLine, [row.id for row in await all_rows(db, m.SalesOrderLine, m.SalesOrderLine.sales_order_id.in_(sales_order_ids or [-1]))])
    await delete_if_any(db, m.QuotationLine, [row.id for row in await all_rows(db, m.QuotationLine, m.QuotationLine.quotation_id.in_(quotation_ids or [-1]))])
    await delete_if_any(db, m.SalesInquiryLine, [row.id for row in await all_rows(db, m.SalesInquiryLine, m.SalesInquiryLine.inquiry_id.in_(inquiry_ids or [-1]))])

    await delete_if_any(db, m.SalesReturn, sales_return_ids)
    await delete_if_any(db, m.SalesInvoice, sales_invoice_ids)
    await delete_if_any(db, m.PurchaseInvoice, purchase_invoice_ids)
    await delete_if_any(db, m.ShipmentRequest, shipment_ids)
    await delete_if_any(db, m.GoodsReceipt, goods_receipt_ids)
    await delete_if_any(db, m.PurchaseOrder, purchase_order_ids)
    await delete_if_any(db, m.PurchaseNotice, purchase_notice_ids)
    await delete_if_any(db, m.SalesOrder, sales_order_ids)
    await delete_if_any(db, m.Quotation, quotation_ids)
    await delete_if_any(db, m.SalesInquiry, inquiry_ids)
    await db.commit()


async def run_step(db, user, doc_type, doc_id, to_state, label="", fields=None, subs=None):
    result = await execute_transition(
        db=db,
        doc_type=doc_type,
        doc_id=doc_id,
        user=user,
        to_state=to_state,
        action_label=label,
        field_updates=fields or {},
        sub_updates=subs or [],
        comment="甲方演示样例初始化",
    )
    if not result.get("success"):
        raise RuntimeError(f"{doc_type}#{doc_id} -> {to_state} 失败: {result}")
    return result


async def choose_unique_number(db, model, attr_name: str, desired: str, fallback: str, current_id: int | None = None):
    attr = getattr(model, attr_name)
    existing = await one(db, model, attr == desired)
    if existing and (current_id is None or existing.id != current_id):
        return fallback
    return desired


async def create_demo_flow(db, master):
    admin = master["users"]["admin"]
    customer = master["customer"]
    supplier = master["supplier"]
    material = master["material"]
    warehouse = master["warehouse"]
    users = master["users"]

    # 1. CRM: 客户询价 -> 报价
    create_inquiry = await execute_transition(
        db=db,
        doc_type="SALES_INQUIRY",
        doc_id=None,
        user=admin,
        field_updates={
            "inquiry_number": DEMO_INQUIRY_NO,
            "customer_id": customer.id,
            "sales_assistant_id": users["sa_li"].id,
            "product_manager_id": users["pm_zhang"].id,
            "source": f"客户 PO {DEMO_CUSTOMER_PO} 演示",
            "target_price": "1.00",
            "currency": "USD",
            "required_delivery_date": "2026-04-15",
            "delivery_address": "SITOPARK, 168 Shengpu Road, Suzhou / 胜浦路168号旭创光电产业园西门门卫室",
            "packaging_requirements": "按 Innolight 样例订单要求包装",
            "barcode_requirements": "按客户标签要求",
            "payment_requirement": "Factoring-60 days",
            "notes": "甲方演示样例：从询价到应收应付全链路",
        },
        sub_updates=[
            {
                "table": "sales_inquiry_line",
                "parent_fk": "inquiry_id",
                "fields": {
                    "line_number": 1,
                    "material_id": material.id,
                    "product_description": "DFB with EA modulator, 1281nm, Lumentum HL13E1CP50-G0",
                    "quantity": "50000",
                    "target_unit_price": "1.00",
                    "requested_delivery_date": "2026-04-15",
                    "notes": "Customer PR 2100000544; customer part 283-0353-28",
                },
            }
        ],
        comment="创建甲方演示客户询价",
    )
    if not create_inquiry.get("success"):
        raise RuntimeError(create_inquiry)
    inquiry_id = create_inquiry["doc_id"]

    await run_step(db, admin, "SALES_INQUIRY", inquiry_id, "DRAFT")
    await run_step(db, admin, "SALES_INQUIRY", inquiry_id, "PM_REVIEW")
    await run_step(db, admin, "SALES_INQUIRY", inquiry_id, "AUTHORIZED", fields={"notes": "PM 已授权报价"})
    await run_step(db, admin, "SALES_INQUIRY", inquiry_id, "QUOTATION_CREATED")

    quotation = await one(db, m.Quotation, m.Quotation.inquiry_id == inquiry_id)
    quotation.quotation_number = await choose_unique_number(db, m.Quotation, "quotation_number", DEMO_QUOTATION_NO, f"{DEMO_QUOTATION_NO}-{quotation.id}", quotation.id)
    quotation.payment_terms_days = 60
    quotation.shipping_method = "FCA"
    quotation.valid_until = date(2025, 12, 31)
    quotation.notes = "由演示询价自动生成，补充为 Innolight 样例报价"
    quotation.total_amount = money("50000.00")
    qline = (await all_rows(db, m.QuotationLine, m.QuotationLine.quotation_id == quotation.id))[0]
    qline.unit_price = money("1.0000")
    qline.total_price = money("50000.00")
    qline.tax_rate = money("0")
    qline.delivery_days = 180
    await db.commit()

    await run_step(db, admin, "QUOTATION", quotation.id, "PM_APPROVAL")
    await run_step(db, admin, "QUOTATION", quotation.id, "SENT")
    await run_step(db, admin, "QUOTATION", quotation.id, "CUSTOMER_CONFIRMED")
    await run_step(db, admin, "QUOTATION", quotation.id, "SALES_ORDER_CREATED")

    # 2. ERP: 销售订单 -> 采购通知
    sales_order = await one(db, m.SalesOrder, m.SalesOrder.quotation_id == quotation.id)
    sales_line = (await all_rows(db, m.SalesOrderLine, m.SalesOrderLine.sales_order_id == sales_order.id))[0]
    sales_order_no = await choose_unique_number(db, m.SalesOrder, "order_number", DEMO_SALES_ORDER_NO, f"{DEMO_SALES_ORDER_NO}-{sales_order.id}", sales_order.id)

    await run_step(
        db,
        admin,
        "SALES_ORDER",
        sales_order.id,
        "SALES_MANAGER_REVIEW",
        fields={
            "order_number": sales_order_no,
            "customer_po_number": DEMO_CUSTOMER_PO,
            "customer_po_date": "2025-10-30",
            "customer_vendor_no": "200080",
            "quotation_reference": quotation.quotation_number,
            "currency": "USD",
            "exchange_rate": "1",
            "total_amount": "50000.00",
            "payment_terms_days": 60,
            "payment_terms_text": "Factoring-60 days",
            "shipping_method": "FCA",
            "shipment_terms": "FCA HK INCOTERMS 2020",
            "requires_advance_receipt": False,
            "advance_receipt_amount": "0",
            "delivery_address": "SITOPARK, 168 Shengpu Road, Suzhou / 胜浦路168号旭创光电产业园西门门卫室",
            "bill_to_name": "Innolight Technology (Suzhou) Ltd",
            "bill_to_address": "8 Xiasheng Road, Suzhou Industrial Park, Suzhou, Jiangsu 215126, China",
            "bill_to_contact": "Ava Huang / 黄苏艳",
            "bill_to_phone": "(512)86669288-8515",
            "ship_to_name": "West Gate Security Room, SITOPARK",
            "ship_to_address": "SITOPARK, 168 Shengpu Road, Suzhou / 胜浦路168号旭创光电产业园西门门卫室",
            "ship_to_contact": "杨凯",
            "ship_to_phone": "13951334033",
            "packaging_requirements": "按 Innolight 样例订单要求包装",
            "barcode_requirements": "按客户标签要求",
            "sales_engineer_id": users["sa_li"].id,
            "sales_assistant_id": users["sa_li"].id,
            "sales_assistant_names": "杨馨凝 / 黄琴 / 朱亚丽 / 张凌",
            "product_manager_id": users["pm_zhang"].id,
            "customer_region": "Innolight",
            "notes": "Demo from customer PO 7200001510",
        },
        subs=[
            {
                "table": "sales_order_line",
                "id": sales_line.id,
                "fields": {
                    "customer_line_number": "1",
                    "customer_pr_number": "2100000544",
                    "customer_part_number": "283-0353-28",
                    "part_revision": "",
                    "product_description": "DFB with EA modulator, 1281nm, Lumentum HL13E1CP50-G0",
                    "quantity": "50000",
                    "uom": "PCS",
                    "unit_price": "1.0000",
                    "total_price": "50000.00",
                    "tax_rate": "0",
                    "requested_delivery_date": "2026-04-15",
                },
            }
        ],
    )
    await run_step(db, admin, "SALES_ORDER", sales_order.id, "READY_FOR_PURCHASE", fields={"notes": "无需预收，放行采购"})

    purchase_notice = await one(db, m.PurchaseNotice, m.PurchaseNotice.sales_order_id == sales_order.id)
    purchase_notice.notice_number = await choose_unique_number(db, m.PurchaseNotice, "notice_number", DEMO_PURCHASE_NOTICE_NO, f"{DEMO_PURCHASE_NOTICE_NO}-{purchase_notice.id}", purchase_notice.id)
    await db.commit()
    pn_line = (await all_rows(db, m.PurchaseNoticeLine, m.PurchaseNoticeLine.purchase_notice_id == purchase_notice.id))[0]
    await run_step(
        db,
        admin,
        "PURCHASE_NOTICE",
        purchase_notice.id,
        "PA_ACCEPTED",
        fields={
            "sales_order_id": sales_order.id,
            "requested_by_id": users["sa_li"].id,
            "purchase_assistant_id": users["pa_chen"].id,
            "required_delivery_date": "2026-04-15",
            "notes": "Customer PO 7200001510; target supplier PO 2510138",
        },
        subs=[
            {
                "table": "purchase_notice_line",
                "id": pn_line.id,
                "fields": {
                    "preferred_supplier_id": supplier.id,
                    "required_delivery_date": "2026-04-15",
                    "notes": "推荐供应商 LumentumEdge GmbH",
                },
            }
        ],
    )
    await run_step(db, admin, "PURCHASE_NOTICE", purchase_notice.id, "PURCHASE_ORDER_CREATED")

    # 3. ERP: 采购订单 -> 入库
    purchase_order = await one(db, m.PurchaseOrder, m.PurchaseOrder.purchase_notice_id == purchase_notice.id)
    purchase_order.order_number = await choose_unique_number(db, m.PurchaseOrder, "order_number", DEMO_PURCHASE_ORDER_NO, f"PO-{DEMO_PURCHASE_ORDER_NO}-DEMO", purchase_order.id)
    await db.commit()
    po_line = (await all_rows(db, m.PurchaseOrderLine, m.PurchaseOrderLine.purchase_order_id == purchase_order.id))[0]
    await run_step(
        db,
        admin,
        "PURCHASE_ORDER",
        purchase_order.id,
        "SUPPLY_MANAGER_REVIEW",
        fields={
            "supplier_id": supplier.id,
            "purchase_assistant_id": users["pa_chen"].id,
            "related_sales_order_id": sales_order.id,
            "purchase_notice_id": purchase_notice.id,
            "po_date": "2025-11-03",
            "currency": "USD",
            "total_amount": "50000.00",
            "expected_delivery_date": "2026-01-02",
            "shipment_terms": "FCA shipping point",
            "payment_terms_text": "Net 30 days",
            "ship_to_name": "Photonteck Co.,Ltd",
            "ship_to_address": "Flat B,15/F., Leahander Centre, 28 Wang Wo Tsai Street, Tsuen Wan, N.T., Hong Kong",
            "ship_to_contact": "Ron Lai",
            "ship_to_phone": "852-26876541",
            "bill_to_name": "Photonteck Co.,Ltd",
            "bill_to_address": "Flat B,15/F., Leahander Centre, 28 Wang Wo Tsai Street, Tsuen Wan, N.T., Hong Kong",
            "bill_to_contact": "Ron Lai",
            "bill_to_phone": "852-26876541",
            "end_user": "Google-Innolight",
            "vendor_code": "LITE05",
            "ship_via": "Fedex a/c:111738718",
            "supplier_contact": "Ruby",
            "buyer_name": "Amanda Wang",
            "requires_advance_payment": False,
            "advance_payment_amount": "0",
            "notes": "Supplier PO sample: PO-2510138 Google-Innolight",
        },
        subs=[
            {
                "table": "purchase_order_line",
                "id": po_line.id,
                "fields": {
                    "supplier_part_number": DEMO_MATERIAL_SKU,
                    "product_description": "200G EML chip",
                    "quantity": "50000",
                    "uom": "PCS",
                    "unit_price": "1.0000",
                    "total_price": "50000.00",
                    "delivery_date": "2026-01-02",
                    "sales_order_line_id": sales_line.id,
                },
            }
        ],
    )
    await run_step(db, admin, "PURCHASE_ORDER", purchase_order.id, "ORDERED", fields={"expected_delivery_date": "2026-01-02", "notes": "供应经理审核通过并下单"})
    await run_step(db, admin, "PURCHASE_ORDER", purchase_order.id, "GOODS_RECEIVED", fields={"actual_delivery_date": "2026-03-03", "notes": "仓库已收货"})

    goods_receipt = await one(db, m.GoodsReceipt, m.GoodsReceipt.purchase_order_id == purchase_order.id)
    goods_receipt.receipt_number = await choose_unique_number(db, m.GoodsReceipt, "receipt_number", DEMO_RECEIPT_NO, f"{DEMO_RECEIPT_NO}-{goods_receipt.id}", goods_receipt.id)
    await db.commit()
    gr_line = (await all_rows(db, m.GoodsReceiptLine, m.GoodsReceiptLine.goods_receipt_id == goods_receipt.id))[0]
    await run_step(
        db,
        admin,
        "GOODS_RECEIPT",
        goods_receipt.id,
        "PA_REVIEW",
        fields={
            "purchase_order_id": purchase_order.id,
            "warehouse_id": warehouse.id,
            "received_by_id": users["wh_liu"].id,
            "received_date": "2026-03-03",
            "notes": "Inbound sample from 发货.xlsx",
        },
        subs=[
            {
                "table": "goods_receipt_line",
                "id": gr_line.id,
                "fields": {
                    "expected_quantity": "50000",
                    "actual_quantity": "481",
                    "quality_status": "OK",
                    "batch_number": DEMO_INBOUND_LINE_NO,
                    "inbound_number": DEMO_INBOUND_LINE_NO,
                    "serial_lot_number": DEMO_SN_LOT,
                    "supplier_id": supplier.id,
                    "goods_nature": "GOODS",
                    "uom": "PCS",
                    "tracking_number": "889130751480",
                    "delivery_method": "FEDEX",
                    "source_doc_number": DEMO_PURCHASE_ORDER_NO,
                    "carton_number": "1-8",
                    "origin_country": "JAPAN",
                    "hs_code": "85414100",
                    "location_code": "AD05",
                    "production_date": "2026-01-18",
                },
            }
        ],
    )
    await run_step(db, admin, "GOODS_RECEIPT", goods_receipt.id, "STOCKED_IN", fields={"notes": "PA 审核通过入库"})

    # 4. 财务: 采购发票 -> 应付
    purchase_invoice = await one(db, m.PurchaseInvoice, m.PurchaseInvoice.goods_receipt_id == goods_receipt.id)
    await run_step(
        db,
        admin,
        "PURCHASE_INVOICE",
        purchase_invoice.id,
        "MATCHING",
        fields={
            "invoice_number": DEMO_PURCHASE_INVOICE_NO,
            "supplier_id": supplier.id,
            "purchase_order_id": purchase_order.id,
            "goods_receipt_id": goods_receipt.id,
            "amount": "481.00",
            "currency": "USD",
            "tax_rate": "0",
            "invoice_date": "2026-03-03",
            "notes": "Demo purchase invoice for PO 2510138",
        },
    )
    await run_step(db, admin, "PURCHASE_INVOICE", purchase_invoice.id, "AP_CREATED", fields={"notes": "采购发票勾稽通过并生成应付"})

    purchase_order = await one(db, m.PurchaseOrder, m.PurchaseOrder.id == purchase_order.id)
    if purchase_order.status == "INVOICE_MATCHING":
        await run_step(db, admin, "PURCHASE_ORDER", purchase_order.id, "COMPLETED", fields={"notes": "采购完成"})

    # 5. ERP/WMS: 销售订单 -> 发货出库
    sales_order = await one(db, m.SalesOrder, m.SalesOrder.id == sales_order.id)
    if sales_order.status == "PURCHASE_NOTICE_SENT":
        await run_step(db, admin, "SALES_ORDER", sales_order.id, "READY_TO_SHIP", fields={"notes": "库存满足可发货"})
    await run_step(db, admin, "SALES_ORDER", sales_order.id, "SHIPMENT_REQUESTED", fields={"notes": "发布发货通知"})

    inventory = await one(db, m.Inventory, m.Inventory.serial_lot_number == DEMO_SN_LOT)
    shipment = await one(db, m.ShipmentRequest, m.ShipmentRequest.sales_order_id == sales_order.id)
    shipment.shipment_number = await choose_unique_number(db, m.ShipmentRequest, "shipment_number", DEMO_SHIPMENT_NO, f"{DEMO_SHIPMENT_NO}-{shipment.id}", shipment.id)
    await db.commit()
    await run_step(
        db,
        admin,
        "SHIPMENT",
        shipment.id,
        "FINANCE_APPROVAL",
        fields={
            "sales_order_id": sales_order.id,
            "requested_by_id": users["sa_li"].id,
            "approved_by_id": users["cathy"].id,
            "warehouse_id": warehouse.id,
            "shipping_method": "LOCAL",
            "tracking_number": "N/A",
            "source_purchase_order_number": f"PO#{DEMO_PURCHASE_ORDER_NO}",
            "product_line": "光通信",
            "payment_terms_text": "Factoring 30 days",
            "document_status": "Finished",
            "packaging_requirements": "按客户标签和装箱要求",
            "barcode_requirements": "按客户条码要求",
            "delivery_requirements": "LOCAL DELIVERY",
            "label_status": "PENDING",
            "inspection_status": "PENDING",
            "shipped_date": "2026-03-03",
            "notes": "Shipment sample from 发货.xlsx",
        },
        subs=[
            {
                "table": "shipment_line",
                "parent_fk": "shipment_id",
                "fields": {
                    "sales_order_line_id": sales_line.id,
                    "inventory_id": inventory.id,
                    "quantity": "481",
                    "uom": "PCS",
                    "inbound_number": DEMO_INBOUND_LINE_NO,
                    "serial_lot_number": DEMO_SN_LOT,
                    "supplier_id": supplier.id,
                    "goods_nature": "GOODS",
                    "tracking_number": "N/A",
                    "delivery_method": "LOCAL DELIVERY",
                    "invoice_number": DEMO_SALES_INVOICE_NO,
                    "carton_number": "1-8",
                    "origin_country": "JAPAN",
                    "hs_code": "85414100",
                },
            }
        ],
    )
    await run_step(db, admin, "SHIPMENT", shipment.id, "PACKING_LABELING", fields={"approved_by_id": users["cathy"].id, "notes": "财务放行"})
    await run_step(
        db,
        admin,
        "SHIPMENT",
        shipment.id,
        "PICKING_RECHECK",
        fields={"label_status": "DONE", "inspection_status": "PASS", "tracking_number": "N/A", "notes": "完成制标并拣货复检"},
    )
    await run_step(db, admin, "SHIPMENT", shipment.id, "SALES_OUTBOUND", fields={"shipped_date": "2026-03-03", "tracking_number": "N/A", "notes": "确认出库"})
    await run_step(db, admin, "SHIPMENT", shipment.id, "CUSTOMER_RECEIVED", fields={"notes": "客户已签收"})

    sales_order = await one(db, m.SalesOrder, m.SalesOrder.id == sales_order.id)
    if sales_order.status == "SHIPMENT_REQUESTED":
        await run_step(db, admin, "SALES_ORDER", sales_order.id, "COMPLETED", fields={"notes": "销售订单完成"})

    # 6. 财务: 销售发票 -> 应收
    sales_invoice = await one(db, m.SalesInvoice, m.SalesInvoice.shipment_id == shipment.id)
    await run_step(
        db,
        admin,
        "SALES_INVOICE",
        sales_invoice.id,
        "MATCHING",
        fields={
            "invoice_number": DEMO_SALES_INVOICE_NO,
            "customer_id": customer.id,
            "sales_order_id": sales_order.id,
            "shipment_id": shipment.id,
            "amount": "481.00",
            "currency": "USD",
            "tax_rate": "0",
            "invoice_date": "2026-03-03",
            "notes": "Sales invoice / shipment sample I-2603-054",
        },
    )
    await run_step(db, admin, "SALES_INVOICE", sales_invoice.id, "AR_CREATED", fields={"notes": "销售发票勾稽通过并生成应收"})

    await db.commit()
    return {
        "inquiry_id": inquiry_id,
        "quotation_id": quotation.id,
        "sales_order_id": sales_order.id,
        "purchase_notice_id": purchase_notice.id,
        "purchase_order_id": purchase_order.id,
        "goods_receipt_id": goods_receipt.id,
        "purchase_invoice_id": purchase_invoice.id,
        "shipment_id": shipment.id,
        "sales_invoice_id": sales_invoice.id,
    }


async def main(reset_demo: bool):
    await seed_phase1()

    factory = get_session_factory()
    async with factory() as db:
        master = await ensure_demo_master_data(db)

    async with factory() as db:
        if reset_demo:
            await reset_demo_data(db)
        elif await demo_exists(db):
            print("演示数据已存在，跳过初始化。")
            print(f"可在系统里搜索: {DEMO_CUSTOMER_PO} / {DEMO_PURCHASE_ORDER_NO} / {DEMO_RECEIPT_NO} / {DEMO_SHIPMENT_NO} / {DEMO_SALES_INVOICE_NO}")
            print("如需重建，请执行: python -m scripts.seed_demo_flow --reset-demo")
            return

    async with factory() as db:
        master = await ensure_demo_master_data(db)
        ids = await create_demo_flow(db, master)

    print("甲方演示 Demo 流程已初始化。")
    print(f"客户 PO: {DEMO_CUSTOMER_PO}")
    print(f"客户询价: {DEMO_INQUIRY_NO}")
    print(f"报价单: {DEMO_QUOTATION_NO}")
    print(f"销售订单: {DEMO_SALES_ORDER_NO}")
    print(f"采购通知: {DEMO_PURCHASE_NOTICE_NO}")
    print(f"采购 PO: {DEMO_PURCHASE_ORDER_NO}")
    print(f"入仓: {DEMO_RECEIPT_NO} / {DEMO_INBOUND_LINE_NO} / {DEMO_SN_LOT}")
    print(f"出库: {DEMO_SHIPMENT_NO}")
    print(f"发货/销售发票: {DEMO_SALES_INVOICE_NO}")
    print(f"内部ID: {ids}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset-demo", action="store_true", help="删除旧 Demo 链路后重建")
    args = parser.parse_args()
    asyncio.run(main(reset_demo=args.reset_demo))
