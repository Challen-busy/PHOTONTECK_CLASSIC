"""应付款管理（finance-gl 应付波，完全替代金蝶应付款管理）

Revision ID: w7x8y9z0
Revises: v6w7x8y9
Create Date: 2026-06-19

金蝶应付款管理 = 应收款管理的供应商侧镜像（核销引擎 writeoff_link/writeoff_scheme 已在 v6w7x8y9 建好，
biz_type=AP 直接复用，本迁移不再建）。本迁移：

1. 扩 accounts_payable（doc_type ACCOUNTS_PAYABLE）：把精简存根补成金蝶应付单
   （单号/立账类型[暂估/业务应付]/业务日期/付款条件/采购员/采购组织/结算组织/价外税开关/先到票后入库/
   已核销额/核销状态/本位币双金额/凭证回链）。新增列均 nullable / server_default → 存量行兼容。
2. 新子表 ap_bill_line 应付单明细（物料×计价数量×单价×税率组×不含税/税额/价税合计）。
3. 新子表 ap_payment_plan_line 应付单付款计划（到期日/比例/金额）。
4. 新表 ap_payment 付款单（doc_type AP_PAYMENT）：供应商/币别/付款日期/结算方式/银行账户/金额/
   付款用途/是否预付/已核销额/状态。

引擎五条不破坏：均为扩展点（扩列 + 新表 + 新 doc_type + 新版 WorkflowDefinition）；核心三件零 diff。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "w7x8y9z0"
down_revision: Union[str, Sequence[str], None] = "v6w7x8y9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _audit_cols():
    """AuditMixin 公共列（对齐 v6w7x8y9 风格）。"""
    return [
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("company.id"), nullable=False, index=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    ]


def upgrade() -> None:
    # === 1. 扩 accounts_payable：金蝶应付单头字段（新增列均 nullable / 带 default）===
    op.add_column("accounts_payable", sa.Column("voucher_id", sa.Integer(), sa.ForeignKey("voucher.id"), nullable=True))
    op.add_column("accounts_payable", sa.Column("settlement_batch_no", sa.String(50), server_default=""))
    op.add_column("accounts_payable", sa.Column("bill_number", sa.String(40), server_default=""))
    op.add_column("accounts_payable", sa.Column("bill_type", sa.String(20), server_default="BUSINESS_AP"))
    op.add_column("accounts_payable", sa.Column("bill_date", sa.Date(), nullable=True))
    op.add_column("accounts_payable", sa.Column("base_currency", sa.String(3), server_default=""))
    op.add_column("accounts_payable", sa.Column("base_amount", sa.Numeric(16, 2), nullable=True))
    op.add_column("accounts_payable", sa.Column("payment_terms_text", sa.String(100), server_default=""))
    op.add_column("accounts_payable", sa.Column("purchaser_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True))
    op.add_column("accounts_payable", sa.Column("purchase_org_id", sa.Integer(), sa.ForeignKey("company.id"), nullable=True))
    op.add_column("accounts_payable", sa.Column("settle_org_id", sa.Integer(), sa.ForeignKey("company.id"), nullable=True))
    op.add_column("accounts_payable", sa.Column("purchase_dept", sa.String(50), server_default=""))
    op.add_column("accounts_payable", sa.Column("is_tax_included", sa.Boolean(), server_default=sa.text("false")))
    op.add_column("accounts_payable", sa.Column("is_price_tax_inclusive", sa.Boolean(), server_default=sa.text("false")))
    op.add_column("accounts_payable", sa.Column("is_goods_first", sa.Boolean(), server_default=sa.text("false")))
    op.add_column("accounts_payable", sa.Column("tax_amount", sa.Numeric(16, 2), server_default="0"))
    op.add_column("accounts_payable", sa.Column("untaxed_amount", sa.Numeric(16, 2), server_default="0"))
    op.add_column("accounts_payable", sa.Column("written_off_amount", sa.Numeric(16, 2), server_default="0"))
    op.add_column("accounts_payable", sa.Column("writeoff_status", sa.String(15), server_default="UNVERIFIED"))
    op.add_column("accounts_payable", sa.Column("remark", sa.Text(), server_default=""))
    op.create_index("ix_accounts_payable_bill_number", "accounts_payable", ["bill_number"])
    op.create_unique_constraint(
        "ux_accounts_payable_bill_number", "accounts_payable", ["company_id", "bill_number"])

    # === 2. 应付单明细子表 ap_bill_line（FK → accounts_payable / material / purchase_order_line）===
    op.create_table(
        "ap_bill_line",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("accounts_payable_id", sa.Integer(), sa.ForeignKey("accounts_payable.id"), nullable=False, index=True),
        sa.Column("line_number", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("material_id", sa.Integer(), sa.ForeignKey("material.id"), nullable=True),
        sa.Column("material_code", sa.String(50), server_default=""),
        sa.Column("material_name", sa.String(300), server_default=""),
        sa.Column("purchase_order_line_id", sa.Integer(), sa.ForeignKey("purchase_order_line.id"), nullable=True),
        sa.Column("quantity", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("uom", sa.String(20), server_default=""),
        sa.Column("unit_price", sa.Numeric(12, 4), nullable=False, server_default="0"),
        sa.Column("tax_rate_group", sa.String(30), server_default=""),
        sa.Column("tax_rate", sa.Numeric(5, 2), server_default="0"),
        sa.Column("untaxed_amount", sa.Numeric(16, 2), server_default="0"),
        sa.Column("tax_amount", sa.Numeric(16, 2), server_default="0"),
        sa.Column("amount", sa.Numeric(16, 2), server_default="0"),
        sa.Column("remark", sa.String(200), server_default=""),
        sa.UniqueConstraint("accounts_payable_id", "line_number", name="ux_ap_bill_line"),
    )

    # === 3. 应付单付款计划子表 ap_payment_plan_line（FK → accounts_payable）===
    op.create_table(
        "ap_payment_plan_line",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("accounts_payable_id", sa.Integer(), sa.ForeignKey("accounts_payable.id"), nullable=False, index=True),
        sa.Column("line_number", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("ratio", sa.Numeric(7, 4), server_default="0"),
        sa.Column("plan_amount", sa.Numeric(16, 2), server_default="0"),
        sa.Column("paid_amount", sa.Numeric(16, 2), server_default="0"),
        sa.Column("remark", sa.String(200), server_default=""),
        sa.UniqueConstraint("accounts_payable_id", "line_number", name="ux_ap_payment_plan_line"),
    )

    # === 4. 付款单 ap_payment（doc_type AP_PAYMENT；FK → supplier / settlement_method / voucher）===
    op.create_table(
        "ap_payment",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_audit_cols(),
        sa.Column("payment_number", sa.String(40), nullable=False, index=True),
        sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("supplier.id"), nullable=True),
        sa.Column("payment_date", sa.Date(), nullable=True),
        sa.Column("currency", sa.String(3), server_default=""),
        sa.Column("exchange_rate", sa.Numeric(12, 6), server_default="1"),
        sa.Column("base_currency", sa.String(3), server_default=""),
        sa.Column("base_amount", sa.Numeric(16, 2), nullable=True),
        sa.Column("amount", sa.Numeric(16, 2), nullable=False, server_default="0"),
        sa.Column("settlement_method_id", sa.Integer(), sa.ForeignKey("settlement_method.id"), nullable=True),
        sa.Column("bank_account", sa.String(50), server_default=""),
        sa.Column("payee_name", sa.String(100), server_default=""),
        sa.Column("payment_purpose", sa.String(50), server_default=""),
        sa.Column("is_advance", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("voucher_id", sa.Integer(), sa.ForeignKey("voucher.id"), nullable=True),
        sa.Column("written_off_amount", sa.Numeric(16, 2), server_default="0"),
        sa.Column("writeoff_status", sa.String(15), server_default="UNVERIFIED"),
        sa.Column("status", sa.String(30), server_default="DRAFT"),
        sa.Column("remark", sa.Text(), server_default=""),
        sa.UniqueConstraint("company_id", "payment_number", name="ux_ap_payment_number"),
    )


def downgrade() -> None:
    op.drop_table("ap_payment")
    op.drop_table("ap_payment_plan_line")
    op.drop_table("ap_bill_line")
    op.drop_constraint("ux_accounts_payable_bill_number", "accounts_payable", type_="unique")
    op.drop_index("ix_accounts_payable_bill_number", table_name="accounts_payable")
    for col in (
        "remark", "writeoff_status", "written_off_amount", "untaxed_amount", "tax_amount",
        "is_goods_first", "is_price_tax_inclusive", "is_tax_included", "purchase_dept",
        "settle_org_id", "purchase_org_id", "purchaser_id", "payment_terms_text",
        "base_amount", "base_currency", "bill_date", "bill_type", "bill_number",
        "settlement_batch_no", "voucher_id",
    ):
        op.drop_column("accounts_payable", col)
