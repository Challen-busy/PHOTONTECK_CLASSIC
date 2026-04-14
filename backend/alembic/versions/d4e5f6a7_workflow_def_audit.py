"""workflow definition audit log

记录所有对流程定义的改动（创建/删除/Fork/上线/停用/编辑/危险修改）。

Revision ID: d4e5f6a7
Revises: c3d4e5f6
Create Date: 2026-04-14 00:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'd4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('workflow_def_audit',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('workflow_id', sa.Integer(), nullable=False),
        sa.Column('change_type', sa.String(length=30), nullable=False),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('before_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('after_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('danger_mode', sa.Boolean(), server_default=sa.text('false'), nullable=True),
        sa.Column('changed_by_id', sa.Integer(), nullable=False),
        sa.Column('timestamp', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['workflow_id'], ['workflow_definition.id']),
        sa.ForeignKeyConstraint(['changed_by_id'], ['user_account.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_workflow_def_audit_workflow_id', 'workflow_def_audit', ['workflow_id'])
    op.create_index('ix_workflow_def_audit_timestamp', 'workflow_def_audit', ['timestamp'])


def downgrade() -> None:
    op.drop_index('ix_workflow_def_audit_timestamp', table_name='workflow_def_audit')
    op.drop_index('ix_workflow_def_audit_workflow_id', table_name='workflow_def_audit')
    op.drop_table('workflow_def_audit')
