"""rename agent_log.agent_id to agent_type

Revision ID: e5f6a7b8
Revises: d4e5f6a7
Create Date: 2026-04-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e5f6a7b8"
down_revision: Union[str, None] = "d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "agent_log",
        "agent_id",
        new_column_name="agent_type",
        existing_type=sa.String(length=50),
        type_=sa.String(length=20),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "agent_log",
        "agent_type",
        new_column_name="agent_id",
        existing_type=sa.String(length=20),
        type_=sa.String(length=50),
        existing_nullable=False,
    )
