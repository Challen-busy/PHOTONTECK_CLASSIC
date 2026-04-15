"""relax NOT NULL on business FKs to allow blank-shell creation in START state

Revision ID: f6a7b8c9
Revises: e5f6a7b8
Create Date: 2026-04-15

业务外键放开 NOT NULL：B-model 创建路径会先建空壳进 START，由 workflow hard_rules
在进入下一态时强制校验。保留 *_number / voucher_date / period_id 等可由 auto-fill
兜底的列原状。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f6a7b8c9"
down_revision: Union[str, None] = "e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


RELAX = [
    ("purchase_order",      "supplier_id",        sa.Integer()),
    ("sales_order",         "customer_id",        sa.Integer()),
    ("framework_contract",  "customer_id",        sa.Integer()),
    ("framework_contract",  "start_date",         sa.Date()),
    ("framework_contract",  "end_date",           sa.Date()),
    ("goods_receipt",       "purchase_order_id",  sa.Integer()),
    ("goods_receipt",       "warehouse_id",       sa.Integer()),
    ("shipment_request",    "sales_order_id",     sa.Integer()),
    ("shipment_request",    "requested_by_id",    sa.Integer()),
    ("accounts_payable",    "supplier_id",        sa.Integer()),
    ("accounts_payable",    "purchase_order_id",  sa.Integer()),
    ("accounts_payable",    "amount",             sa.Numeric(16, 2)),
    ("accounts_payable",    "currency",           sa.String(length=3)),
    ("accounts_payable",    "due_date",           sa.Date()),
    ("accounts_receivable", "customer_id",        sa.Integer()),
    ("accounts_receivable", "sales_order_id",     sa.Integer()),
    ("accounts_receivable", "amount",             sa.Numeric(16, 2)),
    ("accounts_receivable", "currency",           sa.String(length=3)),
    ("accounts_receivable", "due_date",           sa.Date()),
    ("project",             "customer_id",        sa.Integer()),
    ("project",             "name",               sa.String(length=200)),
]


def upgrade() -> None:
    for table, col, col_type in RELAX:
        op.alter_column(table, col, existing_type=col_type, nullable=True)


def downgrade() -> None:
    for table, col, col_type in RELAX:
        op.alter_column(table, col, existing_type=col_type, nullable=False)
