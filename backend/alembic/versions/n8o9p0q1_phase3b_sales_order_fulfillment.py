"""phase3b: 销售订单履约对齐（决策①合同即 SO + ★预付到账闸 + 签章字段组 + 事业部分类）
+ 备货消单流水 stock_up_consumption（接段2d-1 遗留）

Revision ID: n8o9p0q1
Revises: m7n8o9p0
Create Date: 2026-06-17

段3b（PRD 05-客户销售-订单与履约 页面1/2/4/5）：
- sales_order 头扩列（决策①合同即 SO）：external_order_no（编号/客户订单号，全链只读）+
  合同签章字段组（contract_attachment_ref / signature_status / signature_party / signed_at，
  一签宝占位，引擎无对象存储/签章原生支持 → 字段 + 占位集成）+ business_unit/research_sub_market
  （事业部分类 + 科研细分市场，签单大表筛选维度）+ advance_receipt_confirmed（★预付到账闸放行标志）。
- stock_up_consumption 表：SO 成交累加 STOCK_UP_REQUEST.consumed_quantity 的明细留痕 + 幂等锚
  （(stock_up_request_id, sales_order_line_id) 唯一，consume_on_sales_order EXPLICIT effect 守卫读本表）。

引擎五条不破坏：仅加列/加表，不动唯一写入路径（execute_transition / @register_command）。
SO 流程对齐（SA leader 下级审核 + 签章 + ★到账闸 hard_rule + 推金蝶）= WorkflowDefinition states
JSONB 配置（services/phase1_workflows.py，经 seed_phase1 幂等写），非 schema 变更。
SO 内部订单号月度连号 SO-YYMM-001 = NumberingRule（seed.py）+ 建单取号 effect（numbering_effect.py）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "n8o9p0q1"
down_revision: Union[str, Sequence[str], None] = "m7n8o9p0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# sales_order 头扩列（决策①合同即 SO + ★到账闸 + 事业部分类）。
_SO_COLUMNS = [
    sa.Column("external_order_no", sa.String(length=50), server_default=""),
    sa.Column("contract_attachment_ref", sa.Text(), server_default=""),
    sa.Column("signature_status", sa.String(length=20), server_default="PENDING"),
    sa.Column("signature_party", sa.String(length=20), server_default=""),
    sa.Column("signed_at", sa.DateTime(), nullable=True),
    sa.Column("business_unit", sa.String(length=40), server_default=""),
    sa.Column("research_sub_market", sa.String(length=60), server_default=""),
    sa.Column("advance_receipt_confirmed", sa.Boolean(), server_default=sa.text("false")),
]


def upgrade() -> None:
    for col in _SO_COLUMNS:
        op.add_column("sales_order", col)
    op.create_index("ix_sales_order_external_order_no", "sales_order", ["external_order_no"])

    # === 备货消单流水 stock_up_consumption（段3b，接段2d-1 遗留）===
    op.create_table(
        "stock_up_consumption",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("company.id"), nullable=False, index=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("stock_up_request_id", sa.Integer(), sa.ForeignKey("stock_up_request.id"), nullable=False),
        sa.Column("sales_order_id", sa.Integer(), sa.ForeignKey("sales_order.id"), nullable=False),
        sa.Column("sales_order_line_id", sa.Integer(), sa.ForeignKey("sales_order_line.id"), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 2), nullable=False),
        sa.UniqueConstraint("stock_up_request_id", "sales_order_line_id", name="ux_stockup_consumption_so_line"),
    )


def downgrade() -> None:
    op.drop_table("stock_up_consumption")
    op.drop_index("ix_sales_order_external_order_no", table_name="sales_order")
    for col in reversed(_SO_COLUMNS):
        op.drop_column("sales_order", col.name)
