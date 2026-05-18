"""wms phase1 foundation tables

Revision ID: 0a1b2c3d
Revises: f3d4e5f6
Create Date: 2026-04-30
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0a1b2c3d"
down_revision: Union[str, None] = "f3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "inventory_reservation",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reservation_number", sa.String(length=40), nullable=False),
        sa.Column("inventory_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("sales_order_id", sa.Integer(), nullable=True),
        sa.Column("shipment_id", sa.Integer(), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("reserved_by_id", sa.Integer(), nullable=True),
        sa.Column("reserved_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("released_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(length=15), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["company.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["user_account.id"]),
        sa.ForeignKeyConstraint(["updated_by_id"], ["user_account.id"]),
        sa.ForeignKeyConstraint(["inventory_id"], ["inventory.id"]),
        sa.ForeignKeyConstraint(["customer_id"], ["customer.id"]),
        sa.ForeignKeyConstraint(["sales_order_id"], ["sales_order.id"]),
        sa.ForeignKeyConstraint(["shipment_id"], ["shipment_request.id"]),
        sa.ForeignKeyConstraint(["reserved_by_id"], ["user_account.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "reservation_number"),
    )
    op.create_index("ix_inventory_reservation_reservation_number", "inventory_reservation", ["reservation_number"])
    op.create_index("ix_inventory_reservation_company_id", "inventory_reservation", ["company_id"])
    op.create_index("ix_inventory_reservation_active", "inventory_reservation", ["inventory_id", "status"])

    op.create_table(
        "supplier_sn_rule",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("supplier_id", sa.Integer(), nullable=False),
        sa.Column("material_id", sa.Integer(), nullable=True),
        sa.Column("rule_name", sa.String(length=100), nullable=True),
        sa.Column("exact_length", sa.SmallInteger(), nullable=True),
        sa.Column("min_length", sa.SmallInteger(), nullable=True),
        sa.Column("max_length", sa.SmallInteger(), nullable=True),
        sa.Column("pattern", sa.String(length=200), nullable=True),
        sa.Column("allow_duplicate", sa.Boolean(), nullable=True),
        sa.Column("unique_scope", sa.String(length=30), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["company.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["user_account.id"]),
        sa.ForeignKeyConstraint(["updated_by_id"], ["user_account.id"]),
        sa.ForeignKeyConstraint(["supplier_id"], ["supplier.id"]),
        sa.ForeignKeyConstraint(["material_id"], ["material.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_supplier_sn_rule_company_id", "supplier_sn_rule", ["company_id"])
    op.create_index("ix_supplier_sn_rule_supplier_material", "supplier_sn_rule", ["supplier_id", "material_id"])

    op.create_table(
        "wms_attachment",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("doc_type", sa.String(length=30), nullable=True),
        sa.Column("doc_id", sa.BigInteger(), nullable=True),
        sa.Column("goods_receipt_id", sa.Integer(), nullable=True),
        sa.Column("goods_receipt_line_id", sa.Integer(), nullable=True),
        sa.Column("inventory_id", sa.Integer(), nullable=True),
        sa.Column("attachment_type", sa.String(length=30), nullable=True),
        sa.Column("file_name", sa.String(length=200), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("uploaded_by_id", sa.Integer(), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["company.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["user_account.id"]),
        sa.ForeignKeyConstraint(["updated_by_id"], ["user_account.id"]),
        sa.ForeignKeyConstraint(["goods_receipt_id"], ["goods_receipt.id"]),
        sa.ForeignKeyConstraint(["goods_receipt_line_id"], ["goods_receipt_line.id"]),
        sa.ForeignKeyConstraint(["inventory_id"], ["inventory.id"]),
        sa.ForeignKeyConstraint(["uploaded_by_id"], ["user_account.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_wms_attachment_company_id", "wms_attachment", ["company_id"])
    op.create_index("ix_wms_attachment_doc_type", "wms_attachment", ["doc_type"])
    op.create_index("ix_wms_attachment_doc_id", "wms_attachment", ["doc_id"])


def downgrade() -> None:
    op.drop_index("ix_wms_attachment_doc_id", table_name="wms_attachment")
    op.drop_index("ix_wms_attachment_doc_type", table_name="wms_attachment")
    op.drop_index("ix_wms_attachment_company_id", table_name="wms_attachment")
    op.drop_table("wms_attachment")

    op.drop_index("ix_supplier_sn_rule_supplier_material", table_name="supplier_sn_rule")
    op.drop_index("ix_supplier_sn_rule_company_id", table_name="supplier_sn_rule")
    op.drop_table("supplier_sn_rule")

    op.drop_index("ix_inventory_reservation_active", table_name="inventory_reservation")
    op.drop_index("ix_inventory_reservation_company_id", table_name="inventory_reservation")
    op.drop_index("ix_inventory_reservation_reservation_number", table_name="inventory_reservation")
    op.drop_table("inventory_reservation")
