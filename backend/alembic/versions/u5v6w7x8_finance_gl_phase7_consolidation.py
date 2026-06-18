"""总账·第七波（finance-gl wave-7）合并报表（多账簿合并）：合并范围 + 成员子表 + 抵消分录 3 张新表

Revision ID: u5v6w7x8
Revises: t4u5v6w7
Create Date: 2026-06-18

合并报表「可手工合」（会计专家定调）→ 半自动：各成员公司单体报表汇总 + 折算 + 手工抵消分录调整。
靠 3 张新表落地，引擎五条不破坏：
- 配置主数据（均 AuditMixin + __queryable__ + __doc_types__，company_id 按主导/创建公司隔离）：
  consolidation_group 合并范围 / elimination_entry 抵消分录。
- 关联子表 consolidation_member 合并成员（跨公司：member_company_id 弱引用任一公司，故不随 group.company_id）。
- 唯一键：consolidation_group (company_id, code) / consolidation_member (group_id, member_company_id) /
  elimination_entry 无业务唯一键（同组同期同行可多笔抵消，按主键各自成行）。
- 建表顺序按 FK 依赖：consolidation_group 先，再 consolidation_member(→consolidation_group,→company) /
  elimination_entry(→consolidation_group)。
- 写仍走 execute_transition（MasterDataPage 唯一写入）；各 doc_type 的轻量单状态机 WorkflowDefinition
  由 scripts.seed_consolidation 种入；registry/workflow/commands 核心零 diff。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "u5v6w7x8"
down_revision: Union[str, Sequence[str], None] = "t4u5v6w7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _audit_cols():
    """AuditMixin 公共列（对齐现有主数据迁移风格，见 t4u5v6w7）。"""
    return [
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("company.id"), nullable=False, index=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    ]


def upgrade() -> None:
    # === 1. 合并范围 consolidation_group ===
    op.create_table(
        "consolidation_group",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_audit_cols(),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("presentation_currency", sa.String(3), nullable=False, server_default="CNY"),
        sa.Column("standard", sa.String(10), nullable=False, server_default="CAS"),
        sa.Column("description", sa.String(200), server_default=""),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
        sa.UniqueConstraint("company_id", "code", name="ux_consolidation_group_company_code"),
    )

    # === 2. 合并成员子表 consolidation_member（FK → consolidation_group / company；跨公司）===
    op.create_table(
        "consolidation_member",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("consolidation_group.id"), nullable=False, index=True),
        sa.Column("member_company_id", sa.Integer(), sa.ForeignKey("company.id"), nullable=False),
        sa.Column("ownership_pct", sa.Numeric(7, 4), nullable=False, server_default="100"),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
        sa.UniqueConstraint("group_id", "member_company_id", name="ux_consolidation_member"),
    )

    # === 3. 抵消分录 elimination_entry（FK → consolidation_group）===
    op.create_table(
        "elimination_entry",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_audit_cols(),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("consolidation_group.id"), nullable=False, index=True),
        sa.Column("period_year", sa.Integer(), nullable=False),
        sa.Column("period_number", sa.SmallInteger(), nullable=False),
        sa.Column("statement", sa.String(2), nullable=False, server_default="BS"),
        sa.Column("line_key", sa.String(50), server_default=""),
        sa.Column("account_code", sa.String(20), server_default=""),
        sa.Column("debit", sa.Numeric(16, 2), server_default="0"),
        sa.Column("credit", sa.Numeric(16, 2), server_default="0"),
        sa.Column("memo", sa.String(200), server_default=""),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
    )


def downgrade() -> None:
    op.drop_table("elimination_entry")
    op.drop_table("consolidation_member")
    op.drop_table("consolidation_group")
