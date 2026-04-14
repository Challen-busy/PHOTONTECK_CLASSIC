"""centralize node prompts in knowledge base

将节点描述从 workflow_transition.agent_prompt 迁移到 knowledge_entry。
knowledge_entry 成为业务逻辑的单一来源。

Revision ID: a1b2c3d4
Revises: 695b66f90ab0
Create Date: 2026-04-13 00:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'a1b2c3d4'
down_revision: Union[str, Sequence[str], None] = '695b66f90ab0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # knowledge_entry: 加节点定位字段
    op.add_column('knowledge_entry', sa.Column('doc_type', sa.String(length=30), nullable=True))
    op.add_column('knowledge_entry', sa.Column('state_code', sa.String(length=30), nullable=True))
    op.create_index('ix_knowledge_entry_doc_type', 'knowledge_entry', ['doc_type'])
    op.create_index('ix_knowledge_entry_state_code', 'knowledge_entry', ['state_code'])

    # 把 workflow_transition.agent_prompt 内容迁到 knowledge_entry
    op.execute("""
        INSERT INTO knowledge_entry (entry_type, title, content, doc_type, state_code, applicable_doc_types, is_active)
        SELECT
            'NODE',
            wd.doc_type || '::' || wt.from_state || '::' || wt.name,
            wt.agent_prompt,
            wd.doc_type,
            wt.from_state,
            to_jsonb(ARRAY[wd.doc_type]::text[]),
            TRUE
        FROM workflow_transition wt
        JOIN workflow_definition wd ON wd.id = wt.workflow_id
        WHERE wt.agent_prompt IS NOT NULL AND wt.agent_prompt <> ''
    """)

    # 删掉 agent_prompt 列
    op.drop_column('workflow_transition', 'agent_prompt')


def downgrade() -> None:
    op.add_column('workflow_transition', sa.Column('agent_prompt', sa.Text(), nullable=True))
    op.drop_index('ix_knowledge_entry_state_code', table_name='knowledge_entry')
    op.drop_index('ix_knowledge_entry_doc_type', table_name='knowledge_entry')
    op.drop_column('knowledge_entry', 'state_code')
    op.drop_column('knowledge_entry', 'doc_type')
