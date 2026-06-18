"""总账·第二波（finance-gl wave-2）模块 C：业财映射规则 account_mapping_rule

Revision ID: r2s3t4u5
Revises: q1r2s3t4
Create Date: 2026-06-18

总账·第二波模块 C（业务单 → 凭证分录模板）全靠新表落地，引擎五条不破坏：
- 新主数据表 account_mapping_rule（AuditMixin + __queryable__，company_id 隔离）：
  一条 = 某业务单类型在某触发动作下、自动生成凭证第 line_seq 行分录的取数+科目规则。
  HK/CAS 准则差异（HK 6401=Selling expenses≠主营成本；CAS 6401=主营业务成本）按公司隔离落到
  各家自己的规则，业财 effect 按 company_id 取本家规则，不在代码里硬编码科目码。
- UNIQUE(company_id, source_doc_type, trigger_action, line_seq, effective_date)：同一 key 多版本
  按生效日切换。
- 模块 B（期末：过账→调汇→结转损益→结账）不需要新表，复用现有 Voucher / AccountBalance /
  AccountingPeriod.status（OPEN→LOCKED→CLOSED）。
- 写仍走 execute_transition / @register_* 扩展点，不动 registry / workflow / commands 核心语义。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "r2s3t4u5"
down_revision: Union[str, Sequence[str], None] = "q1r2s3t4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "account_mapping_rule",
        sa.Column("id", sa.Integer(), primary_key=True),
        # AuditMixin（对齐现有主数据风格）
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("company.id"), nullable=False, index=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
        # 业财映射规则字段
        sa.Column("source_doc_type", sa.String(30), nullable=False),
        sa.Column("trigger_action", sa.String(30), nullable=False),
        sa.Column("line_seq", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("dr_cr", sa.String(2), nullable=False),
        sa.Column("account_code", sa.String(20), server_default=""),
        sa.Column("account_source", sa.String(20), nullable=False, server_default="FIXED"),
        sa.Column("amount_formula", sa.String(200), server_default=""),
        sa.Column("tax_handling", sa.String(10), server_default="NONE"),
        sa.Column("memo_template", sa.String(200), server_default=""),
        sa.Column("date_source", sa.String(10), server_default="BIZ"),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("confirmed_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.UniqueConstraint(
            "company_id", "source_doc_type", "trigger_action", "line_seq", "effective_date",
            name="ux_account_mapping_rule_key",
        ),
    )


def downgrade() -> None:
    op.drop_table("account_mapping_rule")
