"""add edge_layout

Revision ID: f3d4e5f6
Revises: f2c3d4e5
Create Date: 2026-04-26 13:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "f2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "workflow_definition",
        sa.Column("edge_layout", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workflow_definition", "edge_layout")
