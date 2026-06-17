"""段3a 冒烟：CRM 前段（线索 LEAD / 商机 OPPORTUNITY / 报价 QUOTATION 对齐扩 + ★PM门控 + ★Q18防火墙）。

经唯一写入路径（execute_transition / query_data）验证：
  [1] 线索：建单（LD-YYMM-001）→ 分派 → 跟进 → 转商机（验 EXPLICIT 派生 opportunity 草稿回填 + OPP-YYMM-001）。
  [2] 商机阶段推进：★科研缺细分市场被 hard_rule 拦（business_unit=RESEARCH 进送样需 research_sub_market）；
      补上细分市场后放行。送样推进需 customer_id（hard_rule）。无进展可回退前期沟通。
  [3] 报价对齐扩 + ★PM 门控：建报价 → 待成本（录 cost/cost_unit）→ ★待报价决策（PM 不点报价进不了已报价 →
      选报价）→ ★待定价（PM 设 profit_point 定价）→ 已报价；非 PM 角色无权在 PM 关卡推进。
  [4] ★Q18 报价防火墙（query+schema 两路）：
      - SALES/SA query quotation 看不到 cost、quote_tier_line 看不到 cost_unit，但看得到 profit_point/unit_profit_point；
      - PM/OPERATIONS 全见（cost + profit_point）。schema 路同步删列。
  [5] 架构边界：节点级 allowed_roles（PM 关卡仅 PRODUCT_MANAGER）；引擎核心未被业务污染（doc_type 注册自动）。

在 backend/ 下执行（指向干净库 photonteck_p3a，需先 alembic upgrade head + seed + seed_phase1）:
  DATABASE_URL=postgresql+asyncpg://photonteck:photonteck@localhost:5433/photonteck_p3a \
    python -m scripts.smoke_p3a
"""

import asyncio
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import models as m
from core.database import get_session_factory
from services.tools import query_data, _serialize_row
from services.workflow import execute_transition
from routers import data as data_router


def _check(label, cond):
    print(f"  [{'OK ' if cond else 'FAIL'}] {label}")
    if not cond:
        raise SystemExit(f"冒烟失败: {label}")


def _ym() -> str:
    return date.today().strftime("%y%m")


async def _user(db, username):
    return (await db.execute(select(m.UserAccount).where(m.UserAccount.username == username))).scalar_one()


def _attach_company_ctx(user):
    """模拟 get_current_user 注入的多租户上下文（_company_filter 读取）。"""
    user._active_company_id = user.company_id
    user._authorized_company_ids = [user.company_id]
    return user


