"""wms phase2 operational controls

Revision ID: 1b2c3d4e
Revises: 0a1b2c3d
Create Date: 2026-04-30
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "1b2c3d4e"
down_revision: Union[str, None] = "0a1b2c3d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("inventory", sa.Column("unit_cost", sa.Numeric(precision=16, scale=4), server_default="0", nullable=True))
    op.add_column("inventory", sa.Column("total_cost", sa.Numeric(precision=16, scale=2), server_default="0", nullable=True))

    op.create_table(
        "inventory_policy",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("material_id", sa.Integer(), nullable=False),
        sa.Column("warehouse_id", sa.Integer(), nullable=True),
        sa.Column("safety_stock", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("reorder_point", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("max_stock", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("lead_time_days", sa.Integer(), nullable=True),
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
        sa.ForeignKeyConstraint(["material_id"], ["material.id"]),
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouse.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "material_id", "warehouse_id"),
    )
    op.create_index("ix_inventory_policy_company_id", "inventory_policy", ["company_id"])
    op.create_index("ix_inventory_policy_material_warehouse", "inventory_policy", ["material_id", "warehouse_id"])

    op.create_table(
        "inventory_count",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("count_number", sa.String(length=40), nullable=False),
        sa.Column("warehouse_id", sa.Integer(), nullable=True),
        sa.Column("planned_date", sa.Date(), nullable=True),
        sa.Column("counted_by_id", sa.Integer(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("adjusted_at", sa.DateTime(), nullable=True),
        sa.Column("adjusted_by_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["company.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["user_account.id"]),
        sa.ForeignKeyConstraint(["updated_by_id"], ["user_account.id"]),
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouse.id"]),
        sa.ForeignKeyConstraint(["counted_by_id"], ["user_account.id"]),
        sa.ForeignKeyConstraint(["adjusted_by_id"], ["user_account.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "count_number"),
    )
    op.create_index("ix_inventory_count_company_id", "inventory_count", ["company_id"])
    op.create_index("ix_inventory_count_count_number", "inventory_count", ["count_number"])

    op.create_table(
        "inventory_count_line",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("inventory_count_id", sa.Integer(), nullable=False),
        sa.Column("inventory_id", sa.Integer(), nullable=False),
        sa.Column("material_id", sa.Integer(), nullable=False),
        sa.Column("warehouse_id", sa.Integer(), nullable=True),
        sa.Column("location_code", sa.String(length=50), nullable=True),
        sa.Column("batch_number", sa.String(length=50), nullable=True),
        sa.Column("inbound_number", sa.String(length=50), nullable=True),
        sa.Column("serial_lot_number", sa.String(length=100), nullable=True),
        sa.Column("system_quantity", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("counted_quantity", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("difference_quantity", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["inventory_count_id"], ["inventory_count.id"]),
        sa.ForeignKeyConstraint(["inventory_id"], ["inventory.id"]),
        sa.ForeignKeyConstraint(["material_id"], ["material.id"]),
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouse.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("inventory_count_id", "inventory_id"),
    )
    op.create_index("ix_inventory_count_line_count", "inventory_count_line", ["inventory_count_id"])


def downgrade() -> None:
    op.drop_index("ix_inventory_count_line_count", table_name="inventory_count_line")
    op.drop_table("inventory_count_line")

    op.drop_index("ix_inventory_count_count_number", table_name="inventory_count")
    op.drop_index("ix_inventory_count_company_id", table_name="inventory_count")
    op.drop_table("inventory_count")

    op.drop_index("ix_inventory_policy_material_warehouse", table_name="inventory_policy")
    op.drop_index("ix_inventory_policy_company_id", table_name="inventory_policy")
    op.drop_table("inventory_policy")

    op.drop_column("inventory", "total_cost")
    op.drop_column("inventory", "unit_cost")
