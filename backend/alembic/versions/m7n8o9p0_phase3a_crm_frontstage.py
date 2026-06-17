"""phase3a: CRM 前段 — 线索 LEAD（页面3）+ 商机 OPPORTUNITY（页面4）+ 跟进子表（页面5）
+ 报价 QUOTATION 对齐扩（页面6：阶梯子表 quote_tier_line + 头 cost/profit_point/quote_decision/PM门控扩列）

Revision ID: m7n8o9p0
Revises: l6m7n8o9
Create Date: 2026-06-17

段3a CRM 前段（PRD 05-客户销售-CRM前段）：售前漏斗（线索→商机→报价）显式建模。
- lead 头：网络/电话咨询登记 → 销售经理分派 → 跟进 → 转商机/关闭丢失。客户可空（询价先于建档）。
  «转商机» EXPLICIT effect 派生 opportunity 草稿回填（crm.create_opportunity_from_lead）。
- opportunity 头 + opportunity_followup_line 子表：核心阶段状态机（前期沟通→送样→小批量→批量→
  关闭赢/丢/无进展[可回退]）；科研推进时 research_sub_market 必填（hard_rule，非 schema）。
- quotation 头扩列（opportunity_id/business_unit/cost/profit_point/quote_decision/report_header/
  lead_time/trade_term）+ quote_tier_line 阶梯子表（min_quantity/unit_price/cost_unit/unit_profit_point）。

🔒Q18 报价防火墙（落 services/tools.py BUY_PRICE_FIELDS/BUY_TABLES，非 schema 层）：
  quotation.cost + quote_tier_line.cost_unit 对 SALES+SA 隐藏；
  profit_point/unit_profit_point 不入隐藏集 → 对 SALES+SA 可见（甲方 Q18）。

引擎五条不破坏：仅加表/加列，不动唯一写入路径（execute_transition / @register_command）。
LEAD/OPPORTUNITY 流程 + QUOTATION PM 门控 = WorkflowDefinition states JSONB 配置
（services/phase1_workflows.py，经 seed_phase1 幂等写），非 schema 变更。
转商机派生 = 注册 effect（phase1_effects.py）。LD/OPP 月度连号 = NumberingRule（seed.py）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "m7n8o9p0"
down_revision: Union[str, Sequence[str], None] = "l6m7n8o9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # === 线索 lead（PRD 05 页面3）===
    op.create_table(
        "lead",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("company.id"), nullable=False, index=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("lead_number", sa.String(length=30), nullable=False, index=True),
        sa.Column("source", sa.String(length=20), server_default="BAIDU"),
        sa.Column("content", sa.Text(), server_default=""),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customer.id"), nullable=True),
        sa.Column("customer_name_raw", sa.String(length=120), server_default=""),
        sa.Column("product_line_id", sa.Integer(), sa.ForeignKey("product_line.id"), nullable=True),
        sa.Column("assigned_sales_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("assigned_fae_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("region", sa.String(length=20), server_default=""),
        sa.Column("next_step", sa.String(length=200), server_default=""),
        sa.Column("close_reason", sa.String(length=200), server_default=""),
        sa.Column("status", sa.String(length=30), server_default="DRAFT"),
        sa.Column("notes", sa.Text(), server_default=""),
        sa.UniqueConstraint("company_id", "lead_number", name="ux_lead_company_number"),
    )

    # === 商机 opportunity（PRD 05 页面4）===
    op.create_table(
        "opportunity",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("company.id"), nullable=False, index=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("opportunity_number", sa.String(length=30), nullable=False, index=True),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("lead.id"), nullable=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customer.id"), nullable=True),
        sa.Column("product_line_id", sa.Integer(), sa.ForeignKey("product_line.id"), nullable=True),
        sa.Column("project_name", sa.String(length=200), server_default=""),
        sa.Column("product_model", sa.String(length=120), server_default=""),
        sa.Column("business_unit", sa.String(length=40), server_default=""),
        sa.Column("research_sub_market", sa.String(length=60), server_default=""),
        sa.Column("grade", sa.String(length=20), server_default=""),
        sa.Column("owner_sales_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("fae_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.Column("expected_amount", sa.Numeric(16, 2), nullable=True),
        sa.Column("expected_close_date", sa.Date(), nullable=True),
        sa.Column("stage", sa.String(length=30), server_default="EARLY"),
        sa.Column("next_step", sa.String(length=200), server_default=""),
        sa.Column("close_reason", sa.String(length=200), server_default=""),
        sa.Column("status", sa.String(length=30), server_default="DRAFT"),
        sa.Column("remark", sa.Text(), server_default=""),
        sa.UniqueConstraint("company_id", "opportunity_number", name="ux_opportunity_company_number"),
    )

    # === 商机跟进记录子表 opportunity_followup_line（PRD 05 页面5）===
    op.create_table(
        "opportunity_followup_line",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("opportunity_id", sa.Integer(), sa.ForeignKey("opportunity.id"), nullable=False),
        sa.Column("line_number", sa.SmallInteger(), nullable=False),
        sa.Column("activity_date", sa.Date(), nullable=True),
        sa.Column("activity_type", sa.String(length=20), server_default=""),
        sa.Column("contact_id", sa.Integer(), sa.ForeignKey("customer_contact_line.id"), nullable=True),
        sa.Column("content", sa.Text(), server_default=""),
        sa.Column("next_step", sa.String(length=200), server_default=""),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("user_account.id"), nullable=True),
        sa.UniqueConstraint("opportunity_id", "line_number", name="ux_opp_followup_line_no"),
    )

    # === 报价 quotation 头对齐扩列（PRD 05 页面6）===
    op.add_column("quotation", sa.Column("opportunity_id", sa.Integer(), sa.ForeignKey("opportunity.id"), nullable=True))
    op.add_column("quotation", sa.Column("business_unit", sa.String(length=40), server_default=""))
    # 🔒Q18 采购成本：对销售端隐藏（services/tools.py BUY_PRICE_FIELDS/BUY_TABLES）。
    op.add_column("quotation", sa.Column("cost", sa.Numeric(16, 4), nullable=True))
    # ✅Q18 利润点：对 SALES+SA 可见（不入隐藏集）。
    op.add_column("quotation", sa.Column("profit_point", sa.Numeric(8, 4), nullable=True))
    op.add_column("quotation", sa.Column("quote_decision", sa.String(length=12), server_default="PENDING"))
    op.add_column("quotation", sa.Column("report_header", sa.String(length=120), server_default=""))
    op.add_column("quotation", sa.Column("lead_time", sa.String(length=60), server_default=""))
    op.add_column("quotation", sa.Column("trade_term", sa.String(length=10), server_default=""))

    # === 报价阶梯价子表 quote_tier_line（PRD 05 页面6）===
    op.create_table(
        "quote_tier_line",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("quotation_id", sa.Integer(), sa.ForeignKey("quotation.id"), nullable=False),
        sa.Column("line_number", sa.SmallInteger(), nullable=False),
        sa.Column("min_quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("unit_price", sa.Numeric(12, 4), nullable=True),
        # 🔒Q18：该阶梯采购成本，对 SALES+SA 隐藏。
        sa.Column("cost_unit", sa.Numeric(12, 4), nullable=True),
        # ✅Q18：该阶梯利润点，对 SALES+SA 可见。
        sa.Column("unit_profit_point", sa.Numeric(8, 4), nullable=True),
        sa.Column("remark", sa.String(length=200), server_default=""),
        sa.UniqueConstraint("quotation_id", "line_number", name="ux_quote_tier_line_no"),
    )


def downgrade() -> None:
    op.drop_table("quote_tier_line")
    op.drop_column("quotation", "trade_term")
    op.drop_column("quotation", "lead_time")
    op.drop_column("quotation", "report_header")
    op.drop_column("quotation", "quote_decision")
    op.drop_column("quotation", "profit_point")
    op.drop_column("quotation", "cost")
    op.drop_column("quotation", "business_unit")
    op.drop_column("quotation", "opportunity_id")
    op.drop_table("opportunity_followup_line")
    op.drop_table("opportunity")
    op.drop_table("lead")
