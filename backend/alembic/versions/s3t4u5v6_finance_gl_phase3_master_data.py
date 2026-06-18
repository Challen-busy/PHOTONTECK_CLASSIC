"""总账·第三波（finance-gl wave-3）配账主数据：7 张基础资料表

Revision ID: s3t4u5v6
Revises: r2s3t4u5
Create Date: 2026-06-18

总账·第三波「配账主数据维护 UI」全靠新表落地，引擎五条不破坏：
- 新增 7 张配置主数据表（均 AuditMixin + __queryable__ + __doc_types__，company_id 隔离）：
  currency 币别 / settlement_method 结算方式 / accounting_policy 会计政策 /
  accounting_system 会计核算体系 / summary_entry 摘要库 /
  model_voucher 模式凭证（+ model_voucher_line 分录模板子表）/ auxiliary_dimension_value 核算维度数据。
- 既有 GL 主数据类（Account/VoucherWord/AuxiliaryDimension/CashflowItem/ExchangeRate）只在
  models.py 加 __doc_types__ 使其「可建档」，无 schema 变更（不在本迁移内）。
- 各表 (company_id, code) 唯一（auxiliary_dimension_value 为 (company_id, dimension_id, code)）。
- 建表顺序按 FK 依赖：先 currency/settlement_method/accounting_policy/summary_entry/
  auxiliary_dimension_value，再 accounting_system(→policy)、model_voucher(→voucher_word)、
  model_voucher_line(→model_voucher/account)。
- 写仍走 execute_transition（MasterDataPage 唯一写入），各 doc_type 的轻量单状态机
  WorkflowDefinition 由 scripts.seed_master_gl 种入；registry/workflow/commands 核心零 diff。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "s3t4u5v6"
down_revision: Union[str, Sequence[str], None] = "r2s3t4u5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _audit_cols():
    """AuditMixin 公共列（对齐现有主数据迁移风格，见 r2s3t4u5）。"""
    return [
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("company.id"), nullable=False, index=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    ]


def upgrade() -> None:
    # === 1. 币别 currency ===
    op.create_table(
        "currency",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_audit_cols(),
        sa.Column("code", sa.String(3), nullable=False),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("symbol", sa.String(10), server_default=""),
        sa.Column("is_base", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("decimal_places", sa.SmallInteger(), server_default="2"),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
        sa.UniqueConstraint("company_id", "code", name="ux_currency_company_code"),
    )

    # === 2. 结算方式 settlement_method ===
    op.create_table(
        "settlement_method",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_audit_cols(),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("method_type", sa.String(15), nullable=False, server_default="CASH"),
        sa.Column("needs_settlement_no", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
        sa.UniqueConstraint("company_id", "code", name="ux_settlement_method_company_code"),
    )

    # === 3. 会计政策 accounting_policy ===
    op.create_table(
        "accounting_policy",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_audit_cols(),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("standard", sa.String(10), nullable=False, server_default="CAS"),
        sa.Column("measurement_basis", sa.String(20), server_default="HISTORICAL_COST"),
        sa.Column("depreciation_method", sa.String(20), server_default="STRAIGHT_LINE"),
        sa.Column("inventory_valuation", sa.String(20), server_default="WEIGHTED_AVG"),
        sa.Column("bad_debt_method", sa.String(20), server_default="ALLOWANCE"),
        sa.Column("fiscal_year_start_month", sa.SmallInteger(), server_default="1"),
        sa.Column("extra", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb")),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
        sa.UniqueConstraint("company_id", "code", name="ux_accounting_policy_company_code"),
    )

    # === 4. 会计核算体系 accounting_system（FK → accounting_policy）===
    op.create_table(
        "accounting_system",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_audit_cols(),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("base_currency", sa.String(3), nullable=False, server_default="CNY"),
        sa.Column("standard", sa.String(10), nullable=False, server_default="CAS"),
        sa.Column("policy_id", sa.Integer(), sa.ForeignKey("accounting_policy.id"), nullable=True),
        sa.Column("start_year", sa.Integer(), nullable=True),
        sa.Column("start_period", sa.SmallInteger(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
        sa.UniqueConstraint("company_id", "code", name="ux_accounting_system_company_code"),
    )

    # === 5. 摘要库 summary_entry ===
    op.create_table(
        "summary_entry",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_audit_cols(),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("category", sa.String(30), server_default=""),
        sa.Column("text", sa.String(200), nullable=False),
        sa.Column("sort_order", sa.SmallInteger(), server_default="0"),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
        sa.UniqueConstraint("company_id", "code", name="ux_summary_entry_company_code"),
    )

    # === 6. 模式凭证 model_voucher（FK → voucher_word）+ 子表 model_voucher_line ===
    op.create_table(
        "model_voucher",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_audit_cols(),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("voucher_word_id", sa.Integer(), sa.ForeignKey("voucher_word.id"), nullable=True),
        sa.Column("default_description", sa.String(200), server_default=""),
        sa.Column("notes", sa.Text(), server_default=""),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
        sa.UniqueConstraint("company_id", "code", name="ux_model_voucher_company_code"),
    )
    op.create_table(
        "model_voucher_line",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("model_voucher_id", sa.Integer(), sa.ForeignKey("model_voucher.id"), nullable=False, index=True),
        sa.Column("line_number", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("account.id"), nullable=True),
        sa.Column("account_code", sa.String(20), server_default=""),
        sa.Column("dr_cr", sa.String(2), nullable=False, server_default="DR"),
        sa.Column("description", sa.String(200), server_default=""),
        sa.Column("amount", sa.Numeric(16, 2), nullable=True),
        sa.UniqueConstraint("model_voucher_id", "line_number", name="ux_model_voucher_line"),
    )

    # === 7. 核算维度数据 auxiliary_dimension_value（FK → auxiliary_dimension + 自引用）===
    op.create_table(
        "auxiliary_dimension_value",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_audit_cols(),
        sa.Column("dimension_id", sa.Integer(), sa.ForeignKey("auxiliary_dimension.id"), nullable=False, index=True),
        sa.Column("code", sa.String(30), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("parent_id", sa.Integer(), sa.ForeignKey("auxiliary_dimension_value.id"), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
        sa.UniqueConstraint("company_id", "dimension_id", "code", name="ux_aux_dim_value_company_dim_code"),
    )


def downgrade() -> None:
    op.drop_table("auxiliary_dimension_value")
    op.drop_table("model_voucher_line")
    op.drop_table("model_voucher")
    op.drop_table("summary_entry")
    op.drop_table("accounting_system")
    op.drop_table("accounting_policy")
    op.drop_table("settlement_method")
    op.drop_table("currency")
