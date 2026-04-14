"""workflow lifecycle: group_name + is_published

加流程分组和上线锁字段。

Revision ID: c3d4e5f6
Revises: b2c3d4e5
Create Date: 2026-04-13 23:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('workflow_definition',
        sa.Column('group_name', sa.String(length=50), nullable=True, server_default=''))
    op.add_column('workflow_definition',
        sa.Column('is_published', sa.Boolean(), nullable=True, server_default=sa.text('false')))
    op.create_index('ix_workflow_definition_group_name', 'workflow_definition', ['group_name'])


def downgrade() -> None:
    op.drop_index('ix_workflow_definition_group_name', table_name='workflow_definition')
    op.drop_column('workflow_definition', 'is_published')
    op.drop_column('workflow_definition', 'group_name')
