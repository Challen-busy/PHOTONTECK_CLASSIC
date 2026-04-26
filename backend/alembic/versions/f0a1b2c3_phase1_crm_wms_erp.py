"""phase 1 CRM/WMS/ERP bridge documents

Revision ID: f0a1b2c3
Revises: e6f7a8b9
Create Date: 2026-04-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f0a1b2c3"
down_revision: Union[str, None] = "e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def audit_columns() -> list[sa.Column]:
    return [
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("company.id"), nullable=False, index=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    ]


def upgrade() -> None:
    op.create_table(
        "sales_inquiry",
        sa.Column("id", sa.Integer(), primary_key=True),
        *audit_columns(),
        sa.Column("inquiry_number", sa.String(length=30), nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customer.id"), nullable=True),
        sa.Column("sales_assistant_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("product_manager_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("source", sa.String(length=30), server_default=""),
        sa.Column("target_price", sa.Numeric(16, 2), nullable=True),
        sa.Column("currency", sa.String(length=3), server_default="USD"),
        sa.Column("required_delivery_date", sa.Date(), nullable=True),
        sa.Column("delivery_address", sa.Text(), server_default=""),
        sa.Column("packaging_requirements", sa.Text(), server_default=""),
        sa.Column("barcode_requirements", sa.Text(), server_default=""),
        sa.Column("payment_requirement", sa.String(length=100), server_default=""),
        sa.Column("status", sa.String(length=30), server_default="DRAFT"),
        sa.Column("notes", sa.Text(), server_default=""),
        sa.UniqueConstraint("company_id", "inquiry_number"),
    )
    op.create_index("ix_sales_inquiry_inquiry_number", "sales_inquiry", ["inquiry_number"])

    op.create_table(
        "sales_inquiry_line",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("inquiry_id", sa.Integer(), sa.ForeignKey("sales_inquiry.id"), nullable=False),
        sa.Column("line_number", sa.SmallInteger(), nullable=False),
        sa.Column("material_id", sa.Integer(), sa.ForeignKey("material.id"), nullable=True),
        sa.Column("product_description", sa.Text(), server_default=""),
        sa.Column("quantity", sa.Numeric(12, 2), nullable=False),
        sa.Column("target_unit_price", sa.Numeric(12, 4), nullable=True),
        sa.Column("requested_delivery_date", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), server_default=""),
        sa.UniqueConstraint("inquiry_id", "line_number"),
    )

    op.create_table(
        "quotation",
        sa.Column("id", sa.Integer(), primary_key=True),
        *audit_columns(),
        sa.Column("quotation_number", sa.String(length=30), nullable=False),
        sa.Column("inquiry_id", sa.Integer(), sa.ForeignKey("sales_inquiry.id"), nullable=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customer.id"), nullable=True),
        sa.Column("sales_assistant_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("product_manager_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("currency", sa.String(length=3), server_default="USD"),
        sa.Column("total_amount", sa.Numeric(16, 2), server_default="0"),
        sa.Column("tax_rate", sa.Numeric(5, 2), server_default="0"),
        sa.Column("payment_terms_days", sa.Integer(), server_default="30"),
        sa.Column("shipping_method", sa.String(length=10), server_default="FOB"),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column("delivery_address", sa.Text(), server_default=""),
        sa.Column("packaging_requirements", sa.Text(), server_default=""),
        sa.Column("barcode_requirements", sa.Text(), server_default=""),
        sa.Column("status", sa.String(length=30), server_default="DRAFT"),
        sa.Column("notes", sa.Text(), server_default=""),
        sa.UniqueConstraint("company_id", "quotation_number"),
    )
    op.create_index("ix_quotation_quotation_number", "quotation", ["quotation_number"])

    op.create_table(
        "quotation_line",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("quotation_id", sa.Integer(), sa.ForeignKey("quotation.id"), nullable=False),
        sa.Column("line_number", sa.SmallInteger(), nullable=False),
        sa.Column("material_id", sa.Integer(), sa.ForeignKey("material.id"), nullable=True),
        sa.Column("product_description", sa.Text(), server_default=""),
        sa.Column("quantity", sa.Numeric(12, 2), nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 4), nullable=False),
        sa.Column("total_price", sa.Numeric(16, 2), nullable=False),
        sa.Column("tax_rate", sa.Numeric(5, 2), server_default="0"),
        sa.Column("delivery_days", sa.Integer(), nullable=True),
        sa.Column("packaging_requirements", sa.Text(), server_default=""),
        sa.Column("barcode_requirements", sa.Text(), server_default=""),
        sa.UniqueConstraint("quotation_id", "line_number"),
    )

    op.add_column("sales_order", sa.Column("inquiry_id", sa.Integer(), nullable=True))
    op.add_column("sales_order", sa.Column("quotation_id", sa.Integer(), nullable=True))
    op.add_column("sales_order", sa.Column("requires_advance_receipt", sa.Boolean(), server_default=sa.false(), nullable=True))
    op.add_column("sales_order", sa.Column("advance_receipt_amount", sa.Numeric(16, 2), server_default="0", nullable=True))
    op.add_column("sales_order", sa.Column("delivery_address", sa.Text(), server_default="", nullable=True))
    op.add_column("sales_order", sa.Column("packaging_requirements", sa.Text(), server_default="", nullable=True))
    op.add_column("sales_order", sa.Column("barcode_requirements", sa.Text(), server_default="", nullable=True))
    op.create_foreign_key("fk_sales_order_inquiry", "sales_order", "sales_inquiry", ["inquiry_id"], ["id"])
    op.create_foreign_key("fk_sales_order_quotation", "sales_order", "quotation", ["quotation_id"], ["id"])

    op.create_table(
        "purchase_notice",
        sa.Column("id", sa.Integer(), primary_key=True),
        *audit_columns(),
        sa.Column("notice_number", sa.String(length=30), nullable=False),
        sa.Column("sales_order_id", sa.Integer(), sa.ForeignKey("sales_order.id"), nullable=False),
        sa.Column("requested_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("purchase_assistant_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("required_delivery_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=30), server_default="DRAFT"),
        sa.Column("notes", sa.Text(), server_default=""),
        sa.UniqueConstraint("company_id", "notice_number"),
    )
    op.create_index("ix_purchase_notice_notice_number", "purchase_notice", ["notice_number"])

    op.create_table(
        "purchase_notice_line",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("purchase_notice_id", sa.Integer(), sa.ForeignKey("purchase_notice.id"), nullable=False),
        sa.Column("line_number", sa.SmallInteger(), nullable=False),
        sa.Column("sales_order_line_id", sa.Integer(), sa.ForeignKey("sales_order_line.id"), nullable=True),
        sa.Column("material_id", sa.Integer(), sa.ForeignKey("material.id"), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 2), nullable=False),
        sa.Column("preferred_supplier_id", sa.Integer(), sa.ForeignKey("supplier.id"), nullable=True),
        sa.Column("required_delivery_date", sa.Date(), nullable=True),
        sa.Column("packaging_requirements", sa.Text(), server_default=""),
        sa.Column("barcode_requirements", sa.Text(), server_default=""),
        sa.Column("notes", sa.Text(), server_default=""),
        sa.UniqueConstraint("purchase_notice_id", "line_number"),
    )

    op.add_column("purchase_order", sa.Column("purchase_notice_id", sa.Integer(), nullable=True))
    op.add_column("purchase_order", sa.Column("requires_advance_payment", sa.Boolean(), server_default=sa.false(), nullable=True))
    op.add_column("purchase_order", sa.Column("advance_payment_amount", sa.Numeric(16, 2), server_default="0", nullable=True))
    op.create_foreign_key("fk_purchase_order_notice", "purchase_order", "purchase_notice", ["purchase_notice_id"], ["id"])

    op.add_column("shipment_request", sa.Column("packaging_requirements", sa.Text(), server_default="", nullable=True))
    op.add_column("shipment_request", sa.Column("barcode_requirements", sa.Text(), server_default="", nullable=True))
    op.add_column("shipment_request", sa.Column("delivery_requirements", sa.Text(), server_default="", nullable=True))
    op.add_column("shipment_request", sa.Column("label_status", sa.String(length=20), server_default="PENDING", nullable=True))
    op.add_column("shipment_request", sa.Column("inspection_status", sa.String(length=20), server_default="PENDING", nullable=True))

    op.create_table(
        "sales_return",
        sa.Column("id", sa.Integer(), primary_key=True),
        *audit_columns(),
        sa.Column("return_number", sa.String(length=30), nullable=False),
        sa.Column("sales_order_id", sa.Integer(), sa.ForeignKey("sales_order.id"), nullable=False),
        sa.Column("shipment_id", sa.Integer(), sa.ForeignKey("shipment_request.id"), nullable=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customer.id"), nullable=True),
        sa.Column("warehouse_id", sa.Integer(), sa.ForeignKey("warehouse.id"), nullable=True),
        sa.Column("return_reason", sa.Text(), server_default=""),
        sa.Column("logistics_tracking_number", sa.String(length=100), server_default=""),
        sa.Column("status", sa.String(length=30), server_default="DRAFT"),
        sa.Column("notes", sa.Text(), server_default=""),
        sa.UniqueConstraint("company_id", "return_number"),
    )
    op.create_index("ix_sales_return_return_number", "sales_return", ["return_number"])

    op.create_table(
        "sales_return_line",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sales_return_id", sa.Integer(), sa.ForeignKey("sales_return.id"), nullable=False),
        sa.Column("line_number", sa.SmallInteger(), nullable=False),
        sa.Column("sales_order_line_id", sa.Integer(), sa.ForeignKey("sales_order_line.id"), nullable=True),
        sa.Column("shipment_line_id", sa.Integer(), sa.ForeignKey("shipment_line.id"), nullable=True),
        sa.Column("material_id", sa.Integer(), sa.ForeignKey("material.id"), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 2), nullable=False),
        sa.Column("quality_status", sa.String(length=10), server_default="PENDING"),
        sa.Column("return_action", sa.String(length=20), server_default="RESTOCK"),
        sa.Column("notes", sa.Text(), server_default=""),
        sa.UniqueConstraint("sales_return_id", "line_number"),
    )

    op.create_table(
        "advance_receipt",
        sa.Column("id", sa.Integer(), primary_key=True),
        *audit_columns(),
        sa.Column("receipt_number", sa.String(length=50), nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customer.id"), nullable=False),
        sa.Column("sales_order_id", sa.Integer(), sa.ForeignKey("sales_order.id"), nullable=False),
        sa.Column("bank_account", sa.String(length=50), server_default=""),
        sa.Column("payer_name", sa.String(length=100), server_default=""),
        sa.Column("amount", sa.Numeric(16, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="CNY"),
        sa.Column("receipt_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=30), server_default="DRAFT"),
        sa.Column("notes", sa.Text(), server_default=""),
        sa.UniqueConstraint("company_id", "receipt_number"),
    )
    op.create_index("ix_advance_receipt_receipt_number", "advance_receipt", ["receipt_number"])

    op.create_table(
        "advance_payment",
        sa.Column("id", sa.Integer(), primary_key=True),
        *audit_columns(),
        sa.Column("payment_number", sa.String(length=50), nullable=False),
        sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("supplier.id"), nullable=False),
        sa.Column("purchase_order_id", sa.Integer(), sa.ForeignKey("purchase_order.id"), nullable=False),
        sa.Column("requested_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("approved_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("bank_account", sa.String(length=50), server_default=""),
        sa.Column("payee_name", sa.String(length=100), server_default=""),
        sa.Column("amount", sa.Numeric(16, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="CNY"),
        sa.Column("payment_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=30), server_default="DRAFT"),
        sa.Column("notes", sa.Text(), server_default=""),
        sa.UniqueConstraint("company_id", "payment_number"),
    )
    op.create_index("ix_advance_payment_payment_number", "advance_payment", ["payment_number"])

    op.create_table(
        "purchase_invoice",
        sa.Column("id", sa.Integer(), primary_key=True),
        *audit_columns(),
        sa.Column("invoice_number", sa.String(length=50), nullable=False),
        sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("supplier.id"), nullable=False),
        sa.Column("purchase_order_id", sa.Integer(), sa.ForeignKey("purchase_order.id"), nullable=True),
        sa.Column("goods_receipt_id", sa.Integer(), sa.ForeignKey("goods_receipt.id"), nullable=True),
        sa.Column("amount", sa.Numeric(16, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="CNY"),
        sa.Column("tax_rate", sa.Numeric(5, 2), server_default="0"),
        sa.Column("invoice_date", sa.Date(), nullable=True),
        sa.Column("matched_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(length=30), server_default="DRAFT"),
        sa.Column("notes", sa.Text(), server_default=""),
        sa.UniqueConstraint("company_id", "invoice_number"),
    )
    op.create_index("ix_purchase_invoice_invoice_number", "purchase_invoice", ["invoice_number"])

    op.create_table(
        "purchase_invoice_line",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("purchase_invoice_id", sa.Integer(), sa.ForeignKey("purchase_invoice.id"), nullable=False),
        sa.Column("line_number", sa.SmallInteger(), nullable=False),
        sa.Column("purchase_order_line_id", sa.Integer(), sa.ForeignKey("purchase_order_line.id"), nullable=True),
        sa.Column("goods_receipt_line_id", sa.Integer(), sa.ForeignKey("goods_receipt_line.id"), nullable=True),
        sa.Column("material_id", sa.Integer(), sa.ForeignKey("material.id"), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 2), nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 4), nullable=False),
        sa.Column("total_price", sa.Numeric(16, 2), nullable=False),
        sa.Column("tax_rate", sa.Numeric(5, 2), server_default="0"),
        sa.UniqueConstraint("purchase_invoice_id", "line_number"),
    )

    op.create_table(
        "sales_invoice",
        sa.Column("id", sa.Integer(), primary_key=True),
        *audit_columns(),
        sa.Column("invoice_number", sa.String(length=50), nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customer.id"), nullable=False),
        sa.Column("sales_order_id", sa.Integer(), sa.ForeignKey("sales_order.id"), nullable=True),
        sa.Column("shipment_id", sa.Integer(), sa.ForeignKey("shipment_request.id"), nullable=True),
        sa.Column("amount", sa.Numeric(16, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="CNY"),
        sa.Column("tax_rate", sa.Numeric(5, 2), server_default="0"),
        sa.Column("invoice_date", sa.Date(), nullable=True),
        sa.Column("matched_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(length=30), server_default="DRAFT"),
        sa.Column("notes", sa.Text(), server_default=""),
        sa.UniqueConstraint("company_id", "invoice_number"),
    )
    op.create_index("ix_sales_invoice_invoice_number", "sales_invoice", ["invoice_number"])

    op.create_table(
        "sales_invoice_line",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sales_invoice_id", sa.Integer(), sa.ForeignKey("sales_invoice.id"), nullable=False),
        sa.Column("line_number", sa.SmallInteger(), nullable=False),
        sa.Column("sales_order_line_id", sa.Integer(), sa.ForeignKey("sales_order_line.id"), nullable=True),
        sa.Column("shipment_line_id", sa.Integer(), sa.ForeignKey("shipment_line.id"), nullable=True),
        sa.Column("material_id", sa.Integer(), sa.ForeignKey("material.id"), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 2), nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 4), nullable=False),
        sa.Column("total_price", sa.Numeric(16, 2), nullable=False),
        sa.Column("tax_rate", sa.Numeric(5, 2), server_default="0"),
        sa.Column("cost_amount", sa.Numeric(16, 2), server_default="0"),
        sa.UniqueConstraint("sales_invoice_id", "line_number"),
    )


def downgrade() -> None:
    op.drop_table("sales_invoice_line")
    op.drop_index("ix_sales_invoice_invoice_number", table_name="sales_invoice")
    op.drop_table("sales_invoice")
    op.drop_table("purchase_invoice_line")
    op.drop_index("ix_purchase_invoice_invoice_number", table_name="purchase_invoice")
    op.drop_table("purchase_invoice")
    op.drop_index("ix_advance_payment_payment_number", table_name="advance_payment")
    op.drop_table("advance_payment")
    op.drop_index("ix_advance_receipt_receipt_number", table_name="advance_receipt")
    op.drop_table("advance_receipt")
    op.drop_table("sales_return_line")
    op.drop_index("ix_sales_return_return_number", table_name="sales_return")
    op.drop_table("sales_return")

    op.drop_column("shipment_request", "inspection_status")
    op.drop_column("shipment_request", "label_status")
    op.drop_column("shipment_request", "delivery_requirements")
    op.drop_column("shipment_request", "barcode_requirements")
    op.drop_column("shipment_request", "packaging_requirements")

    op.drop_constraint("fk_purchase_order_notice", "purchase_order", type_="foreignkey")
    op.drop_column("purchase_order", "advance_payment_amount")
    op.drop_column("purchase_order", "requires_advance_payment")
    op.drop_column("purchase_order", "purchase_notice_id")
    op.drop_table("purchase_notice_line")
    op.drop_index("ix_purchase_notice_notice_number", table_name="purchase_notice")
    op.drop_table("purchase_notice")

    op.drop_constraint("fk_sales_order_quotation", "sales_order", type_="foreignkey")
    op.drop_constraint("fk_sales_order_inquiry", "sales_order", type_="foreignkey")
    op.drop_column("sales_order", "barcode_requirements")
    op.drop_column("sales_order", "packaging_requirements")
    op.drop_column("sales_order", "delivery_address")
    op.drop_column("sales_order", "advance_receipt_amount")
    op.drop_column("sales_order", "requires_advance_receipt")
    op.drop_column("sales_order", "quotation_id")
    op.drop_column("sales_order", "inquiry_id")

    op.drop_table("quotation_line")
    op.drop_index("ix_quotation_quotation_number", table_name="quotation")
    op.drop_table("quotation")
    op.drop_table("sales_inquiry_line")
    op.drop_index("ix_sales_inquiry_inquiry_number", table_name="sales_inquiry")
    op.drop_table("sales_inquiry")
