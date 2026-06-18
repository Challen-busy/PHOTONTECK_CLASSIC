"""总账·第一波（finance-gl）记账核心闭环：凭证字/辅助核算/现金流量项目主数据
+ 凭证双金额(本位币)/审核·出纳复核·红冲回链列 + 分录辅助核算/现金流量/结算列。

Revision ID: q1r2s3t4
Revises: p0q1r2s3
Create Date: 2026-06-18

总账·第一波（PRD 自研财务 ERP，录音+v2 PRD+金蝶逆向）全靠扩展点落地，引擎五条不破坏：
- 新主数据表 voucher_word（凭证字 记/收/付/转）、auxiliary_dimension（辅助核算维度）、
  cashflow_item（现金流量项目）：均 __queryable__ 主数据，company_id 隔离 + (company_id,code) 唯一。
- voucher 加列：voucher_word_id（凭证字）、audited_by_id/at（审核）、reviewed_by_id/at（出纳复核）、
  reversed_voucher_id/reversal_type/is_reversed（红冲回链，无蓝冲）。
- voucher_entry 加列：base_debit/base_credit（本位币=原币×汇率，过账与平衡校验只认本位币；
  存量行回填为原币值）、aux_party_type/id + aux_dept_id/aux_project_id（辅助核算）、
  cashflow_item_id（现金流量项目 FK）、settlement_method/settlement_no（资金类结算）。
- 过账/反过账/借贷平衡/期间锁/职责分离/红冲 = services/finance_posting.py 注册扩展点
  （@register_transition_effect/@register_transition_validator/@register_command），
  不动 execute_transition / 命令框架 / registry 核心语义。
- AccountingPeriod.status 值层加 LOCKED（OPEN→LOCKED→CLOSED）语义，无 schema 变更（仍 String(10)）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "q1r2s3t4"
down_revision: Union[str, Sequence[str], None] = "p0q1r2s3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # === 凭证字主数据（voucher.voucher_word_id 引用它，先建）===
    op.create_table(
        "voucher_word",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("company.id"), nullable=False),
        sa.Column("code", sa.String(10), nullable=False),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("restrict_multi_dc", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
        sa.UniqueConstraint("company_id", "code", name="ux_voucher_word_company_code"),
    )

    # === 辅助核算维度主数据 ===
    op.create_table(
        "auxiliary_dimension",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("company.id"), nullable=False),
        sa.Column("code", sa.String(30), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
        sa.UniqueConstraint("company_id", "code", name="ux_auxiliary_dimension_company_code"),
    )

    # === 现金流量项目主数据（voucher_entry.cashflow_item_id 引用它，先建）===
    op.create_table(
        "cashflow_item",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("company.id"), nullable=False),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("parent_id", sa.Integer(), sa.ForeignKey("cashflow_item.id"), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
        sa.UniqueConstraint("company_id", "code", name="ux_cashflow_item_company_code"),
    )

    # === voucher 加列：凭证字 + 审核/出纳复核/红冲回链 ===
    op.add_column("voucher", sa.Column("voucher_word_id", sa.Integer(), sa.ForeignKey("voucher_word.id"), nullable=True))
    op.add_column("voucher", sa.Column("audited_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True))
    op.add_column("voucher", sa.Column("audited_at", sa.DateTime(), nullable=True))
    op.add_column("voucher", sa.Column("reviewed_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True))
    op.add_column("voucher", sa.Column("reviewed_at", sa.DateTime(), nullable=True))
    op.add_column("voucher", sa.Column("reversed_voucher_id", sa.Integer(), sa.ForeignKey("voucher.id"), nullable=True))
    op.add_column("voucher", sa.Column("reversal_type", sa.String(10), nullable=True))
    op.add_column("voucher", sa.Column("is_reversed", sa.Boolean(), server_default=sa.text("false")))

    # === voucher_entry 加列：本位币双金额 + 辅助核算 + 现金流量 + 结算 ===
    op.add_column("voucher_entry", sa.Column("base_debit", sa.Numeric(16, 2), server_default="0"))
    op.add_column("voucher_entry", sa.Column("base_credit", sa.Numeric(16, 2), server_default="0"))
    op.add_column("voucher_entry", sa.Column("aux_party_type", sa.String(20), nullable=True))
    op.add_column("voucher_entry", sa.Column("aux_party_id", sa.Integer(), nullable=True))
    op.add_column("voucher_entry", sa.Column("aux_dept_id", sa.Integer(), nullable=True))
    op.add_column("voucher_entry", sa.Column("aux_project_id", sa.Integer(), nullable=True))
    op.add_column("voucher_entry", sa.Column("cashflow_item_id", sa.Integer(), sa.ForeignKey("cashflow_item.id"), nullable=True))
    op.add_column("voucher_entry", sa.Column("settlement_method", sa.String(20), server_default=""))
    op.add_column("voucher_entry", sa.Column("settlement_no", sa.String(50), server_default=""))

    # 存量行 base_* 回填为原币值（本币记账 rate=1 时本位币=原币；外币存量按当前 debit/credit 视为已折本币兜底）。
    op.execute("UPDATE voucher_entry SET base_debit = debit, base_credit = credit "
               "WHERE base_debit = 0 AND base_credit = 0 AND (debit <> 0 OR credit <> 0)")


def downgrade() -> None:
    op.drop_column("voucher_entry", "settlement_no")
    op.drop_column("voucher_entry", "settlement_method")
    op.drop_column("voucher_entry", "cashflow_item_id")
    op.drop_column("voucher_entry", "aux_project_id")
    op.drop_column("voucher_entry", "aux_dept_id")
    op.drop_column("voucher_entry", "aux_party_id")
    op.drop_column("voucher_entry", "aux_party_type")
    op.drop_column("voucher_entry", "base_credit")
    op.drop_column("voucher_entry", "base_debit")

    op.drop_column("voucher", "is_reversed")
    op.drop_column("voucher", "reversal_type")
    op.drop_column("voucher", "reversed_voucher_id")
    op.drop_column("voucher", "reviewed_at")
    op.drop_column("voucher", "reviewed_by_id")
    op.drop_column("voucher", "audited_at")
    op.drop_column("voucher", "audited_by_id")
    op.drop_column("voucher", "voucher_word_id")

    op.drop_table("cashflow_item")
    op.drop_table("auxiliary_dimension")
    op.drop_table("voucher_word")
