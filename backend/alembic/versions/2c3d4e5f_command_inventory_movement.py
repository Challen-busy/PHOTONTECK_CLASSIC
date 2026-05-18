"""command log and inventory movement

Revision ID: 2c3d4e5f
Revises: 1b2c3d4e
Create Date: 2026-05-03
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "2c3d4e5f"
down_revision: Union[str, None] = "1b2c3d4e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "command_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("command_name", sa.String(length=80), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=True),
        sa.Column("actor_id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=True),
        sa.Column("request_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("result_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["actor_id"], ["user_account.id"]),
        sa.ForeignKeyConstraint(["company_id"], ["company.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_command_log_actor_id", "command_log", ["actor_id"])
    op.create_index("ix_command_log_command_name", "command_log", ["command_name"])
    op.create_index("ix_command_log_company_id", "command_log", ["company_id"])
    op.create_index("ix_command_log_created_at", "command_log", ["created_at"])
    op.create_index("ix_command_log_name_created", "command_log", ["command_name", "created_at"])
    op.create_index(
        "ux_command_log_name_key_active",
        "command_log",
        ["command_name", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL AND status IN ('RUNNING', 'SUCCESS')"),
    )
    op.create_index("ix_command_log_status", "command_log", ["status"])

    op.create_table(
        "inventory_movement",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("command_log_id", sa.Integer(), nullable=True),
        sa.Column("movement_type", sa.String(length=30), nullable=False),
        sa.Column("material_id", sa.Integer(), nullable=False),
        sa.Column("warehouse_id", sa.Integer(), nullable=True),
        sa.Column("inventory_id", sa.Integer(), nullable=True),
        sa.Column("quantity_delta", sa.Numeric(precision=16, scale=2), nullable=True),
        sa.Column("reserved_delta", sa.Numeric(precision=16, scale=2), nullable=True),
        sa.Column("unit_cost", sa.Numeric(precision=16, scale=4), nullable=True),
        sa.Column("source_doc_type", sa.String(length=30), nullable=True),
        sa.Column("source_doc_id", sa.BigInteger(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["command_log_id"], ["command_log.id"]),
        sa.ForeignKeyConstraint(["company_id"], ["company.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["user_account.id"]),
        sa.ForeignKeyConstraint(["inventory_id"], ["inventory.id"]),
        sa.ForeignKeyConstraint(["material_id"], ["material.id"]),
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouse.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_inventory_movement_command_log_id", "inventory_movement", ["command_log_id"])
    op.create_index("ix_inventory_movement_company_id", "inventory_movement", ["company_id"])
    op.create_index("ix_inventory_movement_created_at", "inventory_movement", ["created_at"])
    op.create_index("ix_inventory_movement_inventory_id", "inventory_movement", ["inventory_id"])
    op.create_index("ix_inventory_movement_material_created", "inventory_movement", ["company_id", "material_id", "created_at"])
    op.create_index("ix_inventory_movement_material_id", "inventory_movement", ["material_id"])
    op.create_index("ix_inventory_movement_movement_type", "inventory_movement", ["movement_type"])
    op.create_index("ix_inventory_movement_source", "inventory_movement", ["source_doc_type", "source_doc_id"])
    op.create_index("ix_inventory_movement_source_doc_id", "inventory_movement", ["source_doc_id"])
    op.create_index("ix_inventory_movement_source_doc_type", "inventory_movement", ["source_doc_type"])
    op.create_index("ix_inventory_movement_warehouse_id", "inventory_movement", ["warehouse_id"])


def downgrade() -> None:
    op.drop_index("ix_inventory_movement_warehouse_id", table_name="inventory_movement")
    op.drop_index("ix_inventory_movement_source_doc_type", table_name="inventory_movement")
    op.drop_index("ix_inventory_movement_source_doc_id", table_name="inventory_movement")
    op.drop_index("ix_inventory_movement_source", table_name="inventory_movement")
    op.drop_index("ix_inventory_movement_movement_type", table_name="inventory_movement")
    op.drop_index("ix_inventory_movement_material_id", table_name="inventory_movement")
    op.drop_index("ix_inventory_movement_material_created", table_name="inventory_movement")
    op.drop_index("ix_inventory_movement_inventory_id", table_name="inventory_movement")
    op.drop_index("ix_inventory_movement_created_at", table_name="inventory_movement")
    op.drop_index("ix_inventory_movement_company_id", table_name="inventory_movement")
    op.drop_index("ix_inventory_movement_command_log_id", table_name="inventory_movement")
    op.drop_table("inventory_movement")

    op.drop_index("ix_command_log_status", table_name="command_log")
    op.drop_index("ux_command_log_name_key_active", table_name="command_log")
    op.drop_index("ix_command_log_name_created", table_name="command_log")
    op.drop_index("ix_command_log_created_at", table_name="command_log")
    op.drop_index("ix_command_log_company_id", table_name="command_log")
    op.drop_index("ix_command_log_command_name", table_name="command_log")
    op.drop_index("ix_command_log_actor_id", table_name="command_log")
    op.drop_table("command_log")
