"""phase2d-1: 备货申请单 STOCK_UP_REQUEST（04b-1）

Revision ID: k5l6m7n8
Revises: j4k5l6m7
Create Date: 2026-06-17

段2d-1 备货申请（04b-1）：引擎排除「备货」业务（引擎 02 §2.9）→ 全新增 doc_type。

- stock_up_request 新表：销售/PM 提议囤货，金额阈值分流（<20万 PM 单批 / ≥20万 PM+FINANCE 会审）。
  头存型号/备货数量/库存在途快照/意向客户/签单公司/欠款/原因/风险/金额/草稿PO/已消数量/状态。
- ≥20万会审复用并行会签标准件（cosign_line，cosign_group=STOCK_REVIEW），不新增表。
- request_number 月度连号 SU-YYMM-001 复用 NumberingRule（seed_phase1 注册规则）。

引擎五条不破坏：仅加表，不动唯一写入路径（execute_transition / @register_command）。
STOCK_UP_REQUEST 流程 = WorkflowDefinition states JSONB 配置（services/phase1_workflows.py，
经 seed_phase1 幂等写），非 schema 变更。阈值分流 = 边级 hard_rules（rules DSL）。
🔒Q18：amount 为含税报价口径，对 SALES 可见，单上无成本/买价列 → 不进 BUY_TABLES（非 schema 层）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "k5l6m7n8"
down_revision: Union[str, Sequence[str], None] = "j4k5l6m7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stock_up_request",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("company.id"), nullable=False, index=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("request_number", sa.String(length=30), nullable=False, index=True),
        sa.Column("requested_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("requester_role", sa.String(length=30), server_default=""),
        sa.Column("material_id", sa.Integer(), sa.ForeignKey("material.id"), nullable=True),
        sa.Column("stockup_quantity", sa.Numeric(12, 2), nullable=True),
        sa.Column("stock_on_hand", sa.Numeric(12, 2), nullable=True),
        sa.Column("in_transit_qty", sa.Numeric(12, 2), nullable=True),
        sa.Column("intended_customer_id", sa.Integer(), sa.ForeignKey("customer.id"), nullable=True),
        sa.Column("signing_company_id", sa.Integer(), sa.ForeignKey("company.id"), nullable=True),
        sa.Column("customer_arrears", sa.Numeric(16, 2), nullable=True),
        sa.Column("reason", sa.Text(), server_default=""),
        sa.Column("risk_notes", sa.Text(), server_default=""),
        sa.Column("amount", sa.Numeric(16, 2), nullable=True),
        sa.Column("currency", sa.String(length=3), server_default="USD"),
        sa.Column("draft_po_id", sa.Integer(), sa.ForeignKey("purchase_order.id"), nullable=True),
        sa.Column("consumed_quantity", sa.Numeric(12, 2), server_default="0"),
        sa.Column("status", sa.String(length=30), server_default="DRAFT"),
        sa.Column("notes", sa.Text(), server_default=""),
        sa.UniqueConstraint("company_id", "request_number", name="ux_stock_up_request_number"),
    )


def downgrade() -> None:
    op.drop_table("stock_up_request")
