"""align phase 1 fields with example documents

Revision ID: f1b2c3d4
Revises: f0a1b2c3
Create Date: 2026-04-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f1b2c3d4"
down_revision: Union[str, None] = "f0a1b2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def add_text_columns(table_name: str, columns: list[tuple[str, object]]) -> None:
    for name, col_type in columns:
        op.add_column(table_name, sa.Column(name, col_type, server_default="", nullable=True))


def drop_columns(table_name: str, columns: list[str]) -> None:
    for name in columns:
        op.drop_column(table_name, name)


def upgrade() -> None:
    op.add_column("sales_order", sa.Column("customer_po_number", sa.String(length=50), server_default="", nullable=True))
    op.add_column("sales_order", sa.Column("customer_po_date", sa.Date(), nullable=True))
    op.add_column("sales_order", sa.Column("customer_vendor_no", sa.String(length=50), server_default="", nullable=True))
    op.add_column("sales_order", sa.Column("quotation_reference", sa.String(length=100), server_default="", nullable=True))
    op.add_column("sales_order", sa.Column("sales_assistant_names", sa.Text(), server_default="", nullable=True))
    op.add_column("sales_order", sa.Column("product_manager_id", sa.Integer(), nullable=True))
    op.add_column("sales_order", sa.Column("customer_region", sa.String(length=50), server_default="", nullable=True))
    op.add_column("sales_order", sa.Column("exchange_rate", sa.Numeric(12, 6), server_default="1", nullable=True))
    op.add_column("sales_order", sa.Column("payment_terms_text", sa.String(length=100), server_default="", nullable=True))
    op.add_column("sales_order", sa.Column("shipment_terms", sa.String(length=100), server_default="", nullable=True))
    add_text_columns(
        "sales_order",
        [
            ("bill_to_name", sa.String(length=200)),
            ("bill_to_address", sa.Text()),
            ("bill_to_contact", sa.String(length=100)),
            ("bill_to_phone", sa.String(length=50)),
            ("ship_to_name", sa.String(length=200)),
            ("ship_to_address", sa.Text()),
            ("ship_to_contact", sa.String(length=100)),
            ("ship_to_phone", sa.String(length=50)),
        ],
    )
    op.create_index("ix_sales_order_customer_po_number", "sales_order", ["customer_po_number"])
    op.create_foreign_key("fk_sales_order_product_manager", "sales_order", "user_account", ["product_manager_id"], ["id"])

    add_text_columns(
        "sales_order_line",
        [
            ("customer_line_number", sa.String(length=30)),
            ("customer_pr_number", sa.String(length=50)),
            ("customer_part_number", sa.String(length=100)),
            ("part_revision", sa.String(length=30)),
            ("product_description", sa.Text()),
            ("uom", sa.String(length=20)),
        ],
    )
    op.add_column("sales_order_line", sa.Column("tax_rate", sa.Numeric(5, 2), server_default="0", nullable=True))

    op.add_column("purchase_order", sa.Column("po_date", sa.Date(), nullable=True))
    add_text_columns(
        "purchase_order",
        [
            ("shipment_terms", sa.String(length=100)),
            ("payment_terms_text", sa.String(length=100)),
            ("ship_to_name", sa.String(length=200)),
            ("ship_to_address", sa.Text()),
            ("ship_to_contact", sa.String(length=100)),
            ("ship_to_phone", sa.String(length=50)),
            ("bill_to_name", sa.String(length=200)),
            ("bill_to_address", sa.Text()),
            ("bill_to_contact", sa.String(length=100)),
            ("bill_to_phone", sa.String(length=50)),
            ("end_user", sa.String(length=100)),
            ("vendor_code", sa.String(length=50)),
            ("ship_via", sa.String(length=100)),
            ("supplier_contact", sa.String(length=100)),
            ("buyer_name", sa.String(length=100)),
        ],
    )

    add_text_columns(
        "purchase_order_line",
        [
            ("supplier_part_number", sa.String(length=100)),
            ("product_description", sa.Text()),
            ("uom", sa.String(length=20)),
        ],
    )
    op.add_column("purchase_order_line", sa.Column("delivery_date", sa.Date(), nullable=True))

    add_text_columns(
        "inventory",
        [
            ("inbound_number", sa.String(length=50)),
            ("source_doc_number", sa.String(length=50)),
            ("serial_lot_number", sa.String(length=100)),
            ("goods_nature", sa.String(length=30)),
            ("uom", sa.String(length=20)),
            ("tracking_number", sa.String(length=100)),
            ("delivery_method", sa.String(length=50)),
            ("carton_number", sa.String(length=50)),
            ("origin_country", sa.String(length=50)),
            ("hs_code", sa.String(length=50)),
            ("location_code", sa.String(length=50)),
            ("date_code", sa.String(length=50)),
        ],
    )
    op.add_column("inventory", sa.Column("supplier_id", sa.Integer(), nullable=True))
    op.add_column("inventory", sa.Column("production_date", sa.Date(), nullable=True))
    op.create_index("ix_inventory_inbound_number", "inventory", ["inbound_number"])
    op.create_index("ix_inventory_serial_lot_number", "inventory", ["serial_lot_number"])
    op.create_foreign_key("fk_inventory_supplier", "inventory", "supplier", ["supplier_id"], ["id"])

    add_text_columns(
        "goods_receipt_line",
        [
            ("inbound_number", sa.String(length=50)),
            ("serial_lot_number", sa.String(length=100)),
            ("goods_nature", sa.String(length=30)),
            ("uom", sa.String(length=20)),
            ("tracking_number", sa.String(length=100)),
            ("delivery_method", sa.String(length=50)),
            ("source_doc_number", sa.String(length=50)),
            ("carton_number", sa.String(length=50)),
            ("origin_country", sa.String(length=50)),
            ("hs_code", sa.String(length=50)),
            ("location_code", sa.String(length=50)),
            ("date_code", sa.String(length=50)),
        ],
    )
    op.add_column("goods_receipt_line", sa.Column("supplier_id", sa.Integer(), nullable=True))
    op.add_column("goods_receipt_line", sa.Column("production_date", sa.Date(), nullable=True))
    op.create_foreign_key("fk_goods_receipt_line_supplier", "goods_receipt_line", "supplier", ["supplier_id"], ["id"])

    add_text_columns(
        "shipment_request",
        [
            ("source_purchase_order_number", sa.String(length=50)),
            ("product_line", sa.String(length=50)),
            ("payment_terms_text", sa.String(length=100)),
            ("document_status", sa.String(length=50)),
        ],
    )

    add_text_columns(
        "shipment_line",
        [
            ("uom", sa.String(length=20)),
            ("inbound_number", sa.String(length=50)),
            ("serial_lot_number", sa.String(length=100)),
            ("goods_nature", sa.String(length=30)),
            ("tracking_number", sa.String(length=100)),
            ("delivery_method", sa.String(length=50)),
            ("invoice_number", sa.String(length=50)),
            ("carton_number", sa.String(length=50)),
            ("origin_country", sa.String(length=50)),
            ("hs_code", sa.String(length=50)),
        ],
    )
    op.add_column("shipment_line", sa.Column("supplier_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_shipment_line_supplier", "shipment_line", "supplier", ["supplier_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_shipment_line_supplier", "shipment_line", type_="foreignkey")
    op.drop_column("shipment_line", "supplier_id")
    drop_columns(
        "shipment_line",
        [
            "hs_code", "origin_country", "carton_number", "invoice_number", "delivery_method",
            "tracking_number", "goods_nature", "serial_lot_number", "inbound_number", "uom",
        ],
    )

    drop_columns(
        "shipment_request",
        ["document_status", "payment_terms_text", "product_line", "source_purchase_order_number"],
    )

    op.drop_constraint("fk_goods_receipt_line_supplier", "goods_receipt_line", type_="foreignkey")
    op.drop_column("goods_receipt_line", "production_date")
    op.drop_column("goods_receipt_line", "supplier_id")
    drop_columns(
        "goods_receipt_line",
        [
            "date_code", "location_code", "hs_code", "origin_country", "carton_number",
            "source_doc_number", "delivery_method", "tracking_number", "uom", "goods_nature",
            "serial_lot_number", "inbound_number",
        ],
    )

    op.drop_constraint("fk_inventory_supplier", "inventory", type_="foreignkey")
    op.drop_index("ix_inventory_serial_lot_number", table_name="inventory")
    op.drop_index("ix_inventory_inbound_number", table_name="inventory")
    op.drop_column("inventory", "production_date")
    op.drop_column("inventory", "supplier_id")
    drop_columns(
        "inventory",
        [
            "date_code", "location_code", "hs_code", "origin_country", "carton_number",
            "delivery_method", "tracking_number", "uom", "goods_nature", "serial_lot_number",
            "source_doc_number", "inbound_number",
        ],
    )

    op.drop_column("purchase_order_line", "delivery_date")
    drop_columns("purchase_order_line", ["uom", "product_description", "supplier_part_number"])

    drop_columns(
        "purchase_order",
        [
            "buyer_name", "supplier_contact", "ship_via", "vendor_code", "end_user",
            "bill_to_phone", "bill_to_contact", "bill_to_address", "bill_to_name",
            "ship_to_phone", "ship_to_contact", "ship_to_address", "ship_to_name",
            "payment_terms_text", "shipment_terms",
        ],
    )
    op.drop_column("purchase_order", "po_date")

    op.drop_column("sales_order_line", "tax_rate")
    drop_columns(
        "sales_order_line",
        [
            "uom", "product_description", "part_revision", "customer_part_number",
            "customer_pr_number", "customer_line_number",
        ],
    )

    op.drop_constraint("fk_sales_order_product_manager", "sales_order", type_="foreignkey")
    op.drop_index("ix_sales_order_customer_po_number", table_name="sales_order")
    drop_columns(
        "sales_order",
        [
            "ship_to_phone", "ship_to_contact", "ship_to_address", "ship_to_name",
            "bill_to_phone", "bill_to_contact", "bill_to_address", "bill_to_name",
            "shipment_terms", "payment_terms_text", "exchange_rate", "customer_region",
            "product_manager_id", "sales_assistant_names", "quotation_reference",
            "customer_vendor_no", "customer_po_date", "customer_po_number",
        ],
    )