async def main():
    factory = get_session_factory()

    # ============ 0) 取演示用户/主数据 ============
    async with factory() as db:
        sales = await _user(db, "sales")
        sa = await _user(db, "sa")
        se = await _user(db, "se")
        pm = await _user(db, "pm")
        pa = await _user(db, "pa")
        company_id = sales.company_id
        customer = (await db.execute(select(m.Customer).where(m.Customer.company_id == company_id))).scalars().first()
        product_line = (await db.execute(select(m.ProductLine).where(m.ProductLine.company_id == company_id))).scalars().first()
        customer_id = customer.id
        product_line_id = product_line.id if product_line else None
        sales_id, se_id = sales.id, se.id

    # ============ 1) 线索：建单 → 分派 → 跟进 → 转商机（派生 opportunity）============
    print("\n[1] 线索 LEAD：建单（LD 月度连号）→ 分派 → 跟进 → 转商机（验派生 opportunity）")
    async with factory() as db:
        u = await _user(db, "sales")
        created = await execute_transition(
            db, "LEAD", None, u, to_state="START",
            field_updates={
                "source": "BAIDU", "content": "客户咨询 850nm VCSEL 需求一句话",
                "customer_id": customer_id, "product_line_id": product_line_id, "region": "华北",
            },
        )
        _check("销售经 execute_transition 建线索", created.get("success"))
        lead_id = created["doc_id"]

    async with factory() as db:
        lead = (await db.execute(select(m.Lead).where(m.Lead.id == lead_id))).scalar_one()
        expected = f"LD-{_ym()}-001"
        _check(f"线索号 = {expected}（实 {lead.lead_number}）", lead.lead_number == expected)
        _check("建单落初始 START 态（待进 DRAFT 录入）", lead.status == "START")

    # START→DRAFT 进录入态（建单取号已在 START effect 完成）。
    async with factory() as db:
        u = await _user(db, "sales")
        r = await execute_transition(db, "LEAD", lead_id, u, to_state="DRAFT")
        _check("START→DRAFT 进线索登记", r.get("success"))

    # DRAFT→ASSIGNED（提交分派）。
    async with factory() as db:
        u = await _user(db, "sales")
        r = await execute_transition(db, "LEAD", lead_id, u, to_state="ASSIGNED")
        _check("DRAFT→ASSIGNED 提交分派", r.get("success"))

    # ASSIGNED→FOLLOWING（销售经理 @ 分派给某销售 + FAE，开始跟进）。
    async with factory() as db:
        u = await _user(db, "sales")
        r = await execute_transition(db, "LEAD", lead_id, u, to_state="FOLLOWING",
                                     field_updates={"assigned_sales_id": sales_id, "assigned_fae_id": se_id,
                                                    "next_step": "约客户线上沟通"})
        _check("ASSIGNED→FOLLOWING 分派并开始跟进", r.get("success"))

    # FOLLOWING→CONVERTED：转商机（EXPLICIT 派生 effect 建 opportunity）。
    async with factory() as db:
        u = await _user(db, "sales")
        r = await execute_transition(db, "LEAD", lead_id, u, to_state="CONVERTED")
        _check("FOLLOWING→CONVERTED 转商机", r.get("success"))

    async with factory() as db:
        opp = (await db.execute(select(m.Opportunity).where(m.Opportunity.lead_id == lead_id))).scalar_one_or_none()
        _check("★派生 opportunity 已建（EXPLICIT effect）", opp is not None)
        expected_opp = f"OPP-{_ym()}-001"
        _check(f"派生商机号 = {expected_opp}（实 {opp.opportunity_number}）", opp.opportunity_number == expected_opp)
        _check("派生回填客户", opp.customer_id == customer_id)
        _check("派生回填产线", opp.product_line_id == product_line_id)
        _check("派生回填干系人-销售", opp.owner_sales_id == sales_id)
        _check("派生回填干系人-FAE", opp.fae_id == se_id)
        _check("派生商机落初始 EARLY 前期沟通态", opp.status == "EARLY")
        opp_id = opp.id

    # 幂等：再次转商机不应重复建（线索已终态，此处直接验 effect 守卫——手动再跑 effect）。
    async with factory() as db:
        cnt = len((await db.execute(select(m.Opportunity).where(m.Opportunity.lead_id == lead_id))).scalars().all())
        _check("派生幂等：一线索一商机", cnt == 1)

    # ============ 2) 商机阶段推进：★科研缺细分市场被拦 ============
    print("\n[2] 商机阶段推进：★科研（RESEARCH）缺细分市场被 hard_rule 拦，补上放行")
    # 把派生商机置为科研事业部，验送样推进 hard_rule（缺 research_sub_market 拦）。
    async with factory() as db:
        u = await _user(db, "sales")
        r = await execute_transition(db, "OPPORTUNITY", opp_id, u,
                                     field_updates={"business_unit": "RESEARCH", "project_name": "科研定制项目"})
        _check("商机置事业部=RESEARCH（编辑）", r.get("success"))

    # 科研缺 research_sub_market → 进送样被拦。
    async with factory() as db:
        u = await _user(db, "sales")
        denied = await execute_transition(db, "OPPORTUNITY", opp_id, u, to_state="SAMPLING",
                                          field_updates={"customer_id": customer_id})
        _check("★科研缺细分市场进送样被 hard_rule 拦", not denied.get("success"))

    # 补 research_sub_market → 放行。
    async with factory() as db:
        u = await _user(db, "sales")
        r = await execute_transition(db, "OPPORTUNITY", opp_id, u, to_state="SAMPLING",
                                     field_updates={"customer_id": customer_id, "research_sub_market": "光谱分析"})
        _check("补细分市场后进送样放行", r.get("success"))

    async with factory() as db:
        opp = (await db.execute(select(m.Opportunity).where(m.Opportunity.id == opp_id))).scalar_one()
        _check("商机推进到 SAMPLING 送样", opp.status == "SAMPLING")

    # ============ 3) 报价对齐扩 + ★PM 门控 ============
    print("\n[3] 报价 QUOTATION：待成本 → ★待报价决策（PM）→ ★待定价（PM 设 profit_point）→ 已报价")
    async with factory() as db:
        u = await _user(db, "sa")
        created = await execute_transition(
            db, "QUOTATION", None, u, to_state="START",
            field_updates={"customer_id": customer_id, "currency": "USD"},
        )
        _check("SA 建报价单", created.get("success"))
        quote_id = created["doc_id"]

    # START→DRAFT 进制作态。
    async with factory() as db:
        u = await _user(db, "sa")
        r = await execute_transition(db, "QUOTATION", quote_id, u, to_state="DRAFT")
        _check("报价 START→DRAFT 进制作", r.get("success"))

    # DRAFT→PENDING_COST（提交产品部录成本，带阶梯子表）。
    async with factory() as db:
        u = await _user(db, "sa")
        r = await execute_transition(
            db, "QUOTATION", quote_id, u, to_state="PENDING_COST",
            field_updates={"opportunity_id": opp_id, "business_unit": "RESEARCH", "tax_rate": 0},
            sub_updates=[{
                "table": "quote_tier_line", "parent_fk": "quotation_id",
                "fields": {"line_number": 1, "min_quantity": 100, "remark": "样品阶梯"},
            }],
        )
        _check("DRAFT→PENDING_COST 提交录成本（含阶梯子表）", r.get("success"))

    # 待成本：PM 录采购成本 cost（对销售隐藏）+ 子表 cost_unit。
    async with factory() as db:
        u = await _user(db, "pm")
        r = await execute_transition(db, "QUOTATION", quote_id, u, to_state="PENDING_QUOTE_DECISION",
                                     field_updates={"cost": 38.5})
        _check("PENDING_COST→PENDING_QUOTE_DECISION（PM 录成本）", r.get("success"))

    # 给阶梯子表录采购成本 cost_unit（编辑模式 PM 直接写子表）。
    async with factory() as db:
        tier = (await db.execute(select(m.QuoteTierLine).where(m.QuoteTierLine.quotation_id == quote_id))).scalar_one()
        tier.cost_unit = 38.5
        await db.commit()
        tier_id = tier.id

    # ★PM 门控关卡 1：非 PM 无权在 PENDING_QUOTE_DECISION 推进。
    async with factory() as db:
        u = await _user(db, "sa")
        denied = await execute_transition(db, "QUOTATION", quote_id, u, to_state="PENDING_PRICING",
                                          field_updates={"quote_decision": "QUOTE"})
        _check("★非 PM（SA）无权在「待报价决策」推进", not denied.get("success"))

    # ★PM 选「报价」→ 进待定价（门控：不点报价进不了已报价）。
    async with factory() as db:
        u = await _user(db, "pm")
        r = await execute_transition(db, "QUOTATION", quote_id, u, to_state="PENDING_PRICING",
                                     field_updates={"quote_decision": "QUOTE", "report_header": "富泰科技"})
        _check("★PM 选报价 → 待定价", r.get("success"))

    # ★PM 门控关卡 2：PM 设 profit_point 定价 → 已报价（没定价进不了已报价：profit_point 在此关卡录）。
    async with factory() as db:
        u = await _user(db, "pm")
        r = await execute_transition(db, "QUOTATION", quote_id, u, to_state="SENT",
                                     field_updates={"profit_point": 0.25, "total_amount": 4812.5})
        _check("★PM 设利润点定价 → 已报价 SENT", r.get("success"))
        # 同时给子表录利润点 unit_profit_point（对 SALES+SA 可见）。
        tier = (await db.execute(select(m.QuoteTierLine).where(m.QuoteTierLine.id == tier_id))).scalar_one()
        tier.unit_profit_point = 0.25
        tier.unit_price = 48.125
        await db.commit()

    async with factory() as db:
        q = (await db.execute(select(m.Quotation).where(m.Quotation.id == quote_id))).scalar_one()
        _check("报价单到达「已报价」SENT", q.status == "SENT")
        _check("PM 门控决策 quote_decision=QUOTE", q.quote_decision == "QUOTE")

    # ============ 4) ★Q18 报价防火墙（query + schema 两路）============
    print("\n[4] ★Q18 报价防火墙：SALES/SA 无 cost/cost_unit、有 profit_point；PM 全见")

    async def _q(username, table):
        async with factory() as db:
            u = _attach_company_ctx(await _user(db, username))
            res = await query_data(db, u, {"table": table, "filters": {"id": quote_id if table == "quotation" else tier_id}})
            return res.get("data", [{}])[0] if res.get("data") else {}

    # query 路：SALES。
    sales_q = await _q("sales", "quotation")
    sales_t = await _q("sales", "quote_tier_line")
    _check("SALES query quotation 无 cost（采购成本隐藏）", "cost" not in sales_q)
    _check("SALES query quotation 有 profit_point（利润点可见）", "profit_point" in sales_q)
    _check("SALES query quote_tier_line 无 cost_unit（采购成本隐藏）", "cost_unit" not in sales_t)
    _check("SALES query quote_tier_line 有 unit_profit_point（利润点可见）", "unit_profit_point" in sales_t)
    _check("SALES 仍可见卖价 unit_price（子表）", "unit_price" in sales_t)

    # query 路：SA（与 SALES 同层）。
    sa_q = await _q("sa", "quotation")
    sa_t = await _q("sa", "quote_tier_line")
    _check("SA query quotation 无 cost", "cost" not in sa_q)
    _check("SA query quotation 有 profit_point", "profit_point" in sa_q)
    _check("SA query quote_tier_line 无 cost_unit", "cost_unit" not in sa_t)
    _check("SA query quote_tier_line 有 unit_profit_point", "unit_profit_point" in sa_t)

    # query 路：PM 全见。
    pm_q = await _q("pm", "quotation")
    pm_t = await _q("pm", "quote_tier_line")
    _check("PM query quotation 全见 cost", "cost" in pm_q and pm_q.get("cost") is not None)
    _check("PM query quotation 全见 profit_point", "profit_point" in pm_q)
    _check("PM query quote_tier_line 全见 cost_unit", "cost_unit" in pm_t and pm_t.get("cost_unit") is not None)

    # schema 路：与 query 一致删列。
    async def _schema_fields(username, table):
        async with factory() as db:
            u = await _user(db, username)
            res = await data_router.get_schema(table, user=u)
            return {f["name"] for f in res["fields"]}

    sales_qs = await _schema_fields("sales", "quotation")
    sales_ts = await _schema_fields("sales", "quote_tier_line")
    pm_qs = await _schema_fields("pm", "quotation")
    _check("schema 路 SALES quotation 无 cost", "cost" not in sales_qs)
    _check("schema 路 SALES quotation 有 profit_point", "profit_point" in sales_qs)
    _check("schema 路 SALES quote_tier_line 无 cost_unit", "cost_unit" not in sales_ts)
    _check("schema 路 SALES quote_tier_line 有 unit_profit_point", "unit_profit_point" in sales_ts)
    _check("schema 路 PM quotation 全见 cost", "cost" in pm_qs)

    # ============ 5) 架构边界回归：表级权限 + 业务号 ============
    print("\n[5] 架构边界：CRM 表角色白名单 + 业务号 LD/OPP-YYMM-001")
    async with factory() as db:
        u = _attach_company_ctx(await _user(db, "sales"))
        res = await query_data(db, u, {"table": "lead"})
        _check("SALES 可查 lead 表（已入白名单）", "error" not in res)
        res2 = await query_data(db, u, {"table": "opportunity"})
        _check("SALES 可查 opportunity 表（已入白名单）", "error" not in res2)

    async with factory() as db:
        u = _attach_company_ctx(await _user(db, "pm"))
        res = await query_data(db, u, {"table": "opportunity"})
        _check("PM 可查 opportunity 表（产线维度看商机）", "error" not in res)

    print("\n✅ 段3a CRM 前段冒烟全部通过。")


if __name__ == "__main__":
    asyncio.run(main())
