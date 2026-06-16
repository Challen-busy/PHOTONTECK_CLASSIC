"""phase1b2: stock transfer + stock adjustment + count goods_nature + GR source_issue_number

Revision ID: f4a5b6c7
Revises: e1f2a3b4
Create Date: 2026-06-16

段1b-2 出库后续（PRD 03b 页面5 调拨 · 页面6 盘点 · 页面7 库存调整单 + 03a-9b 委外加工入库）：

- inventory_count_line += goods_nature（盘点分性质视图，从 inventory 快照带入）。
- goods_receipt += source_issue_number（委外加工入库弱关联委外发料单号，仅留痕）。
- 新表 stock_transfer / stock_transfer_line（STOCK_TRANSFER doc_type，仅同公司内仓/库位间移库）。
- 新表 stock_adjustment / stock_adjustment_line（STOCK_ADJUSTMENT doc_type，盘点差异落账 + 推金蝶）。

引擎五条不破坏：只加列 / 加新实体表，不动唯一写入路径（execute_transition / @register_command）。
新 doc_type 走 __doc_types__ + WorkflowDefinition states JSONB + @register_transition_effect 扩展点。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f4a5b6c7"
down_revision: Union[str, Sequence[str], None] = "e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ========== 加列：盘点分性质 + 委外弱关联 + 库位轻量态机 status ==========
    op.add_column("inventory_count_line", sa.Column("goods_nature", sa.String(length=30), nullable=True, server_default=""))
    op.add_column("goods_receipt", sa.Column("source_issue_number", sa.String(length=50), nullable=True, server_default=""))
    # 库位挂 WAREHOUSE_LOCATION 单态机（ACTIVE），execute_transition 编辑路径读 doc.status，故加 status 列。
    op.add_column("warehouse_location", sa.Column("status", sa.String(length=15), nullable=True, server_default="ACTIVE"))

    # ========== 调拨单（STOCK_TRANSFER）==========
    op.create_table(
        "stock_transfer",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("transfer_number", sa.String(length=40), nullable=False),
        sa.Column("source_location_id", sa.Integer(), nullable=False),
        sa.Column("target_location_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="DRAFT"),
        sa.Column("notes", sa.Text(), server_default=""),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["source_location_id"], ["warehouse_location.id"]),
        sa.ForeignKeyConstraint(["target_location_id"], ["warehouse_location.id"]),
        sa.ForeignKeyConstraint(["company_id"], ["company.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["user_account.id"]),
        sa.ForeignKeyConstraint(["updated_by_id"], ["user_account.id"]),
        sa.UniqueConstraint("company_id", "transfer_number"),
    )
    op.create_index("ix_stock_transfer_transfer_number", "stock_transfer", ["transfer_number"])
    op.create_index("ix_stock_transfer_company_id", "stock_transfer", ["company_id"])

    op.create_table(
        "stock_transfer_line",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("stock_transfer_id", sa.Integer(), nullable=False),
        sa.Column("line_number", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("inventory_id", sa.Integer(), nullable=False),
        sa.Column("inbound_number", sa.String(length=50), server_default=""),
        sa.Column("quantity", sa.Numeric(12, 2), nullable=False),
        sa.Column("notes", sa.Text(), server_default=""),
        sa.ForeignKeyConstraint(["stock_transfer_id"], ["stock_transfer.id"]),
        sa.ForeignKeyConstraint(["inventory_id"], ["inventory.id"]),
        sa.UniqueConstraint("stock_transfer_id", "line_number"),
    )
    op.create_index("ix_stock_transfer_line_stock_transfer_id", "stock_transfer_line", ["stock_transfer_id"])

    # ========== 库存调整单（STOCK_ADJUSTMENT）==========
    op.create_table(
        "stock_adjustment",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("adjustment_number", sa.String(length=40), nullable=False),
        sa.Column("inventory_count_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="DRAFT"),
        sa.Column("notes", sa.Text(), server_default=""),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["inventory_count_id"], ["inventory_count.id"]),
        sa.ForeignKeyConstraint(["company_id"], ["company.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["user_account.id"]),
        sa.ForeignKeyConstraint(["updated_by_id"], ["user_account.id"]),
        sa.UniqueConstraint("company_id", "adjustment_number"),
    )
    op.create_index("ix_stock_adjustment_adjustment_number", "stock_adjustment", ["adjustment_number"])
    op.create_index("ix_stock_adjustment_company_id", "stock_adjustment", ["company_id"])
    op.create_index("ix_stock_adjustment_inventory_count_id", "stock_adjustment", ["inventory_count_id"])

    op.create_table(
        "stock_adjustment_line",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("stock_adjustment_id", sa.Integer(), nullable=False),
        sa.Column("line_number", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("inventory_id", sa.Integer(), nullable=False),
        sa.Column("inbound_number", sa.String(length=50), server_default=""),
        sa.Column("system_quantity", sa.Numeric(12, 2), nullable=False),
        sa.Column("actual_quantity", sa.Numeric(12, 2), nullable=False),
        sa.Column("difference", sa.Numeric(12, 2), server_default="0"),
        sa.Column("reason", sa.String(length=20), server_default=""),
        sa.Column("notes", sa.Text(), server_default=""),
        sa.ForeignKeyConstraint(["stock_adjustment_id"], ["stock_adjustment.id"]),
        sa.ForeignKeyConstraint(["inventory_id"], ["inventory.id"]),
        sa.UniqueConstraint("stock_adjustment_id", "line_number"),
    )
    op.create_index("ix_stock_adjustment_line_stock_adjustment_id", "stock_adjustment_line", ["stock_adjustment_id"])


def downgrade() -> None:
    op.drop_index("ix_stock_adjustment_line_stock_adjustment_id", table_name="stock_adjustment_line")
    op.drop_table("stock_adjustment_line")
    op.drop_index("ix_stock_adjustment_inventory_count_id", table_name="stock_adjustment")
    op.drop_index("ix_stock_adjustment_company_id", table_name="stock_adjustment")
    op.drop_index("ix_stock_adjustment_adjustment_number", table_name="stock_adjustment")
    op.drop_table("stock_adjustment")

    op.drop_index("ix_stock_transfer_line_stock_transfer_id", table_name="stock_transfer_line")
    op.drop_table("stock_transfer_line")
    op.drop_index("ix_stock_transfer_company_id", table_name="stock_transfer")
    op.drop_index("ix_stock_transfer_transfer_number", table_name="stock_transfer")
    op.drop_table("stock_transfer")

    op.drop_column("warehouse_location", "status")
    op.drop_column("goods_receipt", "source_issue_number")
    op.drop_column("inventory_count_line", "goods_nature")
