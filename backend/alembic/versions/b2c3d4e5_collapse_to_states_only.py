"""collapse workflow to states-only model

废除 WorkflowTransition 表。所有节点信息（roles/fields/description/agent_tools/custom_html/next）
直接放进 WorkflowDefinition.states JSONB。

KnowledgeEntry 也清理 doc_type/state_code 列（NODE 条目消失）。

Revision ID: b2c3d4e5
Revises: a1b2c3d4
Create Date: 2026-04-13 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b2c3d4e5'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 清掉 NODE 类型的知识条目
    op.execute("DELETE FROM knowledge_entry WHERE entry_type = 'NODE'")

    # 删 knowledge_entry 的节点定位列
    op.drop_index('ix_knowledge_entry_state_code', table_name='knowledge_entry')
    op.drop_index('ix_knowledge_entry_doc_type', table_name='knowledge_entry')
    op.drop_column('knowledge_entry', 'state_code')
    op.drop_column('knowledge_entry', 'doc_type')

    # 删 WorkflowTransition 表
    op.drop_table('workflow_transition')


def downgrade() -> None:
    # 不太可能回滚，但写一下
    op.create_table('workflow_transition',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('workflow_id', sa.Integer(), sa.ForeignKey('workflow_definition.id'), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('from_state', sa.String(30), nullable=False),
        sa.Column('to_state', sa.String(30), nullable=False),
        sa.Column('allowed_roles', sa.JSON(), nullable=True),
        sa.Column('editable_fields', sa.JSON(), nullable=True),
        sa.Column('conditions', sa.JSON(), nullable=True),
        sa.Column('auto_actions', sa.JSON(), nullable=True),
        sa.Column('related_data', sa.JSON(), nullable=True),
        sa.Column('custom_html', sa.Text(), nullable=True),
        sa.Column('agent_tools', sa.JSON(), nullable=True),
        sa.Column('sort_order', sa.SmallInteger(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
    )
    op.add_column('knowledge_entry', sa.Column('doc_type', sa.String(30), nullable=True))
    op.add_column('knowledge_entry', sa.Column('state_code', sa.String(30), nullable=True))
    op.create_index('ix_knowledge_entry_doc_type', 'knowledge_entry', ['doc_type'])
    op.create_index('ix_knowledge_entry_state_code', 'knowledge_entry', ['state_code'])
