"""phase3c: 客户/销售收尾 — 客户认证(薄+并行会签复用) / 售后技术工单 /
Forecast接单(占位薄) / 特批发货(可隐藏模块) + 功能开关 FeatureFlag

Revision ID: o9p0q1r2
Revises: n8o9p0q1
Create Date: 2026-06-17

段3c（PRD 05-客户认证与会签 / 售后技术工单 / Forecast接单 / 订单与履约 页面4b）：
- customer_qualification 头 + qualification_doc_line（资料清单）+ qualification_risk_line（风险审查）
  子表：客户准入审核，★审核=并行会签复用 services/cosign（CosignLine 子表，cosign_group=CERTIFICATION，
  PA+FINANCE+BOSS 三方全签才过）。APPROVED 回写 customer.qualified_code。
- service_ticket 头 + service_ticket_line（可选明细）子表：售后技术工单（OPEN→IN_PROGRESS→RESOLVED→CLOSED
  + ESCALATED_RMA 旁路），引擎排除「售后」业务 → 全新增 doc_type。
- customer_forecast 头 + customer_forecast_line（滚动月份）子表：Forecast 接单占位薄（手录留痕，不直连）。
- special_shipment 头 + special_shipment_line（入仓编号明细）子表：特批发货（先发后补单，可隐藏模块）；
  ★FINANCE_SPECIAL_APPROVAL 财务特批审 + 强制事后补单勾稽；必关联 SO 硬规则只挂 SHIPMENT 不在此，隔离。
- feature_flag 表：per-company 功能开关（feature.special_batch_shipment 默认 OFF）；引擎无原生 → ➕扩展。

引擎五条不破坏：仅加表，不动唯一写入路径（execute_transition / @register_command）。
状态机/会签校验器/effect = WorkflowDefinition states JSONB（seed_phase1）+ services/cosign + phase1_effects
（均在已注册的扩展模块内，不动 workflow_extensions._EXTENSION_MODULES）。
编号规则 QUAL/ST/FC/SS-YYMM-NNN = NumberingRule（seed.py）+ 建单取号 effect。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "o9p0q1r2"
down_revision: Union[str, Sequence[str], None] = "n8o9p0q1"
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
    # === 客户认证（薄版，会签复用 cosign 标准件）===
    op.create_table(
        "customer_qualification",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_audit_cols(),
        sa.Column("qualification_number", sa.String(30), nullable=False, index=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customer.id"), nullable=True),
        sa.Column("qualification_type", sa.String(30), server_default="NEW_SUPPLIER"),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column("qualified_code", sa.String(50), server_default=""),
        sa.Column("risk_summary", sa.Text(), server_default=""),
        sa.Column("notes", sa.Text(), server_default=""),
        sa.Column("status", sa.String(30), server_default="DRAFT"),
        sa.UniqueConstraint("company_id", "qualification_number", name="ux_customer_qualification_number"),
    )
    op.create_table(
        "qualification_doc_line",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("qualification_id", sa.Integer(), sa.ForeignKey("customer_qualification.id"), nullable=False),
        sa.Column("line_number", sa.SmallInteger(), nullable=False),
        sa.Column("doc_item", sa.String(60), server_default=""),
        sa.Column("is_required", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("is_ready", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("attachment_ref", sa.Text(), server_default=""),
        sa.UniqueConstraint("qualification_id", "line_number"),
    )
    op.create_table(
        "qualification_risk_line",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("qualification_id", sa.Integer(), sa.ForeignKey("customer_qualification.id"), nullable=False),
        sa.Column("line_number", sa.SmallInteger(), nullable=False),
        sa.Column("risk_type", sa.String(20), server_default=""),
        sa.Column("presence", sa.String(10), server_default="PENDING"),
        sa.Column("note", sa.Text(), server_default=""),
        sa.UniqueConstraint("qualification_id", "line_number"),
    )

    # === 售后技术工单（薄）===
    op.create_table(
        "service_ticket",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_audit_cols(),
        sa.Column("ticket_number", sa.String(30), nullable=False, index=True),
        sa.Column("reported_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("report_channel", sa.String(20), server_default="PHONE"),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customer.id"), nullable=True),
        sa.Column("material_id", sa.Integer(), sa.ForeignKey("material.id"), nullable=True),
        sa.Column("serial_lot_number", sa.String(100), server_default=""),
        sa.Column("sales_order_id", sa.Integer(), sa.ForeignKey("sales_order.id"), nullable=True),
        sa.Column("issue_type", sa.String(20), server_default="QUALITY"),
        sa.Column("issue_summary", sa.Text(), server_default=""),
        sa.Column("usage_context", sa.Text(), server_default=""),
        sa.Column("urgency", sa.String(10), server_default="MEDIUM"),
        sa.Column("assignee_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("product_line", sa.String(40), server_default=""),
        sa.Column("resolution_type", sa.String(20), server_default=""),
        sa.Column("resolution_notes", sa.Text(), server_default=""),
        sa.Column("quality_verdict", sa.String(12), server_default="PENDING"),
        sa.Column("repair_advice", sa.Text(), server_default=""),
        sa.Column("rma_id", sa.Integer(), sa.ForeignKey("rma.id"), nullable=True),
        sa.Column("closure_note", sa.Text(), server_default=""),
        sa.Column("status", sa.String(30), server_default="OPEN"),
        sa.UniqueConstraint("company_id", "ticket_number", name="ux_service_ticket_number"),
    )
    op.create_table(
        "service_ticket_line",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("service_ticket_id", sa.Integer(), sa.ForeignKey("service_ticket.id"), nullable=False),
        sa.Column("line_number", sa.SmallInteger(), nullable=False),
        sa.Column("material_id", sa.Integer(), sa.ForeignKey("material.id"), nullable=False),
        sa.Column("serial_lot_number", sa.String(100), server_default=""),
        sa.Column("quantity", sa.Numeric(12, 2), nullable=True),
        sa.Column("line_issue", sa.Text(), server_default=""),
        sa.Column("line_verdict", sa.String(12), server_default="PENDING"),
        sa.UniqueConstraint("service_ticket_id", "line_number"),
    )

    # === 客户 Forecast 滚动预测（占位薄）===
    op.create_table(
        "customer_forecast",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_audit_cols(),
        sa.Column("forecast_number", sa.String(30), nullable=False, index=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customer.id"), nullable=True),
        sa.Column("forecast_version", sa.String(40), server_default=""),
        sa.Column("source_system", sa.String(60), server_default=""),
        sa.Column("product_line", sa.String(40), server_default=""),
        sa.Column("notes", sa.Text(), server_default=""),
        sa.Column("status", sa.String(30), server_default="DRAFT"),
        sa.UniqueConstraint("company_id", "forecast_number", name="ux_customer_forecast_number"),
    )
    op.create_table(
        "customer_forecast_line",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_forecast_id", sa.Integer(), sa.ForeignKey("customer_forecast.id"), nullable=False),
        sa.Column("line_number", sa.SmallInteger(), nullable=False),
        sa.Column("material_id", sa.Integer(), sa.ForeignKey("material.id"), nullable=True),
        sa.Column("forecast_month", sa.String(7), server_default=""),
        sa.Column("forecast_qty", sa.Numeric(12, 2), nullable=True),
        sa.Column("note", sa.Text(), server_default=""),
        sa.UniqueConstraint("customer_forecast_id", "line_number"),
    )

    # === 特批发货（可隐藏模块）===
    op.create_table(
        "special_shipment",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_audit_cols(),
        sa.Column("shipment_number", sa.String(30), nullable=False, index=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customer.id"), nullable=True),
        sa.Column("special_reason", sa.String(20), server_default=""),
        sa.Column("special_reason_note", sa.Text(), server_default=""),
        sa.Column("risk_commitment", sa.Text(), server_default=""),
        sa.Column("authorized_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("expected_reorder_date", sa.Date(), nullable=True),
        sa.Column("price_term", sa.String(10), server_default=""),
        sa.Column("reorder_sales_order_id", sa.Integer(), sa.ForeignKey("sales_order.id"), nullable=True),
        sa.Column("special_approved", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("pending_so", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("notes", sa.Text(), server_default=""),
        sa.Column("status", sa.String(30), server_default="DRAFT"),
        sa.UniqueConstraint("company_id", "shipment_number", name="ux_special_shipment_number"),
    )
    op.create_table(
        "special_shipment_line",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("special_shipment_id", sa.Integer(), sa.ForeignKey("special_shipment.id"), nullable=False),
        sa.Column("line_number", sa.SmallInteger(), nullable=False),
        sa.Column("material_id", sa.Integer(), sa.ForeignKey("material.id"), nullable=True),
        sa.Column("inbound_code", sa.String(100), server_default=""),
        sa.Column("serial_lot_number", sa.String(100), server_default=""),
        sa.Column("quantity", sa.Numeric(12, 2), nullable=True),
        sa.Column("reconciled_so_line_id", sa.Integer(), sa.ForeignKey("sales_order_line.id"), nullable=True),
        sa.UniqueConstraint("special_shipment_id", "line_number"),
    )

    # === 功能开关（per-company）===
    op.create_table(
        "feature_flag",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("company.id"), nullable=False, index=True),
        sa.Column("flag_key", sa.String(60), nullable=False, index=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("notes", sa.Text(), server_default=""),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("company_id", "flag_key", name="ux_feature_flag_company_key"),
    )


def downgrade() -> None:
    op.drop_table("feature_flag")
    op.drop_table("special_shipment_line")
    op.drop_table("special_shipment")
    op.drop_table("customer_forecast_line")
    op.drop_table("customer_forecast")
    op.drop_table("service_ticket_line")
    op.drop_table("service_ticket")
    op.drop_table("qualification_risk_line")
    op.drop_table("qualification_doc_line")
    op.drop_table("customer_qualification")
