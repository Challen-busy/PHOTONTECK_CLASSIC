"""phase1a inbound & inventory: goods_receipt head/line cols + inventory markers

Revision ID: d1e2f3a4
Revises: c1d2e3f4
Create Date: 2026-06-16

段1a 入库与库存（PRD 03-仓储WMS-入库与库存）。沿用已有 GOODS_RECEIPT 流程
（START→PENDING→PA_REVIEW→STOCKED_IN→CANCELLED）与现有列，仅在缺口处加列：

- goods_receipt 头部：inbound_type（入库类型枚举，默认外购入库 PURCHASE）+
  supplier_id（FK supplier）+ customer_id（FK customer，可空）+ reviewer_id（审核 PA）。
- goods_receipt_line：放宽 purchase_order_line_id 为 nullable（样品/无 PO 入库）+
  6 个明细补列（remark/customs_fee/freight_fee/import_export_cert/bag_seal_date/ba_hold）。
- inventory：source_marker（JSONB 来源/品质标记）+ reported_customer_id（FK customer，串货隔离）。

引擎五条不破坏：只加列 / 放宽 NULL，不动唯一写入路径（execute_transition / @register_command）。
库存状态 7 态、movement_type STATUS_CHANGE/COUNT_ADJUST 均为纯值集扩展，无 DB 约束变更。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "d1e2f3a4"
down_revision: Union[str, Sequence[str], None] = "c1d2e3f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ========== goods_receipt 头部扩充 ==========
    op.add_column("goods_receipt", sa.Column("inbound_type", sa.String(length=20), nullable=True, server_default="PURCHASE"))
    op.add_column("goods_receipt", sa.Column("supplier_id", sa.Integer(), nullable=True))
    op.add_column("goods_receipt", sa.Column("customer_id", sa.Integer(), nullable=True))
    op.add_column("goods_receipt", sa.Column("reviewer_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_goods_receipt_supplier", "goods_receipt", "supplier", ["supplier_id"], ["id"])
    op.create_foreign_key("fk_goods_receipt_customer", "goods_receipt", "customer", ["customer_id"], ["id"])
    op.create_foreign_key("fk_goods_receipt_reviewer", "goods_receipt", "user_account", ["reviewer_id"], ["id"])

    # ========== goods_receipt_line：放宽 PO 行 + 6 个补列 ==========
    op.alter_column("goods_receipt_line", "purchase_order_line_id", existing_type=sa.Integer(), nullable=True)
    op.add_column("goods_receipt_line", sa.Column("remark", sa.Text(), nullable=True, server_default=""))
    op.add_column("goods_receipt_line", sa.Column("customs_fee", sa.Numeric(16, 2), nullable=True))
    op.add_column("goods_receipt_line", sa.Column("freight_fee", sa.Numeric(16, 2), nullable=True))
    op.add_column("goods_receipt_line", sa.Column("import_export_cert", sa.String(length=50), nullable=True, server_default=""))
    op.add_column("goods_receipt_line", sa.Column("bag_seal_date", sa.Date(), nullable=True))
    op.add_column("goods_receipt_line", sa.Column("ba_hold", sa.String(length=20), nullable=True, server_default=""))

    # ========== inventory：来源/品质标记 + 原厂报备客户 ==========
    op.add_column("inventory", sa.Column("source_marker", postgresql.JSONB(), nullable=True, server_default=sa.text("'{}'::jsonb")))
    op.add_column("inventory", sa.Column("reported_customer_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_inventory_reported_customer", "inventory", "customer", ["reported_customer_id"], ["id"])

    # ========== label_template：放宽 customer_id 为可空（内部入仓编号标签 INTERNAL 不绑客户）==========
    op.alter_column("label_template", "customer_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    op.alter_column("label_template", "customer_id", existing_type=sa.Integer(), nullable=False)

    op.drop_constraint("fk_inventory_reported_customer", "inventory", type_="foreignkey")
    op.drop_column("inventory", "reported_customer_id")
    op.drop_column("inventory", "source_marker")

    op.drop_column("goods_receipt_line", "ba_hold")
    op.drop_column("goods_receipt_line", "bag_seal_date")
    op.drop_column("goods_receipt_line", "import_export_cert")
    op.drop_column("goods_receipt_line", "freight_fee")
    op.drop_column("goods_receipt_line", "customs_fee")
    op.drop_column("goods_receipt_line", "remark")
    op.alter_column("goods_receipt_line", "purchase_order_line_id", existing_type=sa.Integer(), nullable=False)

    op.drop_constraint("fk_goods_receipt_reviewer", "goods_receipt", type_="foreignkey")
    op.drop_constraint("fk_goods_receipt_customer", "goods_receipt", type_="foreignkey")
    op.drop_constraint("fk_goods_receipt_supplier", "goods_receipt", type_="foreignkey")
    op.drop_column("goods_receipt", "reviewer_id")
    op.drop_column("goods_receipt", "customer_id")
    op.drop_column("goods_receipt", "supplier_id")
    op.drop_column("goods_receipt", "inbound_type")
