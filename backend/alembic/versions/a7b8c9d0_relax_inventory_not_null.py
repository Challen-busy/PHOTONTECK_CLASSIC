"""relax NOT NULL on inventory business columns for blank-shell creation

Revision ID: a7b8c9d0
Revises: f6a7b8c9
Create Date: 2026-04-15

延续 f6a7b8c9 —— inventory 表建空壳需要放开 material_id/warehouse_id/received_date/quantity
的 NOT NULL；由 workflow hard_rules 在推进下一态时强制校验。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a7b8c9d0"
down_revision: Union[str, None] = "f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


RELAX = [
    ("inventory", "material_id",   sa.Integer()),
    ("inventory", "warehouse_id",  sa.Integer()),
    ("inventory", "received_date", sa.Date()),
    ("inventory", "quantity",      sa.Numeric(12, 2)),
]


def upgrade() -> None:
    for table, col, col_type in RELAX:
        op.alter_column(table, col, existing_type=col_type, nullable=True)


def downgrade() -> None:
    for table, col, col_type in RELAX:
        op.alter_column(table, col, existing_type=col_type, nullable=False)
