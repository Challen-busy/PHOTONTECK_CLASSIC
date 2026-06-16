"""phase1b1 outbound: shipment head outbound_type/vendor + line photo_refs + relax SO line

Revision ID: e1f2a3b4
Revises: d1e2f3a4
Create Date: 2026-06-16

段1b-1 出库（PRD 03-仓储WMS-出库与盘点 + 03a-9 委外发料）。沿用已有 SHIPMENT 流程
（10 态：DRAFT→...→PICKING_RECHECK/FINANCE_APPROVAL→SALES_OUTBOUND→...），仅在缺口处加列：

- shipment_request 头部：outbound_type（出库类型枚举，默认 CUSTOMER 客户发货）+
  vendor_id（FK supplier，委外方，仅委外发料用）+ outsource_note（加工说明，自由文本）。
- shipment_line：放宽 sales_order_line_id 为 nullable（委外发料无 SO）+
  photo_refs（JSONB 多图引用，每包拍照留证，进互检前 hard_rule 须非空）。

引擎五条不破坏：只加列 / 放宽 NULL，不动唯一写入路径（execute_transition / @register_command）。
outbound_type 为纯值集扩展，无 DB 约束变更。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e1f2a3b4"
down_revision: Union[str, Sequence[str], None] = "d1e2f3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ========== shipment_request 头部扩充（出库类型 + 委外） ==========
    op.add_column("shipment_request", sa.Column("outbound_type", sa.String(length=20), nullable=True, server_default="CUSTOMER"))
    op.add_column("shipment_request", sa.Column("vendor_id", sa.Integer(), nullable=True))
    op.add_column("shipment_request", sa.Column("outsource_note", sa.Text(), nullable=True, server_default=""))
    op.create_foreign_key("fk_shipment_request_vendor", "shipment_request", "supplier", ["vendor_id"], ["id"])

    # ========== shipment_line：放宽 SO 行（委外发料无 SO） + 每包照片引用 ==========
    op.alter_column("shipment_line", "sales_order_line_id", existing_type=sa.Integer(), nullable=True)
    op.add_column("shipment_line", sa.Column("photo_refs", postgresql.JSONB(), nullable=True, server_default=sa.text("'[]'::jsonb")))


def downgrade() -> None:
    op.drop_column("shipment_line", "photo_refs")
    op.alter_column("shipment_line", "sales_order_line_id", existing_type=sa.Integer(), nullable=False)

    op.drop_constraint("fk_shipment_request_vendor", "shipment_request", type_="foreignkey")
    op.drop_column("shipment_request", "outsource_note")
    op.drop_column("shipment_request", "vendor_id")
    op.drop_column("shipment_request", "outbound_type")
