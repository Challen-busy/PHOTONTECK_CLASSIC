"""AR 业务字段 + 应收票据/银行收款/核销明细三张新表

Revision ID: d5e6f7a8
Revises: c9d0e1f2
Create Date: 2026-04-16

应收款流程改为 12 节点后，补齐业务字段：
- accounts_receivable 加 contract_id / voucher_id / settlement_batch_no
- customer_credit 加 credit_period_days / credit_rating
- 新建 notes_receivable / bank_receipt / ar_settlement
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d5e6f7a8"
down_revision: Union[str, None] = "c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. accounts_receivable 加字段
    op.add_column("accounts_receivable", sa.Column("contract_id", sa.Integer(), nullable=True))
    op.add_column("accounts_receivable", sa.Column("voucher_id", sa.Integer(), nullable=True))
    op.add_column("accounts_receivable", sa.Column("settlement_batch_no", sa.String(length=50), server_default="", nullable=True))
    op.create_foreign_key("fk_ar_contract", "accounts_receivable", "framework_contract", ["contract_id"], ["id"])
    op.create_foreign_key("fk_ar_voucher", "accounts_receivable", "voucher", ["voucher_id"], ["id"])
    op.create_index("ix_accounts_receivable_settlement_batch_no", "accounts_receivable", ["settlement_batch_no"])

    # 2. customer_credit 加字段
    op.add_column("customer_credit", sa.Column("credit_period_days", sa.Integer(), server_default="30", nullable=True))
    op.add_column("customer_credit", sa.Column("credit_rating", sa.String(length=10), server_default="", nullable=True))

    # 3. notes_receivable 应收票据
    op.create_table(
        "notes_receivable",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("company.id"), nullable=False, index=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customer.id"), nullable=True),
        sa.Column("note_number", sa.String(length=50), server_default="", index=True),
        sa.Column("note_type", sa.String(length=20), server_default="COMMERCIAL"),
        sa.Column("amount", sa.Numeric(16, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="CNY"),
        sa.Column("issue_date", sa.Date(), nullable=True),
        sa.Column("maturity_date", sa.Date(), nullable=True),
        sa.Column("drawer", sa.String(length=100), server_default=""),
        sa.Column("acceptor", sa.String(length=100), server_default=""),
        sa.Column("status", sa.String(length=20), server_default="HELD"),
    )

    # 4. bank_receipt 银行收款流水
    op.create_table(
        "bank_receipt",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("company.id"), nullable=False, index=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customer.id"), nullable=True),
        sa.Column("receipt_number", sa.String(length=50), server_default="", index=True),
        sa.Column("bank_account", sa.String(length=50), server_default=""),
        sa.Column("amount", sa.Numeric(16, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="CNY"),
        sa.Column("receipt_date", sa.Date(), index=True),
        sa.Column("payer_name", sa.String(length=100), server_default=""),
        sa.Column("remark", sa.Text(), server_default=""),
        sa.Column("status", sa.String(length=20), server_default="UNALLOCATED"),
    )

    # 5. ar_settlement 应收款核销明细
    op.create_table(
        "ar_settlement",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("company.id"), nullable=False, index=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column("batch_no", sa.String(length=50), server_default="", index=True),
        sa.Column("ar_id", sa.Integer(), sa.ForeignKey("accounts_receivable.id"), nullable=False),
        sa.Column("bank_receipt_id", sa.Integer(), sa.ForeignKey("bank_receipt.id"), nullable=True),
        sa.Column("note_id", sa.Integer(), sa.ForeignKey("notes_receivable.id"), nullable=True),
        sa.Column("settle_amount", sa.Numeric(16, 2), nullable=False),
        sa.Column("settle_date", sa.Date(), nullable=True),
        sa.Column("remark", sa.Text(), server_default=""),
    )


def downgrade() -> None:
    op.drop_table("ar_settlement")
    op.drop_table("bank_receipt")
    op.drop_table("notes_receivable")

    op.drop_column("customer_credit", "credit_rating")
    op.drop_column("customer_credit", "credit_period_days")

    op.drop_index("ix_accounts_receivable_settlement_batch_no", table_name="accounts_receivable")
    op.drop_constraint("fk_ar_voucher", "accounts_receivable", type_="foreignkey")
    op.drop_constraint("fk_ar_contract", "accounts_receivable", type_="foreignkey")
    op.drop_column("accounts_receivable", "settlement_batch_no")
    op.drop_column("accounts_receivable", "voucher_id")
    op.drop_column("accounts_receivable", "contract_id")
