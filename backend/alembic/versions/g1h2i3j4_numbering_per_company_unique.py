"""numbering: per-company unique on document number columns

Revision ID: g1h2i3j4
Revises: f4a5b6c7
Create Date: 2026-06-17

编号接线收口（修编号接线 surface 的 ❌ 跨公司撞号）：

GOODS_RECEIPT / SHIPMENT / PURCHASE_ORDER / SALES_ORDER 的单号列原为【全局 unique】，
与「编号按公司各自连号（6 公司同前缀同期）」冲突——两家公司同月都生成 PR-2606-001，
第二家建单即抛 UniqueViolation。改为 (company_id, *_number) 复合唯一，与已有
SALES_INVOICE / SALES_RETURN / STOCK_TRANSFER / STOCK_ADJUSTMENT / INVENTORY_COUNT
的按公司唯一一致。order_number 保留非唯一 index 供查询。

引擎五条不破坏：纯约束调整，不动唯一写入路径 / execute_transition / 注册器。
"""
from typing import Sequence, Union

from alembic import op


revision: str = "g1h2i3j4"
down_revision: Union[str, Sequence[str], None] = "f4a5b6c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # goods_receipt: 全局 unique → (company_id, receipt_number)
    op.drop_constraint("goods_receipt_receipt_number_key", "goods_receipt", type_="unique")
    op.create_unique_constraint(
        "uq_goods_receipt_company_number", "goods_receipt", ["company_id", "receipt_number"]
    )

    # shipment_request: 全局 unique → (company_id, shipment_number)
    op.drop_constraint("shipment_request_shipment_number_key", "shipment_request", type_="unique")
    op.create_unique_constraint(
        "uq_shipment_request_company_number", "shipment_request", ["company_id", "shipment_number"]
    )

    # purchase_order: 全局 unique index → 非唯一 index + (company_id, order_number)
    op.drop_index("ix_purchase_order_order_number", table_name="purchase_order")
    op.create_index("ix_purchase_order_order_number", "purchase_order", ["order_number"])
    op.create_unique_constraint(
        "uq_purchase_order_company_number", "purchase_order", ["company_id", "order_number"]
    )

    # sales_order: 全局 unique index → 非唯一 index + (company_id, order_number)（前向安全，段3 SO 编号）
    op.drop_index("ix_sales_order_order_number", table_name="sales_order")
    op.create_index("ix_sales_order_order_number", "sales_order", ["order_number"])
    op.create_unique_constraint(
        "uq_sales_order_company_number", "sales_order", ["company_id", "order_number"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_sales_order_company_number", "sales_order", type_="unique")
    op.drop_index("ix_sales_order_order_number", table_name="sales_order")
    op.create_index("ix_sales_order_order_number", "sales_order", ["order_number"], unique=True)

    op.drop_constraint("uq_purchase_order_company_number", "purchase_order", type_="unique")
    op.drop_index("ix_purchase_order_order_number", table_name="purchase_order")
    op.create_index("ix_purchase_order_order_number", "purchase_order", ["order_number"], unique=True)

    op.drop_constraint("uq_shipment_request_company_number", "shipment_request", type_="unique")
    op.create_unique_constraint(
        "shipment_request_shipment_number_key", "shipment_request", ["shipment_number"]
    )

    op.drop_constraint("uq_goods_receipt_company_number", "goods_receipt", type_="unique")
    op.create_unique_constraint(
        "goods_receipt_receipt_number_key", "goods_receipt", ["receipt_number"]
    )
