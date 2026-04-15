"""add status column to inventory_transaction (T-model 接入 workflow)

Revision ID: c9d0e1f2
Revises: b8c9d0e1
Create Date: 2026-04-15

INVENTORY_COSTING 流程对应 InventoryTransaction；workflow 依赖 doc.status，
原设计里该表无 status 列 → 补一列，默认 START，已有行回填 START。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c9d0e1f2"
down_revision: Union[str, None] = "b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "inventory_transaction",
        sa.Column("status", sa.String(length=15), nullable=True, server_default="START"),
    )
    op.create_index("ix_inventory_transaction_status", "inventory_transaction", ["status"])


def downgrade() -> None:
    op.drop_index("ix_inventory_transaction_status", table_name="inventory_transaction")
    op.drop_column("inventory_transaction", "status")
