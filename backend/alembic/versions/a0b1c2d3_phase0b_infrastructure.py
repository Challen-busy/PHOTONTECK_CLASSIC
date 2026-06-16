"""phase0b backend infrastructure: numbering / cosign / kingdee outbox / notification / config audit

Revision ID: a0b1c2d3
Revises: 5fe25ee326e8
Create Date: 2026-06-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a0b1c2d3"
down_revision: Union[str, Sequence[str], None] = "5fe25ee326e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---------- numbering_rule ----------
    op.create_table(
        "numbering_rule",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("doc_type", sa.String(length=40), nullable=False),
        sa.Column("prefix", sa.String(length=20), nullable=False, server_default=""),
        sa.Column("reset_period", sa.String(length=10), nullable=False, server_default="MONTH"),
        sa.Column("seq_padding", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("separator", sa.String(length=5), nullable=False, server_default="-"),
        sa.Column("period_format", sa.String(length=10), nullable=False, server_default="%y%m"),
        sa.Column("current_period", sa.String(length=10), nullable=False, server_default=""),
        sa.Column("current_seq", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["company.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["user_account.id"]),
        sa.ForeignKeyConstraint(["updated_by_id"], ["user_account.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "doc_type", name="ux_numbering_rule_company_doctype"),
    )
    op.create_index("ix_numbering_rule_company_id", "numbering_rule", ["company_id"])
    op.create_index("ix_numbering_rule_doc_type", "numbering_rule", ["doc_type"])

    # ---------- cosign_line ----------
    op.create_table(
        "cosign_line",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("doc_type", sa.String(length=40), nullable=False),
        sa.Column("doc_id", sa.BigInteger(), nullable=False),
        sa.Column("cosign_group", sa.String(length=40), nullable=False, server_default="DEFAULT"),
        sa.Column("required_role", sa.String(length=30), nullable=False),
        sa.Column("decision", sa.String(length=10), nullable=False, server_default="PENDING"),
        sa.Column("signed_by_id", sa.Integer(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("signed_at", sa.DateTime(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["company.id"]),
        sa.ForeignKeyConstraint(["signed_by_id"], ["user_account.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["user_account.id"]),
        sa.ForeignKeyConstraint(["updated_by_id"], ["user_account.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("doc_type", "doc_id", "cosign_group", "required_role", name="ux_cosign_line_one_per_role"),
    )
    op.create_index("ix_cosign_line_company_id", "cosign_line", ["company_id"])
    op.create_index("ix_cosign_line_doc_type", "cosign_line", ["doc_type"])
    op.create_index("ix_cosign_line_doc_id", "cosign_line", ["doc_id"])
    op.create_index("ix_cosign_line_doc", "cosign_line", ["doc_type", "doc_id", "cosign_group"])

    # ---------- kingdee_outbox ----------
    op.create_table(
        "kingdee_outbox",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("doc_type", sa.String(length=40), nullable=False),
        sa.Column("biz_no", sa.String(length=80), nullable=False),
        sa.Column("business_doc_type", sa.String(length=40), nullable=True),
        sa.Column("business_doc_id", sa.BigInteger(), nullable=True),
        sa.Column("trigger_state", sa.String(length=30), nullable=True),
        sa.Column("form_id", sa.String(length=40), nullable=True),
        sa.Column("request_url", sa.String(length=120), nullable=True),
        sa.Column("kingdee_bill_no", sa.String(length=80), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="RUNNING"),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("receipt", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("command_log_id", sa.Integer(), nullable=True),
        sa.Column("retried_from_id", sa.Integer(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["company.id"]),
        sa.ForeignKeyConstraint(["command_log_id"], ["command_log.id"]),
        sa.ForeignKeyConstraint(["retried_from_id"], ["kingdee_outbox.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["user_account.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_kingdee_outbox_company_id", "kingdee_outbox", ["company_id"])
    op.create_index("ix_kingdee_outbox_doc_type", "kingdee_outbox", ["doc_type"])
    op.create_index("ix_kingdee_outbox_biz_no", "kingdee_outbox", ["biz_no"])
    op.create_index("ix_kingdee_outbox_status", "kingdee_outbox", ["status"])
    op.create_index("ix_kingdee_outbox_command_log_id", "kingdee_outbox", ["command_log_id"])
    op.create_index("ix_kingdee_outbox_created_at", "kingdee_outbox", ["created_at"])
    op.create_index("ix_kingdee_outbox_company_status", "kingdee_outbox", ["company_id", "status"])
    op.create_index("ix_kingdee_outbox_biz", "kingdee_outbox", ["doc_type", "biz_no"])

    # ---------- notification ----------
    op.create_table(
        "notification",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("recipient_id", sa.Integer(), nullable=True),
        sa.Column("recipient_role", sa.String(length=30), nullable=True, server_default=""),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("severity", sa.String(length=10), nullable=False, server_default="INFO"),
        sa.Column("source_doc_type", sa.String(length=40), nullable=True, server_default=""),
        sa.Column("source_doc_id", sa.BigInteger(), nullable=True),
        sa.Column("dedup_key", sa.String(length=160), nullable=True),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column("email_status", sa.String(length=20), nullable=False, server_default="NONE"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["company.id"]),
        sa.ForeignKeyConstraint(["recipient_id"], ["user_account.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedup_key", name="ux_notification_dedup"),
    )
    op.create_index("ix_notification_company_id", "notification", ["company_id"])
    op.create_index("ix_notification_recipient_id", "notification", ["recipient_id"])
    op.create_index("ix_notification_recipient_role", "notification", ["recipient_role"])
    op.create_index("ix_notification_category", "notification", ["category"])
    op.create_index("ix_notification_source_doc_type", "notification", ["source_doc_type"])
    op.create_index("ix_notification_dedup_key", "notification", ["dedup_key"])
    op.create_index("ix_notification_is_read", "notification", ["is_read"])
    op.create_index("ix_notification_created_at", "notification", ["created_at"])
    op.create_index("ix_notification_recipient_unread", "notification", ["recipient_id", "is_read"])

    # ---------- config_audit ----------
    op.create_table(
        "config_audit",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("object_type", sa.String(length=40), nullable=False),
        sa.Column("object_id", sa.String(length=60), nullable=True),
        sa.Column("change_type", sa.String(length=30), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("before_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("company_id", sa.Integer(), nullable=True),
        sa.Column("changed_by_id", sa.Integer(), nullable=False),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("timestamp", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["company.id"]),
        sa.ForeignKeyConstraint(["changed_by_id"], ["user_account.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_config_audit_object_type", "config_audit", ["object_type"])
    op.create_index("ix_config_audit_object_id", "config_audit", ["object_id"])
    op.create_index("ix_config_audit_company_id", "config_audit", ["company_id"])
    op.create_index("ix_config_audit_changed_by_id", "config_audit", ["changed_by_id"])
    op.create_index("ix_config_audit_timestamp", "config_audit", ["timestamp"])


def downgrade() -> None:
    op.drop_table("config_audit")
    op.drop_table("notification")
    op.drop_table("kingdee_outbox")
    op.drop_table("cosign_line")
    op.drop_table("numbering_rule")
