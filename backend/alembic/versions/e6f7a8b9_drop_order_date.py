"""drop order_date from sales_order and purchase_order

Revision ID: e6f7a8b9
Revises: d5e6f7a8
Create Date: 2026-04-21

业务上 order_date 与 created_at 没有实际差异（无 backdating 场景），
且 order_date 没有任何写入路径（表单不填、workflow 不补默认），存量 90% 是 NULL。
彻底删除字段，前端日期列改用 created_at。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e6f7a8b9"
down_revision: Union[str, None] = "d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("sales_order", "order_date")
    op.drop_column("purchase_order", "order_date")


def downgrade() -> None:
    op.add_column("sales_order", sa.Column("order_date", sa.Date(), nullable=True))
    op.add_column("purchase_order", sa.Column("order_date", sa.Date(), nullable=True))
