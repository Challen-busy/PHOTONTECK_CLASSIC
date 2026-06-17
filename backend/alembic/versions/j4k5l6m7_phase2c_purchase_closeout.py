"""phase2c: purchase close-out (进项发票审核 / 付款申请 / 采购在途)

Revision ID: j4k5l6m7
Revises: i3j4k5l6
Create Date: 2026-06-17

段2c 采购收尾（04a-6 / 04a-7 / 04a-8）：

- purchase_invoice 扩列（04a-7 ★进项发票审核）：
  due_date（到期日）/ reviewed_by_id / reviewed_at（FINANCE 审核留痕）。
- payment_request 新表（04a-8 货后付款，决策④：发起在采购、执行在财务）：
  关联 PO/已审进项发票，PA 发起→★FINANCE 执行→confirmed 到账确认；做账在金蝶。
- purchase_in_transit 新表（04a-6 采购在途）：一 PO 一行存 PA 录的承诺/最新货期 + 跟踪状态；
  订单/已收/在途由 /api/purchase/intransit 聚合 PO 明细实时算（不冗存）。

引擎五条不破坏：仅加表/加列，不动唯一写入路径（execute_transition / @register_command）。
PURCHASE_INVOICE ★审核节点 + PAYMENT_REQUEST 流程 = WorkflowDefinition states JSONB 配置
（services/phase1_workflows.py，经 seed_phase1 幂等写），非 schema 变更。
🔒Q18：进项发票/付款金额（采购成本/应付）对销售端 SALES+SA 隐藏 = services/tools.py BUY_TABLES/
BUY_PRICE_FIELDS（非 schema 层）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "j4k5l6m7"
down_revision: Union[str, Sequence[str], None] = "i3j4k5l6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- 04a-7：进项发票审核扩列 ---
    op.add_column("purchase_invoice", sa.Column("due_date", sa.Date(), nullable=True))
    op.add_column("purchase_invoice", sa.Column("reviewed_by_id", sa.Integer(), nullable=True))
    op.add_column("purchase_invoice", sa.Column("reviewed_at", sa.DateTime(), nullable=True))
    op.create_foreign_key(
        "fk_purchase_invoice_reviewed_by_id", "purchase_invoice", "user_account",
        ["reviewed_by_id"], ["id"],
    )

    # --- 04a-8：付款申请（货后付款）新表 ---
    op.create_table(
        "payment_request",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("company.id"), nullable=False, index=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("payment_number", sa.String(length=50), nullable=False, index=True),
        sa.Column("payment_type", sa.String(length=20), server_default="POST_DELIVERY"),
        sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("supplier.id"), nullable=True),
        sa.Column("purchase_order_id", sa.Integer(), sa.ForeignKey("purchase_order.id"), nullable=True),
        sa.Column("purchase_invoice_id", sa.Integer(), sa.ForeignKey("purchase_invoice.id"), nullable=True),
        sa.Column("requested_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("approved_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("bank_account", sa.String(length=50), server_default=""),
        sa.Column("payee_name", sa.String(length=100), server_default=""),
        sa.Column("amount", sa.Numeric(16, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="CNY"),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("payment_date", sa.Date(), nullable=True),
        sa.Column("confirmed", sa.Boolean(), server_default=sa.false()),
        sa.Column("status", sa.String(length=30), server_default="DRAFT"),
        sa.Column("notes", sa.Text(), server_default=""),
        sa.UniqueConstraint("company_id", "payment_number", name="ux_payment_request_number"),
    )

    # --- 04a-6：采购在途跟踪新表（一 PO 一行存 PA 录的货期）---
    op.create_table(
        "purchase_in_transit",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("company.id"), nullable=False, index=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("purchase_order_id", sa.Integer(), sa.ForeignKey("purchase_order.id"), nullable=False),
        sa.Column("promised_eta", sa.Date(), nullable=True),
        sa.Column("latest_eta", sa.Date(), nullable=True),
        sa.Column("track_status", sa.String(length=20), server_default="PENDING_ACCEPT"),
        sa.Column("shipped_date", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), server_default=""),
        sa.UniqueConstraint("company_id", "purchase_order_id", name="ux_purchase_in_transit_po"),
    )


def downgrade() -> None:
    op.drop_table("purchase_in_transit")
    op.drop_table("payment_request")
    op.drop_constraint("fk_purchase_invoice_reviewed_by_id", "purchase_invoice", type_="foreignkey")
    op.drop_column("purchase_invoice", "reviewed_at")
    op.drop_column("purchase_invoice", "reviewed_by_id")
    op.drop_column("purchase_invoice", "due_date")
