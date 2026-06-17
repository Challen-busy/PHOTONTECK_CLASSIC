"""phase2b: purchase_order header extension (采购订单主链 PO 头扩列)

Revision ID: i3j4k5l6
Revises: h2i3j4k5
Create Date: 2026-06-17

段2b 采购主链（采购订单 PO，04a-3 / 04a-4）：

- PO 头扩列（源 PO total sheet）：
  factory_so_number（原厂 SO#）/ product_manager_id（产品经理 FK user）/
  pd_id（PD FK user）/ notice_date（采购通知日期）/
  stock_amount_original / stock_amount_latest / stock_quantity / stock_reason（备货金额组）。
- 🔒Q18 字段防火墙：advance_payment_amount / stock_amount_original / stock_amount_latest
  （采购进价/成本）+ 既有 total_amount / line.unit_price / line.total_price
  对销售端 SALES+SA 隐藏（落在 services/tools.py BUY_PRICE_FIELDS，非 schema 层）。

引擎五条不破坏：仅 purchase_order 加列，不动唯一写入路径（execute_transition / @register_command）。
PURCHASE_ORDER 流程重构为聚焦主链（DRAFT→PENDING_APPROVAL→★FINANCE_APPROVAL→ORDERED→
PARTIAL/RECEIVED→CLOSED）= WorkflowDefinition states JSONB 配置（services/phase1_workflows.py），
非 schema 变更，无迁移。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "i3j4k5l6"
down_revision: Union[str, Sequence[str], None] = "h2i3j4k5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("purchase_order", sa.Column("factory_so_number", sa.String(length=50), nullable=True, server_default=""))
    op.add_column("purchase_order", sa.Column("product_manager_id", sa.Integer(), nullable=True))
    op.add_column("purchase_order", sa.Column("pd_id", sa.Integer(), nullable=True))
    op.add_column("purchase_order", sa.Column("notice_date", sa.Date(), nullable=True))
    op.add_column("purchase_order", sa.Column("stock_amount_original", sa.Numeric(16, 2), nullable=True))
    op.add_column("purchase_order", sa.Column("stock_amount_latest", sa.Numeric(16, 2), nullable=True))
    op.add_column("purchase_order", sa.Column("stock_quantity", sa.Numeric(12, 2), nullable=True))
    op.add_column("purchase_order", sa.Column("stock_reason", sa.Text(), nullable=True, server_default=""))
    op.create_foreign_key(
        "fk_purchase_order_product_manager_id", "purchase_order", "user_account",
        ["product_manager_id"], ["id"],
    )
    op.create_foreign_key(
        "fk_purchase_order_pd_id", "purchase_order", "user_account",
        ["pd_id"], ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_purchase_order_pd_id", "purchase_order", type_="foreignkey")
    op.drop_constraint("fk_purchase_order_product_manager_id", "purchase_order", type_="foreignkey")
    op.drop_column("purchase_order", "stock_reason")
    op.drop_column("purchase_order", "stock_quantity")
    op.drop_column("purchase_order", "stock_amount_latest")
    op.drop_column("purchase_order", "stock_amount_original")
    op.drop_column("purchase_order", "notice_date")
    op.drop_column("purchase_order", "pd_id")
    op.drop_column("purchase_order", "product_manager_id")
    op.drop_column("purchase_order", "factory_so_number")
