"""relax NOT NULL on remaining B-model columns (inventory_transaction/customer/supplier)

Revision ID: b8c9d0e1
Revises: a7b8c9d0
Create Date: 2026-04-15

继续 f6a7b8c9 / a7b8c9d0 —— 补齐 B 模型 blank-shell 创建路径剩下三张表：
- inventory_transaction: material/warehouse/transaction_type/transaction_date/quantity/unit_cost/total_cost
- customer: code / name
- supplier: code / name
推进下一态时由 workflow hard_rules 强制校验。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b8c9d0e1"
down_revision: Union[str, None] = "a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


RELAX = [
    ("inventory_transaction", "material_id",      sa.Integer()),
    ("inventory_transaction", "warehouse_id",     sa.Integer()),
    ("inventory_transaction", "transaction_type", sa.String(length=20)),
    ("inventory_transaction", "transaction_date", sa.Date()),
    ("inventory_transaction", "quantity",         sa.Numeric(16, 2)),
    ("inventory_transaction", "unit_cost",        sa.Numeric(16, 4)),
    ("inventory_transaction", "total_cost",       sa.Numeric(16, 2)),
    ("customer",              "code",             sa.String(length=30)),
    ("customer",              "name",             sa.String(length=200)),
    ("supplier",              "code",             sa.String(length=30)),
    ("supplier",              "name",             sa.String(length=200)),
]


def upgrade() -> None:
    for table, col, col_type in RELAX:
        op.alter_column(table, col, existing_type=col_type, nullable=True)


def downgrade() -> None:
    for table, col, col_type in RELAX:
        op.alter_column(table, col, existing_type=col_type, nullable=False)
