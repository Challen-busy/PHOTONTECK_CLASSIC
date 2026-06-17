"""phase4a: 报关域 — 报关单(进口/出口/退运) + 商品明细/费用子表 / 进出口证台账 / 物流轨迹

Revision ID: p0q1r2s3
Revises: o9p0q1r2
Create Date: 2026-06-17

段4a（PRD 06-报关）全新建域（引擎当前无任何报关脚手架）：
- customs_declaration 头（CUSTOMS_DECLARATION doc_type，direction=IMPORT/EXPORT/RE_EXPORT）
  + customs_declaration_line（商品明细子表，合规五件套 hs_code_cn/origin_country/cn_name/eccn）
  + customs_fee_line（费用子表，报关费分摊回写到岸成本）。
  状态机 DRAFT→SUBMITTED→RELEASED→CLOSED + REJECTED 重申报（WorkflowDefinition states JSONB，seed_phase1）。
  ★合规五件套申报硬拦 + 香港退香港一致性 = services/customs validator（注册扩展点，引擎核心零 diff）。
- customs_license 进出口证台账（__queryable__ 主数据，不挂 doc_type）+ 效期预警（前端按 valid_to 着色）。
- shipment_tracking 头 + shipment_tracking_node 子表（__queryable__ 轨迹台账，非审批单，同 kingdee_outbox 范式）；
  顺丰物流 API 框架壳（FeatureFlag SF_EXPRESS_SYNC 默认 OFF + services/customs_commands 命令壳）。

引擎五条不破坏：仅加表 + WorkflowDefinition states JSONB（seed_phase1）+ 注册扩展点
（@register_command / @register_transition_effect / @register_transition_validator，均在已注册的扩展/命令模块内）。
不动 execute_transition / 命令框架 / registry 核心语义。
编号规则 CD/LIC-YYMM-NNN = NumberingRule（seed.py）+ 建单取号 effect（CD 走 START effect）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "p0q1r2s3"
down_revision: Union[str, Sequence[str], None] = "o9p0q1r2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _audit_cols():
    return [
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("company.id"), nullable=False, index=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    ]


def upgrade() -> None:
    # === 进出口证台账（__queryable__ 主数据；先建：customs_declaration_line.license_id 引用它）===
    op.create_table(
        "customs_license",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("company.id"), nullable=False, index=True),
        sa.Column("license_number", sa.String(30), nullable=False),
        sa.Column("license_no", sa.String(80), server_default=""),
        sa.Column("license_type", sa.String(40), server_default=""),
        sa.Column("issuer", sa.String(100), server_default=""),
        sa.Column("broker_id", sa.Integer(), sa.ForeignKey("supplier.id"), nullable=True),
        sa.Column("scope", sa.Text(), server_default=""),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("notes", sa.Text(), server_default=""),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("company_id", "license_number", name="ux_customs_license_number"),
        sa.UniqueConstraint("company_id", "license_no", name="ux_customs_license_no"),
    )

    # === 报关单头（CUSTOMS_DECLARATION doc_type）===
    op.create_table(
        "customs_declaration",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_audit_cols(),
        sa.Column("declaration_number", sa.String(30), nullable=False),
        sa.Column("direction", sa.String(12), server_default="IMPORT"),
        sa.Column("customs_region", sa.String(5), server_default="HK"),
        sa.Column("broker_mode", sa.String(10), server_default="SELF"),
        sa.Column("broker_id", sa.Integer(), sa.ForeignKey("supplier.id"), nullable=True),
        sa.Column("trade_term", sa.String(10), server_default=""),
        sa.Column("goods_receipt_id", sa.Integer(), sa.ForeignKey("goods_receipt.id"), nullable=True),
        sa.Column("shipment_id", sa.Integer(), sa.ForeignKey("shipment_request.id"), nullable=True),
        sa.Column("source_invoice_number", sa.String(50), server_default=""),
        sa.Column("origin_declaration_id", sa.Integer(), sa.ForeignKey("customs_declaration.id"), nullable=True),
        sa.Column("customs_approval_no", sa.String(50), server_default=""),
        sa.Column("customs_approval_date", sa.Date(), nullable=True),
        sa.Column("import_release_date", sa.Date(), nullable=True),
        sa.Column("return_deadline", sa.Date(), nullable=True),
        sa.Column("declared_port", sa.String(100), server_default=""),
        sa.Column("currency", sa.String(3), server_default="USD"),
        sa.Column("total_declared_value", sa.Numeric(16, 2), server_default="0"),
        sa.Column("declared_fx_rate", sa.Numeric(16, 6), nullable=True),
        sa.Column("status", sa.String(15), server_default="DRAFT"),
        sa.Column("notes", sa.Text(), server_default=""),
        sa.UniqueConstraint("company_id", "declaration_number", name="ux_customs_declaration_number"),
    )

    # === 报关单商品明细子表 ===
    op.create_table(
        "customs_declaration_line",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customs_declaration_id", sa.Integer(), sa.ForeignKey("customs_declaration.id"), nullable=False),
        sa.Column("line_number", sa.SmallInteger(), nullable=False),
        sa.Column("material_id", sa.Integer(), sa.ForeignKey("material.id"), nullable=True),
        sa.Column("cn_name", sa.String(300), server_default=""),
        sa.Column("hs_code_cn", sa.String(50), server_default=""),
        sa.Column("hs_code_origin", sa.String(50), server_default=""),
        sa.Column("origin_country", sa.String(50), server_default=""),
        sa.Column("eccn", sa.String(30), server_default=""),
        sa.Column("quantity", sa.Numeric(12, 2), server_default="0"),
        sa.Column("uom", sa.String(20), server_default=""),
        sa.Column("unit_value", sa.Numeric(16, 4), nullable=True),
        sa.Column("declared_amount", sa.Numeric(16, 2), nullable=True),
        sa.Column("currency", sa.String(3), server_default="USD"),
        sa.Column("source_doc_number", sa.String(50), server_default=""),
        sa.Column("source_line_ref", sa.String(60), server_default=""),
        sa.Column("license_id", sa.Integer(), sa.ForeignKey("customs_license.id"), nullable=True),
        sa.Column("remark", sa.Text(), server_default=""),
        sa.UniqueConstraint("customs_declaration_id", "line_number", name="ux_customs_declaration_line"),
    )

    # === 报关费/运费费用子表 ===
    op.create_table(
        "customs_fee_line",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customs_declaration_id", sa.Integer(), sa.ForeignKey("customs_declaration.id"), nullable=False),
        sa.Column("line_number", sa.SmallInteger(), nullable=False),
        sa.Column("fee_type", sa.String(20), server_default="CUSTOMS_FEE"),
        sa.Column("amount", sa.Numeric(16, 2), server_default="0"),
        sa.Column("currency", sa.String(3), server_default="USD"),
        sa.Column("payee", sa.String(100), server_default=""),
        sa.Column("bill_number", sa.String(50), server_default=""),
        sa.Column("incurred_date", sa.Date(), nullable=True),
        sa.Column("allocation_basis", sa.String(20), server_default="AMOUNT"),
        sa.Column("allocation_detail", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb")),
        sa.UniqueConstraint("customs_declaration_id", "line_number", name="ux_customs_fee_line"),
    )

    # === 物流轨迹头（__queryable__ 台账，非审批单）===
    op.create_table(
        "shipment_tracking",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("company.id"), nullable=False, index=True),
        sa.Column("tracking_number", sa.String(100), nullable=False, index=True),
        sa.Column("carrier", sa.String(20), server_default="SF"),
        sa.Column("direction", sa.String(10), server_default="OUTBOUND"),
        sa.Column("ref_doc_type", sa.String(30), server_default=""),
        sa.Column("ref_doc_number", sa.String(50), server_default=""),
        sa.Column("current_status", sa.String(15), server_default="UNKNOWN"),
        sa.Column("last_event_time", sa.DateTime(), nullable=True),
        sa.Column("source", sa.String(12), server_default="MANUAL"),
        sa.Column("is_subscribed", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("synced_at", sa.DateTime(), nullable=True),
        sa.Column("manual_note", sa.Text(), server_default=""),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("company_id", "tracking_number", name="ux_shipment_tracking_number"),
    )

    # === 物流轨迹节点子表 ===
    op.create_table(
        "shipment_tracking_node",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tracking_id", sa.Integer(), sa.ForeignKey("shipment_tracking.id"), nullable=False),
        sa.Column("line_number", sa.SmallInteger(), nullable=False),
        sa.Column("event_time", sa.DateTime(), nullable=True),
        sa.Column("event_type", sa.String(20), server_default=""),
        sa.Column("location", sa.String(100), server_default=""),
        sa.Column("description", sa.String(300), server_default=""),
        sa.Column("raw_opcode", sa.String(20), server_default=""),
        sa.UniqueConstraint("tracking_id", "line_number", name="ux_shipment_tracking_node"),
    )


def downgrade() -> None:
    op.drop_table("shipment_tracking_node")
    op.drop_table("shipment_tracking")
    op.drop_table("customs_fee_line")
    op.drop_table("customs_declaration_line")
    op.drop_table("customs_declaration")
    op.drop_table("customs_license")
