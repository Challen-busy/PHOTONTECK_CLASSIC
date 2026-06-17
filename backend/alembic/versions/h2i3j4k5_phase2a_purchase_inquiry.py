"""phase2a: sales_inquiry extension + supplier_inquiry (对原厂询价)

Revision ID: h2i3j4k5
Revises: g1h2i3j4
Create Date: 2026-06-17

段2a 采购主链（询价端）：

- 04a-1 内部询价扩列：sales_inquiry += home_page / application / project_phase /
  demand_forecast / competitor / competitor_price（销售提供 end-customer 决策上下文）。
- 04a-2 对原厂询价登记：新表 supplier_inquiry / supplier_inquiry_line
  （SUPPLIER_INQUIRY doc_type；轻量状态机 INQUIRING→QUOTED→ADOPTED→CLOSED）。
  子表 unit_price/commission = 采购进价，对销售端 SALES+SA 隐藏（Q18 字段防火墙，
  落在 services/tools.py BUY_TABLES + BUY_PRICE_FIELDS，非 schema 层）。

引擎五条不破坏：只加列 / 加新实体表，不动唯一写入路径（execute_transition / @register_command）。
新 doc_type 走 __doc_types__ + WorkflowDefinition states JSONB + numbering_effect 取业务号。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "h2i3j4k5"
down_revision: Union[str, Sequence[str], None] = "g1h2i3j4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ========== 04a-1 内部询价扩 6 列 ==========
    op.add_column("sales_inquiry", sa.Column("home_page", sa.String(length=200), nullable=True, server_default=""))
    op.add_column("sales_inquiry", sa.Column("application", sa.String(length=200), nullable=True, server_default=""))
    op.add_column("sales_inquiry", sa.Column("project_phase", sa.String(length=20), nullable=True, server_default=""))
    op.add_column("sales_inquiry", sa.Column("demand_forecast", sa.String(length=200), nullable=True, server_default=""))
    op.add_column("sales_inquiry", sa.Column("competitor", sa.String(length=200), nullable=True, server_default=""))
    op.add_column("sales_inquiry", sa.Column("competitor_price", sa.Numeric(16, 2), nullable=True))

    # ========== 04a-2 对原厂询价（SUPPLIER_INQUIRY）==========
    op.create_table(
        "supplier_inquiry",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("inquiry_number", sa.String(length=30), nullable=False),
        sa.Column("supplier_id", sa.Integer(), nullable=True),
        sa.Column("sales_inquiry_id", sa.Integer(), nullable=True),
        sa.Column("product_manager_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=30), server_default="INQUIRING"),
        sa.Column("notes", sa.Text(), server_default=""),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["supplier_id"], ["supplier.id"]),
        sa.ForeignKeyConstraint(["sales_inquiry_id"], ["sales_inquiry.id"]),
        sa.ForeignKeyConstraint(["product_manager_id"], ["user_account.id"]),
        sa.ForeignKeyConstraint(["company_id"], ["company.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["user_account.id"]),
        sa.ForeignKeyConstraint(["updated_by_id"], ["user_account.id"]),
        sa.UniqueConstraint("company_id", "inquiry_number"),
    )
    op.create_index("ix_supplier_inquiry_inquiry_number", "supplier_inquiry", ["inquiry_number"])
    op.create_index("ix_supplier_inquiry_company_id", "supplier_inquiry", ["company_id"])

    op.create_table(
        "supplier_inquiry_line",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("supplier_inquiry_id", sa.Integer(), nullable=False),
        sa.Column("line_number", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("material_id", sa.Integer(), nullable=True),
        sa.Column("description", sa.Text(), server_default=""),
        sa.Column("unit_price", sa.Numeric(12, 4), nullable=True),
        sa.Column("currency", sa.String(length=3), server_default="USD"),
        sa.Column("quantity", sa.Numeric(12, 2), nullable=True),
        sa.Column("uom", sa.String(length=20), server_default="pcs"),
        sa.Column("lead_time", sa.String(length=50), server_default=""),
        sa.Column("shipment_terms", sa.String(length=100), server_default=""),
        sa.Column("payment_terms", sa.String(length=100), server_default=""),
        sa.Column("inquiry_date", sa.Date(), nullable=True),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("sales", sa.String(length=100), server_default=""),
        sa.Column("remarks", sa.Text(), server_default=""),
        sa.Column("mode", sa.String(length=30), server_default="Resell"),
        sa.Column("commission", sa.String(length=50), server_default=""),
        sa.Column("supplier_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["supplier_inquiry_id"], ["supplier_inquiry.id"]),
        sa.ForeignKeyConstraint(["material_id"], ["material.id"]),
        sa.ForeignKeyConstraint(["customer_id"], ["customer.id"]),
        sa.ForeignKeyConstraint(["supplier_id"], ["supplier.id"]),
        sa.UniqueConstraint("supplier_inquiry_id", "line_number"),
    )
    op.create_index("ix_supplier_inquiry_line_supplier_inquiry_id", "supplier_inquiry_line", ["supplier_inquiry_id"])


def downgrade() -> None:
    op.drop_index("ix_supplier_inquiry_line_supplier_inquiry_id", table_name="supplier_inquiry_line")
    op.drop_table("supplier_inquiry_line")
    op.drop_index("ix_supplier_inquiry_company_id", table_name="supplier_inquiry")
    op.drop_index("ix_supplier_inquiry_inquiry_number", table_name="supplier_inquiry")
    op.drop_table("supplier_inquiry")

    op.drop_column("sales_inquiry", "competitor_price")
    op.drop_column("sales_inquiry", "competitor")
    op.drop_column("sales_inquiry", "demand_forecast")
    op.drop_column("sales_inquiry", "project_phase")
    op.drop_column("sales_inquiry", "application")
    op.drop_column("sales_inquiry", "home_page")
