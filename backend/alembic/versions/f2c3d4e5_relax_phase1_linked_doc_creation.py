"""relax phase 1 linked document creation

Revision ID: f2c3d4e5
Revises: f1b2c3d4
Create Date: 2026-04-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f2c3d4e5"
down_revision: Union[str, None] = "f1b2c3d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("purchase_notice", "sales_order_id", existing_type=sa.Integer(), nullable=True)
    op.alter_column("sales_return", "sales_order_id", existing_type=sa.Integer(), nullable=True)
    op.alter_column("advance_receipt", "customer_id", existing_type=sa.Integer(), nullable=True)
    op.alter_column("advance_receipt", "sales_order_id", existing_type=sa.Integer(), nullable=True)
    op.alter_column("advance_payment", "supplier_id", existing_type=sa.Integer(), nullable=True)
    op.alter_column("advance_payment", "purchase_order_id", existing_type=sa.Integer(), nullable=True)
    op.alter_column("purchase_invoice", "supplier_id", existing_type=sa.Integer(), nullable=True)
    op.alter_column("sales_invoice", "customer_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    op.alter_column("sales_invoice", "customer_id", existing_type=sa.Integer(), nullable=False)
    op.alter_column("purchase_invoice", "supplier_id", existing_type=sa.Integer(), nullable=False)
    op.alter_column("advance_payment", "purchase_order_id", existing_type=sa.Integer(), nullable=False)
    op.alter_column("advance_payment", "supplier_id", existing_type=sa.Integer(), nullable=False)
    op.alter_column("advance_receipt", "sales_order_id", existing_type=sa.Integer(), nullable=False)
    op.alter_column("advance_receipt", "customer_id", existing_type=sa.Integer(), nullable=False)
    op.alter_column("sales_return", "sales_order_id", existing_type=sa.Integer(), nullable=False)
    op.alter_column("purchase_notice", "sales_order_id", existing_type=sa.Integer(), nullable=False)
