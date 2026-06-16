"""phase0c templates: label template engine + doc template engine

Revision ID: c1d2e3f4
Revises: b1c2d3e4
Create Date: 2026-06-16

段0c·标签模板引擎 + 单据模板引擎（PRD 09 §9.1/§9.2 + 标签模板规格逐客户 + 单据模板规格 PL/INV/送货单）。

- 扩 label_template（加 company_id/审计列/label_type/size_mm/qr_separator/qr_field_order/
  barcode_fields/orientation/status/is_active/notes）+ 唯一约束 + __doc_types__=LABEL_TEMPLATE。
- 新表 label_field_line（字段映射子表：标签字段→数据来源 + 顺序 + 是否渲条码/进二维码）。
- 新表 doc_template（PL/INV/送货单模板：客户×公司 + 盖章/回签标志）+ __doc_types__=DOC_TEMPLATE。
- 新表 doc_template_field_line（字段集子表：字段→来源 + 本地/出口切换 + 渲条码开关）。

引擎五条不破坏：只加列/加表，不动唯一写入路径（execute_transition / @register_command）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c1d2e3f4"
down_revision: Union[str, Sequence[str], None] = "b1c2d3e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ========== 扩 label_template：升级为标签模板引擎主表（__doc_types__=LABEL_TEMPLATE）==========
    # 加 company_id 带 server_default=1（既有无 label_template 数据；兜底首公司），随后保持 NOT NULL。
    op.add_column("label_template", sa.Column("company_id", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("label_template", sa.Column("created_by_id", sa.Integer(), nullable=True))
    op.add_column("label_template", sa.Column("updated_by_id", sa.Integer(), nullable=True))
    op.add_column("label_template", sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True))
    op.add_column("label_template", sa.Column("label_type", sa.String(length=20), nullable=True, server_default="PKG1"))
    op.add_column("label_template", sa.Column("size_mm", sa.String(length=20), nullable=True, server_default=""))
    op.add_column("label_template", sa.Column("orientation", sa.String(length=10), nullable=True, server_default="PORTRAIT"))
    op.add_column("label_template", sa.Column("qr_separator", sa.String(length=10), nullable=True, server_default=""))
    op.add_column("label_template", sa.Column("qr_field_order", sa.dialects.postgresql.JSONB(), nullable=True, server_default=sa.text("'[]'::jsonb")))
    op.add_column("label_template", sa.Column("barcode_fields", sa.dialects.postgresql.JSONB(), nullable=True, server_default=sa.text("'[]'::jsonb")))
    op.add_column("label_template", sa.Column("status", sa.String(length=15), nullable=True, server_default="ACTIVE"))
    op.add_column("label_template", sa.Column("is_active", sa.Boolean(), nullable=True, server_default=sa.text("true")))
    op.add_column("label_template", sa.Column("notes", sa.Text(), nullable=True, server_default=""))
    op.create_foreign_key("fk_label_template_company", "label_template", "company", ["company_id"], ["id"])
    op.create_foreign_key("fk_label_template_created_by", "label_template", "user_account", ["created_by_id"], ["id"])
    op.create_foreign_key("fk_label_template_updated_by", "label_template", "user_account", ["updated_by_id"], ["id"])
    op.create_index("ix_label_template_customer_id", "label_template", ["customer_id"])
    op.create_unique_constraint(
        "ux_label_template_company_cust_type", "label_template",
        ["company_id", "customer_id", "label_type"],
    )

    # ========== 新表：label_field_line（标签字段映射子表）==========
    op.create_table(
        "label_field_line",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("label_template_id", sa.Integer(), nullable=False),
        sa.Column("line_number", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("label_field_title", sa.String(length=100), nullable=False),
        sa.Column("source_type", sa.String(length=20), nullable=True, server_default="OUTBOUND"),
        sa.Column("source_field", sa.String(length=80), nullable=True, server_default=""),
        sa.Column("derive_expr", sa.String(length=200), nullable=True, server_default=""),
        sa.Column("const_value", sa.String(length=200), nullable=True, server_default=""),
        sa.Column("in_qr", sa.Boolean(), nullable=True, server_default=sa.text("false")),
        sa.Column("qr_order", sa.SmallInteger(), nullable=True),
        sa.Column("render_as_barcode", sa.Boolean(), nullable=True, server_default=sa.text("false")),
        sa.ForeignKeyConstraint(["label_template_id"], ["label_template.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("label_template_id", "line_number"),
    )
    op.create_index("ix_label_field_line_label_template_id", "label_field_line", ["label_template_id"])

    # ========== 新表：doc_template（PL/INV/送货单模板，__doc_types__=DOC_TEMPLATE）==========
    op.create_table(
        "doc_template",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("doc_kind", sa.String(length=20), nullable=True, server_default="PL"),
        sa.Column("region", sa.String(length=10), nullable=True, server_default="HK"),
        sa.Column("needs_stamp", sa.Boolean(), nullable=True, server_default=sa.text("false")),
        sa.Column("needs_countersign", sa.Boolean(), nullable=True, server_default=sa.text("false")),
        sa.Column("header_title", sa.Text(), nullable=True, server_default=""),
        sa.Column("bank_block", sa.Text(), nullable=True, server_default=""),
        sa.Column("render_html", sa.Text(), nullable=True, server_default=""),
        sa.Column("status", sa.String(length=15), nullable=True, server_default="ACTIVE"),
        sa.Column("is_active", sa.Boolean(), nullable=True, server_default=sa.text("true")),
        sa.Column("notes", sa.Text(), nullable=True, server_default=""),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["customer_id"], ["customer.id"]),
        sa.ForeignKeyConstraint(["company_id"], ["company.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["user_account.id"]),
        sa.ForeignKeyConstraint(["updated_by_id"], ["user_account.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_doc_template_company_kind", "doc_template", ["company_id", "doc_kind", "customer_id"])
    op.create_index("ix_doc_template_customer_id", "doc_template", ["customer_id"])

    # ========== 新表：doc_template_field_line（单据字段集子表）==========
    op.create_table(
        "doc_template_field_line",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("doc_template_id", sa.Integer(), nullable=False),
        sa.Column("line_number", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("doc_field_title", sa.String(length=100), nullable=False),
        sa.Column("source_field", sa.String(length=80), nullable=True, server_default=""),
        sa.Column("const_value", sa.String(length=200), nullable=True, server_default=""),
        sa.Column("is_variant_field", sa.Boolean(), nullable=True, server_default=sa.text("false")),
        sa.Column("variant_local", sa.String(length=80), nullable=True, server_default=""),
        sa.Column("variant_export", sa.String(length=80), nullable=True, server_default=""),
        sa.Column("render_as_barcode", sa.Boolean(), nullable=True, server_default=sa.text("false")),
        sa.ForeignKeyConstraint(["doc_template_id"], ["doc_template.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("doc_template_id", "line_number"),
    )
    op.create_index("ix_doc_template_field_line_doc_template_id", "doc_template_field_line", ["doc_template_id"])


def downgrade() -> None:
    op.drop_table("doc_template_field_line")
    op.drop_index("ix_doc_template_customer_id", table_name="doc_template")
    op.drop_index("ix_doc_template_company_kind", table_name="doc_template")
    op.drop_table("doc_template")
    op.drop_index("ix_label_field_line_label_template_id", table_name="label_field_line")
    op.drop_table("label_field_line")

    op.drop_constraint("ux_label_template_company_cust_type", "label_template", type_="unique")
    op.drop_index("ix_label_template_customer_id", table_name="label_template")
    op.drop_constraint("fk_label_template_updated_by", "label_template", type_="foreignkey")
    op.drop_constraint("fk_label_template_created_by", "label_template", type_="foreignkey")
    op.drop_constraint("fk_label_template_company", "label_template", type_="foreignkey")
    for col in (
        "notes", "is_active", "status", "barcode_fields", "qr_field_order", "qr_separator",
        "orientation", "size_mm", "label_type", "updated_at", "updated_by_id", "created_by_id",
        "company_id",
    ):
        op.drop_column("label_template", col)
