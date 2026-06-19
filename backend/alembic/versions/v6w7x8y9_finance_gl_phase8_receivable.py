"""总账·第八波（finance-gl wave-8）应收款管理（完全替代金蝶应收款管理）

Revision ID: v6w7x8y9
Revises: u5v6w7x8
Create Date: 2026-06-19

金蝶应收款管理三件套 + 通用核销引擎落地（biz_type=AR/AP 参数化，应付/出纳后续直接复用）：

1. 扩 accounts_receivable（doc_type 复用 ACCOUNTS_RECEIVABLE）：补金蝶应收单头字段
   （单号/立账类型/业务日期/收款条件/销售员/销售组织/价外税开关/已核销额/核销状态/本位币双金额）。
   新增列均 nullable / server_default → 存量行兼容（引擎五条不破坏）。
2. 新子表 ar_bill_line 应收单明细（物料×计价数量×单价×税率组×不含税/税额/价税合计）。
3. 新子表 ar_receipt_plan_line 应收单收款计划（到期日/比例/金额）。
4. 新表 ar_receipt 收款单（doc_type AR_RECEIPT）：客户/币别/收款日期/结算方式/银行账户/金额/
   是否预收/已核销额/状态。
5. 新主数据 writeoff_scheme 核销方案（biz_type/match_rule FIFO|SAME_AMOUNT|BY_DUEDATE|MANUAL/
   优先级，MasterDataPage 可建/改）。
6. ★新表 writeoff_link 通用核销关系（biz_type/债权侧 debit_*/已收侧 credit_*/amount/base_amount/
   exchange_diff 汇兑差/write_date/结算组织；多对多勾稽；弱引用多态兼容 AR/AP）。

引擎五条不破坏：均为扩展点（扩列 + 新表 + 新 doc_type + 新版 WorkflowDefinition）；核心三件零 diff。
写仍走 execute_transition / @register_command（命令在 Phase2 建）。
建表顺序按 FK 依赖：ar_bill_line/ar_receipt_plan_line(→accounts_receivable) → ar_receipt(→settlement_method) →
writeoff_scheme → writeoff_link(→writeoff_scheme)。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "v6w7x8y9"
down_revision: Union[str, Sequence[str], None] = "u5v6w7x8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _audit_cols():
    """AuditMixin 公共列（对齐现有迁移风格，见 u5v6w7x8）。"""
    return [
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("company.id"), nullable=False, index=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    ]


def upgrade() -> None:
    # === 1. 扩 accounts_receivable：金蝶应收单头字段（新增列均 nullable / 带 default）===
    op.add_column("accounts_receivable", sa.Column("bill_number", sa.String(40), server_default=""))
    op.add_column("accounts_receivable", sa.Column("bill_type", sa.String(20), server_default="BUSINESS_AR"))
    op.add_column("accounts_receivable", sa.Column("bill_date", sa.Date(), nullable=True))
    op.add_column("accounts_receivable", sa.Column("base_currency", sa.String(3), server_default=""))
    op.add_column("accounts_receivable", sa.Column("base_amount", sa.Numeric(16, 2), nullable=True))
    op.add_column("accounts_receivable", sa.Column("payment_terms_text", sa.String(100), server_default=""))
    op.add_column("accounts_receivable", sa.Column("sales_engineer_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True))
    op.add_column("accounts_receivable", sa.Column("sales_org_id", sa.Integer(), sa.ForeignKey("company.id"), nullable=True))
    op.add_column("accounts_receivable", sa.Column("sales_dept", sa.String(50), server_default=""))
    op.add_column("accounts_receivable", sa.Column("is_tax_included", sa.Boolean(), server_default=sa.text("false")))
    op.add_column("accounts_receivable", sa.Column("is_price_tax_inclusive", sa.Boolean(), server_default=sa.text("false")))
    op.add_column("accounts_receivable", sa.Column("tax_amount", sa.Numeric(16, 2), server_default="0"))
    op.add_column("accounts_receivable", sa.Column("untaxed_amount", sa.Numeric(16, 2), server_default="0"))
    op.add_column("accounts_receivable", sa.Column("written_off_amount", sa.Numeric(16, 2), server_default="0"))
    op.add_column("accounts_receivable", sa.Column("writeoff_status", sa.String(15), server_default="UNVERIFIED"))
    op.add_column("accounts_receivable", sa.Column("remark", sa.Text(), server_default=""))
    op.create_index("ix_accounts_receivable_bill_number", "accounts_receivable", ["bill_number"])
    op.create_unique_constraint(
        "ux_accounts_receivable_bill_number", "accounts_receivable", ["company_id", "bill_number"])

    # === 2. 应收单明细子表 ar_bill_line（FK → accounts_receivable / material / sales_order_line / sales_invoice_line）===
    op.create_table(
        "ar_bill_line",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("accounts_receivable_id", sa.Integer(), sa.ForeignKey("accounts_receivable.id"), nullable=False, index=True),
        sa.Column("line_number", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("material_id", sa.Integer(), sa.ForeignKey("material.id"), nullable=True),
        sa.Column("material_code", sa.String(50), server_default=""),
        sa.Column("material_name", sa.String(300), server_default=""),
        sa.Column("sales_order_line_id", sa.Integer(), sa.ForeignKey("sales_order_line.id"), nullable=True),
        sa.Column("sales_invoice_line_id", sa.Integer(), sa.ForeignKey("sales_invoice_line.id"), nullable=True),
        sa.Column("quantity", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("uom", sa.String(20), server_default=""),
        sa.Column("unit_price", sa.Numeric(12, 4), nullable=False, server_default="0"),
        sa.Column("tax_rate_group", sa.String(30), server_default=""),
        sa.Column("tax_rate", sa.Numeric(5, 2), server_default="0"),
        sa.Column("untaxed_amount", sa.Numeric(16, 2), server_default="0"),
        sa.Column("tax_amount", sa.Numeric(16, 2), server_default="0"),
        sa.Column("amount", sa.Numeric(16, 2), server_default="0"),
        sa.Column("remark", sa.String(200), server_default=""),
        sa.UniqueConstraint("accounts_receivable_id", "line_number", name="ux_ar_bill_line"),
    )

    # === 3. 应收单收款计划子表 ar_receipt_plan_line（FK → accounts_receivable）===
    op.create_table(
        "ar_receipt_plan_line",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("accounts_receivable_id", sa.Integer(), sa.ForeignKey("accounts_receivable.id"), nullable=False, index=True),
        sa.Column("line_number", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("ratio", sa.Numeric(7, 4), server_default="0"),
        sa.Column("plan_amount", sa.Numeric(16, 2), server_default="0"),
        sa.Column("received_amount", sa.Numeric(16, 2), server_default="0"),
        sa.Column("remark", sa.String(200), server_default=""),
        sa.UniqueConstraint("accounts_receivable_id", "line_number", name="ux_ar_receipt_plan_line"),
    )

    # === 4. 收款单 ar_receipt（doc_type AR_RECEIPT；FK → customer / settlement_method / voucher）===
    op.create_table(
        "ar_receipt",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_audit_cols(),
        sa.Column("receipt_number", sa.String(40), nullable=False, index=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customer.id"), nullable=True),
        sa.Column("receipt_date", sa.Date(), nullable=True),
        sa.Column("currency", sa.String(3), server_default=""),
        sa.Column("exchange_rate", sa.Numeric(12, 6), server_default="1"),
        sa.Column("base_currency", sa.String(3), server_default=""),
        sa.Column("base_amount", sa.Numeric(16, 2), nullable=True),
        sa.Column("amount", sa.Numeric(16, 2), nullable=False, server_default="0"),
        sa.Column("settlement_method_id", sa.Integer(), sa.ForeignKey("settlement_method.id"), nullable=True),
        sa.Column("bank_account", sa.String(50), server_default=""),
        sa.Column("payer_name", sa.String(100), server_default=""),
        sa.Column("is_advance", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("voucher_id", sa.Integer(), sa.ForeignKey("voucher.id"), nullable=True),
        sa.Column("written_off_amount", sa.Numeric(16, 2), server_default="0"),
        sa.Column("writeoff_status", sa.String(15), server_default="UNVERIFIED"),
        sa.Column("status", sa.String(30), server_default="DRAFT"),
        sa.Column("remark", sa.Text(), server_default=""),
        sa.UniqueConstraint("company_id", "receipt_number", name="ux_ar_receipt_number"),
    )

    # === 5. 核销方案 writeoff_scheme（通用主数据，biz_type=AR/AP）===
    op.create_table(
        "writeoff_scheme",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_audit_cols(),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("biz_type", sa.String(5), nullable=False, server_default="AR"),
        sa.Column("match_rule", sa.String(15), nullable=False, server_default="FIFO"),
        sa.Column("priority", sa.SmallInteger(), nullable=False, server_default="100"),
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("remark", sa.String(200), server_default=""),
        sa.UniqueConstraint("company_id", "biz_type", "code", name="ux_writeoff_scheme_company_biztype_code"),
    )

    # === 6. ★通用核销关系 writeoff_link（FK → company / writeoff_scheme；债权/已收弱引用多态）===
    op.create_table(
        "writeoff_link",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("company.id"), nullable=False, index=True),
        sa.Column("biz_type", sa.String(5), nullable=False, server_default="AR"),
        sa.Column("scheme_id", sa.Integer(), sa.ForeignKey("writeoff_scheme.id"), nullable=True),
        sa.Column("debit_doc_type", sa.String(30), nullable=False),
        sa.Column("debit_doc_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("debit_line_id", sa.BigInteger(), nullable=True),
        sa.Column("credit_doc_type", sa.String(30), nullable=False),
        sa.Column("credit_doc_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("credit_line_id", sa.BigInteger(), nullable=True),
        sa.Column("amount", sa.Numeric(16, 2), nullable=False, server_default="0"),
        sa.Column("base_amount", sa.Numeric(16, 2), server_default="0"),
        sa.Column("exchange_diff", sa.Numeric(16, 2), server_default="0"),
        sa.Column("write_date", sa.Date(), nullable=True),
        sa.Column("settlement_org_id", sa.Integer(), sa.ForeignKey("company.id"), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_writeoff_link_debit", "writeoff_link", ["biz_type", "debit_doc_type", "debit_doc_id"])
    op.create_index("ix_writeoff_link_credit", "writeoff_link", ["biz_type", "credit_doc_type", "credit_doc_id"])


def downgrade() -> None:
    op.drop_index("ix_writeoff_link_credit", table_name="writeoff_link")
    op.drop_index("ix_writeoff_link_debit", table_name="writeoff_link")
    op.drop_table("writeoff_link")
    op.drop_table("writeoff_scheme")
    op.drop_table("ar_receipt")
    op.drop_table("ar_receipt_plan_line")
    op.drop_table("ar_bill_line")
    op.drop_constraint("ux_accounts_receivable_bill_number", "accounts_receivable", type_="unique")
    op.drop_index("ix_accounts_receivable_bill_number", table_name="accounts_receivable")
    for col in (
        "remark", "writeoff_status", "written_off_amount", "untaxed_amount", "tax_amount",
        "is_price_tax_inclusive", "is_tax_included", "sales_dept", "sales_org_id",
        "sales_engineer_id", "payment_terms_text", "base_amount", "base_currency",
        "bill_date", "bill_type", "bill_number",
    ):
        op.drop_column("accounts_receivable", col)
