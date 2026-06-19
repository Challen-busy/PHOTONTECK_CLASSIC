"""信用管理（finance-gl 信用波，完全替代金蝶信用管理 P0）

Revision ID: x8y9z0a1
Revises: w7x8y9z0
Create Date: 2026-06-19

金蝶信用管理 P0：信用档案 + 信用检查规则 + 占用流水 + 超标记录 + 信用控制总开关。
信用检查=transition validator（单据流转时按检查规则校验可用额度），占用=transition effect（流转增减占用流水）。

1. 新表 credit_check_rule（信用检查规则，MasterDataPage）+ credit_check_rule_line（明细：单据×时点×控制策略）。
2. 新表 credit_occupation（★占用流水，单一事实源，可重算）。
3. 新表 credit_overlimit_log（信用超标记录）。
4. 扩 customer_credit / supplier_credit 为完整信用档案（单笔限额/逾期阈值/检查规则/信用状态）。
5. company 加 credit_control_enabled（信用控制总开关，默认关）。

建表顺序按 FK：先建 credit_check_rule（被 customer/supplier_credit.check_rule_id 引用）再加列。
引擎五条不破坏：扩列 + 新表 + 新 doc_type（CREDIT_CHECK_RULE）；核心三件零 diff。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "x8y9z0a1"
down_revision: Union[str, Sequence[str], None] = "w7x8y9z0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _audit_cols():
    return [
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("company.id"), nullable=False, index=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    ]


def upgrade() -> None:
    # === 1. 信用检查规则（先建，被 credit 档案 FK 引用）===
    op.create_table(
        "credit_check_rule",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_audit_cols(),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("remark", sa.String(200), server_default=""),
        sa.UniqueConstraint("company_id", "code", name="ux_credit_check_rule_code"),
    )
    op.create_table(
        "credit_check_rule_line",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("credit_check_rule_id", sa.Integer(), sa.ForeignKey("credit_check_rule.id"), nullable=False, index=True),
        sa.Column("line_number", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("doc_name", sa.String(50), server_default=""),
        sa.Column("doc_type", sa.String(40), nullable=False),
        sa.Column("check_point", sa.String(10), server_default="AUDIT"),
        sa.Column("control_strategy", sa.String(10), server_default="WARN"),
        sa.Column("update_credit", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("check_credit_limit", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("check_single_limit", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("check_overdue", sa.Boolean(), server_default=sa.text("false")),
        sa.UniqueConstraint("credit_check_rule_id", "line_number", name="ux_credit_check_rule_line"),
    )

    # === 2. 占用流水 ===
    op.create_table(
        "credit_occupation",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("company.id"), nullable=False, index=True),
        sa.Column("party_type", sa.String(10), nullable=False, server_default="CUSTOMER"),
        sa.Column("party_id", sa.Integer(), nullable=False, index=True),
        sa.Column("currency", sa.String(3), server_default=""),
        sa.Column("doc_type", sa.String(40), nullable=False),
        sa.Column("doc_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("occupy_amount", sa.Numeric(16, 2), nullable=False, server_default="0"),
        sa.Column("occupy_date", sa.Date(), nullable=True),
        sa.Column("is_released", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("released_at", sa.DateTime(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_credit_occupation_party", "credit_occupation",
                    ["company_id", "party_type", "party_id", "is_released"])

    # === 3. 超标记录 ===
    op.create_table(
        "credit_overlimit_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("company.id"), nullable=False, index=True),
        sa.Column("party_type", sa.String(10), nullable=False, server_default="CUSTOMER"),
        sa.Column("party_id", sa.Integer(), nullable=False, index=True),
        sa.Column("doc_type", sa.String(40), server_default=""),
        sa.Column("doc_id", sa.BigInteger(), nullable=True),
        sa.Column("doc_no", sa.String(50), server_default=""),
        sa.Column("biz_date", sa.Date(), nullable=True),
        sa.Column("occupy_amount", sa.Numeric(16, 2), server_default="0"),
        sa.Column("credit_limit", sa.Numeric(16, 2), server_default="0"),
        sa.Column("available_before", sa.Numeric(16, 2), server_default="0"),
        sa.Column("over_amount", sa.Numeric(16, 2), server_default="0"),
        sa.Column("over_type", sa.String(20), server_default="CREDIT_LIMIT"),
        sa.Column("control_strategy", sa.String(10), server_default="WARN"),
        sa.Column("action", sa.String(10), server_default="WARN"),
        sa.Column("handled_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_credit_overlimit_party", "credit_overlimit_log",
                    ["company_id", "party_type", "party_id"])

    # === 4. 扩 customer_credit / supplier_credit 为完整信用档案 ===
    for tbl in ("customer_credit", "supplier_credit"):
        op.add_column(tbl, sa.Column("single_limit", sa.Numeric(16, 2), server_default="0"))
        op.add_column(tbl, sa.Column("overdue_days", sa.Integer(), server_default="0"))
        op.add_column(tbl, sa.Column("overdue_amount", sa.Numeric(16, 2), server_default="0"))
        op.add_column(tbl, sa.Column("overdue_ratio", sa.Numeric(5, 2), server_default="0"))
        op.add_column(tbl, sa.Column("check_rule_id", sa.Integer(), sa.ForeignKey("credit_check_rule.id"), nullable=True))
        op.add_column(tbl, sa.Column("credit_status", sa.String(10), server_default="NORMAL"))
    # supplier_credit 补 credit_rating / credit_period_days（customer_credit 已有）
    op.add_column("supplier_credit", sa.Column("credit_rating", sa.String(10), server_default=""))
    op.add_column("supplier_credit", sa.Column("credit_period_days", sa.Integer(), server_default="30"))

    # === 5. company 信用控制总开关 ===
    op.add_column("company", sa.Column("credit_control_enabled", sa.Boolean(), server_default=sa.text("false")))


def downgrade() -> None:
    op.drop_column("company", "credit_control_enabled")
    op.drop_column("supplier_credit", "credit_period_days")
    op.drop_column("supplier_credit", "credit_rating")
    for tbl in ("customer_credit", "supplier_credit"):
        for col in ("credit_status", "check_rule_id", "overdue_ratio", "overdue_amount", "overdue_days", "single_limit"):
            op.drop_column(tbl, col)
    op.drop_index("ix_credit_overlimit_party", table_name="credit_overlimit_log")
    op.drop_table("credit_overlimit_log")
    op.drop_index("ix_credit_occupation_party", table_name="credit_occupation")
    op.drop_table("credit_occupation")
    op.drop_table("credit_check_rule_line")
    op.drop_table("credit_check_rule")
