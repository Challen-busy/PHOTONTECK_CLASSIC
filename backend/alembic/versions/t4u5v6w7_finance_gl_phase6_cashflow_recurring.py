"""总账·第六波（finance-gl wave-6）：现金流量归集规则 + 定期凭证方案（+ 行子表）3 张新表

Revision ID: t4u5v6w7
Revises: s3t4u5v6
Create Date: 2026-06-18

总账·第六波「现金流量归集 + 期末补全（自动转账/摊销/预提）」靠新表落地，引擎五条不破坏：
- 新增 3 张配置主数据表（均 AuditMixin + __queryable__ + __doc_types__，company_id 隔离）：
  cashflow_assign_rule 现金流量归集规则 /
  recurring_voucher_scheme 定期凭证方案（+ recurring_voucher_line 分录模板子表）。
- 各表 (company_id, code) 唯一（recurring_voucher_line 为 (scheme_id, line_number)）。
- 建表顺序按 FK 依赖：cashflow_assign_rule(→cashflow_item) / recurring_voucher_scheme(→voucher_word,
  accounting_period)，再 recurring_voucher_line(→recurring_voucher_scheme/account)。
- 写仍走 execute_transition（MasterDataPage 唯一写入），各 doc_type 的轻量单状态机
  WorkflowDefinition 由 scripts.seed_master_gl 种入；registry/workflow/commands 核心零 diff。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "t4u5v6w7"
down_revision: Union[str, Sequence[str], None] = "s3t4u5v6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _audit_cols():
    """AuditMixin 公共列（对齐现有主数据迁移风格，见 s3t4u5v6）。"""
    return [
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("company.id"), nullable=False, index=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    ]


def upgrade() -> None:
    # === 1. 现金流量归集规则 cashflow_assign_rule（FK → cashflow_item）===
    op.create_table(
        "cashflow_assign_rule",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_audit_cols(),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("account_code_from", sa.String(20), server_default=""),
        sa.Column("account_code_to", sa.String(20), server_default=""),
        sa.Column("cash_direction", sa.String(5), nullable=False, server_default="BOTH"),
        sa.Column("cashflow_item_id", sa.Integer(), sa.ForeignKey("cashflow_item.id"), nullable=False),
        sa.Column("priority", sa.SmallInteger(), server_default="100"),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
        sa.UniqueConstraint("company_id", "code", name="ux_cashflow_assign_rule_company_code"),
    )

    # === 2. 定期凭证方案 recurring_voucher_scheme（FK → voucher_word / accounting_period）===
    op.create_table(
        "recurring_voucher_scheme",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_audit_cols(),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("scheme_type", sa.String(15), nullable=False, server_default="TRANSFER"),
        sa.Column("voucher_word_id", sa.Integer(), sa.ForeignKey("voucher_word.id"), nullable=True),
        sa.Column("description", sa.String(200), server_default=""),
        sa.Column("total_amount", sa.Numeric(16, 2), nullable=True),
        sa.Column("periods", sa.SmallInteger(), nullable=True),
        sa.Column("start_period_id", sa.Integer(), sa.ForeignKey("accounting_period.id"), nullable=True),
        sa.Column("amortized_periods", sa.SmallInteger(), server_default="0"),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
        sa.UniqueConstraint("company_id", "code", name="ux_recurring_voucher_scheme_company_code"),
    )

    # === 3. 定期凭证方案分录模板子表 recurring_voucher_line（FK → recurring_voucher_scheme / account）===
    op.create_table(
        "recurring_voucher_line",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scheme_id", sa.Integer(), sa.ForeignKey("recurring_voucher_scheme.id"), nullable=False, index=True),
        sa.Column("line_number", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("account.id"), nullable=True),
        sa.Column("account_code", sa.String(20), server_default=""),
        sa.Column("dr_cr", sa.String(2), nullable=False, server_default="DR"),
        sa.Column("description", sa.String(200), server_default=""),
        sa.Column("amount", sa.Numeric(16, 2), nullable=True),
        sa.Column("formula", sa.String(200), server_default=""),
        sa.UniqueConstraint("scheme_id", "line_number", name="ux_recurring_voucher_line"),
    )


def downgrade() -> None:
    op.drop_table("recurring_voucher_line")
    op.drop_table("recurring_voucher_scheme")
    op.drop_table("cashflow_assign_rule")
