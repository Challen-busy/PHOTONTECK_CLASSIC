"""phase2d-2: 样品 SDN（04b-3）+ RMA 退货统一单（04b-5/04b-6）

Revision ID: l6m7n8o9
Revises: k5l6m7n8
Create Date: 2026-06-17

段2d-2 样品/RMA（04b-3/04b-5/04b-6）：引擎排除「样品/退货」业务（引擎 02 §2.9）→ 全新增 doc_type。
采购侧 RMA ≠ WMS 客退 SALES_RETURN（PRD 04b-5 明确新建 RMA doc_type）。

- sample_sdn 头 + sample_sdn_line 子表：向原厂申请样品，走其他入库进样品仓，跟回签/超期/转正。
  转正 effect 将该批库存 SAMPLE→AVAILABLE。SDN 号 SDN-{C/L}-YYMM-NNN（supplier_line 列拼线字母）。
- rma 头 + rma_line 子表：客户报→PA 核料→PM 决策→报原厂/内部消化→货回入库带 source_marker→退客户→关闭。
  ★SA/PA 双视图 = 字段防火墙（决策⑨，supplier_id/po_number/unit_price/supplier_rma_number 对 SA 遮蔽，
  落在 services/tools.py 非 schema 层；本迁移给全列，遮蔽在序列化/schema 两路）。

引擎五条不破坏：仅加表，不动唯一写入路径（execute_transition / @register_command）。
SAMPLE_SDN / RMA 流程 = WorkflowDefinition states JSONB 配置（services/phase1_workflows.py，
经 seed_phase1 幂等写），非 schema 变更。核料判定/转正/货回入库 = 注册 effect（phase1_effects.py）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "l6m7n8o9"
down_revision: Union[str, Sequence[str], None] = "k5l6m7n8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # === 样品 SDN 头（04b-3，权威=SDN Record.xlsx 31 列）===
    op.create_table(
        "sample_sdn",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("company.id"), nullable=False, index=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("sdn_number", sa.String(length=40), nullable=False, index=True),
        sa.Column("supplier_line", sa.String(length=4), server_default=""),
        sa.Column("sdn_date", sa.Date(), nullable=True),
        sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("supplier.id"), nullable=True),
        sa.Column("pa_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("pa_names", sa.String(length=120), server_default=""),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customer.id"), nullable=True),
        sa.Column("sales_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("sample_nature", sa.String(length=12), server_default="FREE"),
        sa.Column("paid_disposition", sa.String(length=16), server_default=""),
        sa.Column("signed_return", sa.String(length=12), server_default=""),
        sa.Column("application", sa.Text(), server_default=""),
        sa.Column("competitor", sa.Text(), server_default=""),
        sa.Column("demand", sa.Text(), server_default=""),
        sa.Column("target_price", sa.Numeric(16, 4), nullable=True),
        sa.Column("tracking", sa.String(length=100), server_default=""),
        sa.Column("project_status", sa.String(length=16), server_default=""),
        sa.Column("pd_dept", sa.String(length=60), server_default=""),
        sa.Column("overdue_basis_date", sa.Date(), nullable=True),
        sa.Column("remark", sa.Text(), server_default=""),
        sa.Column("status", sa.String(length=30), server_default="REQUESTED"),
        sa.UniqueConstraint("company_id", "sdn_number", name="ux_sample_sdn_number"),
    )
    op.create_table(
        "sample_sdn_line",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sample_sdn_id", sa.Integer(), sa.ForeignKey("sample_sdn.id"), nullable=False),
        sa.Column("line_number", sa.SmallInteger(), nullable=False),
        sa.Column("material_id", sa.Integer(), sa.ForeignKey("material.id"), nullable=False),
        sa.Column("description", sa.Text(), server_default=""),
        sa.Column("quantity", sa.Numeric(12, 2), nullable=False),
        sa.Column("serial_lot_number", sa.String(length=100), server_default=""),
        sa.UniqueConstraint("sample_sdn_id", "line_number"),
    )

    # === RMA 退货统一单（04b-5，权威=RMA record.xlsx 24 列）===
    op.create_table(
        "rma",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("company.id"), nullable=False, index=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("rma_number", sa.String(length=40), nullable=False, index=True),
        sa.Column("rma_date", sa.Date(), nullable=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customer.id"), nullable=True),
        sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("supplier.id"), nullable=True),
        sa.Column("failure_description", sa.Text(), server_default=""),
        sa.Column("failure_location", sa.Text(), server_default=""),
        sa.Column("po_number", sa.String(length=50), server_default=""),
        sa.Column("ship_date", sa.Date(), nullable=True),
        sa.Column("invoice_number", sa.String(length=50), server_default=""),
        sa.Column("supplier_rma_number", sa.String(length=50), server_default=""),
        sa.Column("tracking", sa.String(length=100), server_default=""),
        sa.Column("remark", sa.Text(), server_default=""),
        sa.Column("sales_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("pa_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("pe_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("pm_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("pd_dept", sa.String(length=60), server_default=""),
        sa.Column("sold_by_us", sa.Boolean(), nullable=True),
        sa.Column("under_warranty", sa.Boolean(), nullable=True),
        sa.Column("pm_decision", sa.String(length=16), server_default=""),
        sa.Column("return_customs_status", sa.String(length=20), server_default=""),
        sa.Column("status", sa.String(length=30), server_default="REPORTED"),
        sa.UniqueConstraint("company_id", "rma_number", name="ux_rma_number"),
    )
    op.create_table(
        "rma_line",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rma_id", sa.Integer(), sa.ForeignKey("rma.id"), nullable=False),
        sa.Column("line_number", sa.SmallInteger(), nullable=False),
        sa.Column("material_id", sa.Integer(), sa.ForeignKey("material.id"), nullable=False),
        sa.Column("serial_lot_number", sa.String(length=100), server_default=""),
        sa.Column("quantity", sa.Numeric(12, 2), nullable=False),
        sa.Column("failure_description", sa.Text(), server_default=""),
        sa.Column("quality_result", sa.String(length=10), server_default=""),
        sa.UniqueConstraint("rma_id", "line_number"),
    )


def downgrade() -> None:
    op.drop_table("rma_line")
    op.drop_table("rma")
    op.drop_table("sample_sdn_line")
    op.drop_table("sample_sdn")
