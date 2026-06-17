"""
第四层：5个通用工具

每个工具接收 (db_session, user, params) → 返回结果dict
权限自动继承：通过user对象过滤数据
不知道LLM的存在
"""

import json
from decimal import Decimal

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

import models as m
from core.registry import table_map


# ============================================================
# 权限辅助
# ============================================================

# 行级只读 privileged 集（决策A，EXT-01-J）：跨公司只读汇总。
# 注意：这与「表级全权」FULL_ACCESS_ROLES 是两个不同集合（D-05g），勿假设一致。
# 普通 FINANCE 已移出 → 严格本公司账套；新增 FINANCE_DIRECTOR 财务总监。
ROW_PRIVILEGED_ROLES = {"BOSS", "FINANCE_DIRECTOR"}


def _company_filter(user: m.UserAccount):
    """返回用户可访问的 company_id 列表（None=不过滤，看全部只读）。

    决策B：普通用户限「已开通公司集 ∩ active_company_id」（由 get_current_user 解析后挂在
    user._active_company_id / user._authorized_company_ids 上）。无上下文时回落主属公司。
    """
    if user.role in ROW_PRIVILEGED_ROLES:
        return None  # 行级只读 privileged：看全部
    active = getattr(user, "_active_company_id", None)
    if active is None:
        return [user.company_id]
    allowed = getattr(user, "_authorized_company_ids", None) or [user.company_id]
    return [active] if active in allowed else [user.company_id]


def _can_view_buy_price(user: m.UserAccount) -> bool:
    # Q18：采购侧进价/成本对销售端（SALES/SA）隐藏 → 集合不含 SALES_*。
    return user.role in (
        "BOSS", "FINANCE_DIRECTOR", "OPERATIONS", "FINANCE",
        "PRODUCT_ASSISTANT", "PRODUCT_MANAGER",
    )


def _can_view_sell_price(user: m.UserAccount) -> bool:
    return user.role in (
        "BOSS", "FINANCE_DIRECTOR", "OPERATIONS", "FINANCE",
        "SALES_ENGINEER", "SALES_ASSISTANT", "SALES",
    )


# 表名→模型 映射:统一在 core.registry.table_map() 中从 __queryable__/__doc_types__ 自动生成。

# 需要隐藏买价的字段（commission=对原厂佣金，04a-2 Q18 与对原厂单价同属采购进价）
# 段2b 04a-3：PO 头 advance_payment_amount/stock_amount_*（备货金额）也属采购进价，对销售端遮蔽。
BUY_PRICE_FIELDS = {
    "unit_price", "total_price", "total_amount", "current_unit_cost", "total_value",
    "unit_cost", "total_cost", "commission",
    "advance_payment_amount", "stock_amount_original", "stock_amount_latest",
    # 段2c 04a-7/04a-8：进项发票 / 预付 / 付款申请 / 应付的 amount = 采购成本/应付（对销售端隐藏，Q18）。
    # 仅作用于 BUY_TABLES（purchase_invoice/advance_payment/payment_request/accounts_payable），
    # 这些表的 amount 即采购进价/应付，不影响 sales 侧（SELL_TABLES 用 SELL_PRICE_FIELDS）。
    "amount",
}
# 需要隐藏卖价的字段（在sales相关表上）
SELL_PRICE_FIELDS = {"unit_price", "total_price", "total_amount"}

# 买价相关的表
BUY_TABLES = {
    "purchase_order", "purchase_order_line", "purchase_notice", "purchase_notice_line",
    "purchase_invoice", "purchase_invoice_line", "advance_payment",
    "accounts_payable", "supplier_credit", "inventory_valuation", "inventory_transaction",
    "inventory", "inventory_movement",
    # 04a-2 对原厂询价明细：unit_price（对原厂单价）/commission（佣金）= 采购进价，对销售端隐藏（Q18）
    "supplier_inquiry_line",
    # 段2c 04a-8：付款申请金额（采购成本/应付）对销售端隐藏（Q18）。
    "payment_request",
}
SELL_TABLES = {
    "sales_order", "sales_order_line", "sales_inquiry", "sales_inquiry_line",
    "quotation", "quotation_line", "sales_invoice", "sales_invoice_line",
    "advance_receipt", "accounts_receivable", "customer_credit",
}

# user_account 里的敏感字段:对任何人屏蔽 password_hash,对非 ADMIN/BOSS 屏蔽 is_admin
USER_ACCOUNT_ALWAYS_HIDDEN = {"password_hash"}
USER_ACCOUNT_ADMIN_ONLY = {"is_admin"}

# ============================================================
# 段2d-2 字段级防火墙（(表×角色) 删列）：决策⑨ RMA 双视图 + 样品成本侧（04b-3/04b-5，§00-8）
# ============================================================
# ★RMA SA/PA 双视图（决策⑨，引擎原生 (表,角色) 列遮蔽）：同一 rma 表，对销售端（SA/SALES/SE）
# 遮蔽采购侧列——SA 不对原厂、单价是成本侧（§00-8）；对 PA/PM/运营/财务给全列。query+schema 两路一致。
RMA_PA_ONLY_FIELDS = {"supplier_id", "po_number", "supplier_rma_number", "unit_price"}
# 样品 SDN 目标价（成本侧）对销售端遮蔽（§00-8）。
SAMPLE_SDN_COST_FIELDS = {"target_price"}

# ============================================================
# 段3a ★报价 Q18 字段防火墙（(表×角色) 删列）：采购成本对销售端 SALES+SA 隐藏，利润点对其可见
# ============================================================
# 报价头/阶梯子表上的「采购成本」列（产品部给）：对销售端（SALES/SA/SE）遮蔽（PRD 05 页面6、甲方 Q18）。
# ⚠️ 不能复用 BUY_TABLES：quotation 在 SELL_TABLES，其 unit_price/total_price/total_amount 是卖价、
# 销售端必须可见；故走 (表×角色) 维度只删 cost/cost_unit 这两列（与决策⑨ RMA 同一原生机制）。
# 利润点 profit_point/unit_profit_point ★不入此集 → 对 SALES+SA 可见（Q18，报价决策用）。
QUOTE_COST_FIELDS_BY_TABLE = {
    "quotation": {"cost"},
    "quote_tier_line": {"cost_unit"},
}


def _can_view_rma_purchase_side(user: m.UserAccount) -> bool:
    """RMA/样品 采购侧列可见集：销售端（SALES/SALES_ASSISTANT/SALES_ENGINEER）遮蔽，其余给全列。

    决策⑨ 铁律：采购(PA)不对客户、销售(SA)不对原厂 → 销售端看不到供应商/PO/原厂RMA号/单价（成本侧）。
    """
    return user.role not in ("SALES", "SALES_ASSISTANT", "SALES_ENGINEER")


def _table_role_field_masked(table_name: str, col_name: str, user: m.UserAccount) -> bool:
    """(表,角色) 维度的列遮蔽（决策⑨ RMA 双视图 + 样品成本侧 + 段3a 报价采购成本）。

    query 序列化（_serialize_row）与 schema（routers/data.py get_schema）两路共用，单一事实源。
    """
    if table_name == "rma" and col_name in RMA_PA_ONLY_FIELDS and not _can_view_rma_purchase_side(user):
        return True
    if table_name == "sample_sdn" and col_name in SAMPLE_SDN_COST_FIELDS and not _can_view_rma_purchase_side(user):
        return True
    # 段3a Q18：报价采购成本 cost/cost_unit 对 SALES+SA 隐藏（利润点不在此集，对其可见）。
    if col_name in QUOTE_COST_FIELDS_BY_TABLE.get(table_name, ()) and not _can_view_buy_price(user):
        return True
    return False

# ============================================================
# 表级权限:哪些角色能查哪些表
# ============================================================
# 短期方案:硬编白名单。长期会搬到 role_definition 表(手术 3)。
# 没列在 ROLE_ALLOWED_TABLES 里的角色 → 用 _DEFAULT_ALLOWED_TABLES(最小可用集)。
# FULL_ACCESS_ROLES 不做表级限制(仍受公司过滤和字段防火墙约束)。

# 表级全权（仅影响只读 query_data/aggregate 的可见表集；写仍走命令、各自 role 校验）。
# FINANCE_DIRECTOR 入此集 = 跨公司只读复核需要看全部表（与 BOSS 同为只读 privileged）。
FULL_ACCESS_ROLES = {"BOSS", "FINANCE_DIRECTOR", "FINANCE", "OPERATIONS", "ADMIN"}

_COMMON_TABLES = {
    # 所有受限角色都能看的:自己经手单据的历史、同事信息、公司信息、物料/库存基础
    "workflow_log", "company", "user_account",
    "material", "material_category",
}

ROLE_ALLOWED_TABLES = {
    "SALES": _COMMON_TABLES | {
        "customer", "customer_contact_line", "framework_contract", "product_line",
        "sales_inquiry", "sales_inquiry_line",
        "quotation", "quotation_line",
        # 段3a CRM 前段：线索/商机/跟进子表/报价阶梯子表（销售看本人线索/商机；★Q18 报价 cost 隐藏、profit_point 可见）。
        "lead", "opportunity", "opportunity_followup_line", "quote_tier_line",
        "sales_order", "sales_order_line",
        "project", "project_material", "project_activity",
        "inventory", "inventory_reservation",
        # 对原厂询价：可见行（采用价勾稽报价），但 unit_price/commission 由字段防火墙遮蔽（Q18）
        "supplier_inquiry", "supplier_inquiry_line",
        # 段2d-1 备货申请（04b-1）：销售可发起/查看本人备货单。amount=含税报价口径对 SALES 可见
        # （§00-8：单上无成本/买价列 → 不进 BUY_TABLES，不遮 amount）。
        "stock_up_request",
        # 段2d-2 样品 SDN（04b-3）：销售发起样品申请（target_price 由防火墙遮蔽）。
        "sample_sdn", "sample_sdn_line",
        # 段2d-2 RMA（04b-5）：销售把客户报修传 PA；采购侧列由决策⑨ 防火墙遮蔽。
        "rma", "rma_line",
    },
    "SALES_ASSISTANT": _COMMON_TABLES | {
        "customer", "customer_contact_line", "framework_contract", "product_line",
        "sales_inquiry", "sales_inquiry_line",
        "quotation", "quotation_line",
        # 段3a CRM 前段：SA 制作报价/维护客户主档/录线索；★Q18 报价 cost/cost_unit 隐藏、profit_point 可见（与 SALES 同层）。
        "lead", "opportunity", "opportunity_followup_line", "quote_tier_line",
        "sales_order", "sales_order_line",
        "purchase_notice", "purchase_notice_line",
        "shipment_request", "shipment_line",
        "sales_return", "sales_return_line",
        "advance_receipt", "accounts_receivable", "sales_invoice", "sales_invoice_line",
        "inventory", "inventory_reservation",  # 承诺发货前查库存/预留
        # 对原厂询价：可见行，但 unit_price/commission 由字段防火墙遮蔽（Q18，与 SALES 同隐藏层）
        "supplier_inquiry", "supplier_inquiry_line",
        # 段2d-2 ★RMA SA 视图（决策⑨）：SA 报客户侧/退客户；采购侧列（supplier_id/po_number/
        # supplier_rma_number/unit_price）由 (rma×SA) 字段防火墙遮蔽。
        "rma", "rma_line",
        "sample_sdn", "sample_sdn_line",
    },
    "SALES_ENGINEER": _COMMON_TABLES | {
        "customer", "customer_contact_line", "framework_contract", "product_line",
        "sales_inquiry", "sales_inquiry_line",
        "quotation", "quotation_line",
        # 段3a CRM 前段：FAE(=SE) 是线索/商机干系人（技术配合/规格确认）；★Q18 报价 cost 隐藏、profit_point 可见。
        "lead", "opportunity", "opportunity_followup_line", "quote_tier_line",
        "sales_order", "sales_order_line",
        "project", "project_material", "project_activity",
        "inventory", "inventory_reservation",
    },
    "PRODUCT_ASSISTANT": _COMMON_TABLES | {
        "supplier",
        # 04a-3：PO 明细型号选择器按 supplier_id 过滤产品代码（一型号多 code 按供应商分，
        # 走 /api/query?table=product_code&filters={supplier_id}）；product_line 供产线带出。
        "product_code", "product_line",
        "supplier_inquiry", "supplier_inquiry_line",  # 04a-2 对原厂询价主责录入，可见全价
        "purchase_notice", "purchase_notice_line",
        "purchase_order", "purchase_order_line",
        "sales_order", "sales_order_line",
        "purchase_invoice", "purchase_invoice_line",
        "advance_payment",
        # 段2c 采购收尾：付款申请（货后付款，PA 发起）+ 采购在途跟踪（PA 录货期/查在途）。
        "payment_request", "purchase_in_transit",
        "goods_receipt", "goods_receipt_line",
        "accounts_payable",
        "inventory", "inventory_reservation", "inventory_policy", "inventory_count", "inventory_count_line",
        "supplier_sn_rule", "wms_attachment", "inventory_valuation", "inventory_transaction", "inventory_movement",
        "warehouse", "warehouse_location",
        # 段2d-1 备货申请（04b-1）：PA 批后下 PO + 原始 vs 最新消单跟踪（谁买谁跟到底）。
        "stock_up_request",
        # 段2d-2 ★RMA PA 视图（决策⑨，全列）+ 样品 SDN（PA 主责申请/跟到货/核料/货回）。
        "rma", "rma_line",
        "sample_sdn", "sample_sdn_line",
    },
    "PRODUCT_MANAGER": _COMMON_TABLES | {
        "supplier", "customer", "customer_contact_line",
        "product_code", "product_line",  # 04a-3：按 supplier 过滤产品代码选型
        "sales_inquiry", "sales_inquiry_line",
        "quotation", "quotation_line",
        # 段3a CRM 前段：PM ★门控报价（是否报价 + 定利润点），全列可见（cost + profit_point）；产线维度看商机转化率。
        "lead", "opportunity", "opportunity_followup_line", "quote_tier_line",
        "supplier_inquiry", "supplier_inquiry_line",  # 04a-2 对原厂询价，可见全价（定利润点）
        "purchase_notice", "purchase_notice_line",
        "project", "project_material", "project_activity",
        "purchase_order", "sales_order",
        "inventory", "inventory_reservation", "inventory_policy", "supplier_sn_rule", "inventory_movement",
        # 段2d-1 备货申请（04b-1）：PM 发起/单批/会审参与。
        "stock_up_request",
        # 段2d-2 RMA（04b-5 决策⑨核心：报原厂/内部消化）+ 样品 SDN（决定申请/跟测试转正），PM 给全列。
        "rma", "rma_line",
        "sample_sdn", "sample_sdn_line",
    },
    "LOGISTICS": _COMMON_TABLES | {
        "shipment_request", "shipment_line",
        "picking_list", "picking_list_line",
        "goods_receipt", "goods_receipt_line",
        "sales_return", "sales_return_line",
        "inventory", "inventory_reservation", "inventory_policy", "inventory_count", "inventory_count_line",
        "supplier_sn_rule", "wms_attachment", "inventory_valuation", "inventory_transaction", "inventory_movement",
        "warehouse", "warehouse_location",
        "label_template",
        "sales_order", "sales_order_line", "customer",
        "purchase_order", "purchase_order_line", "supplier",
        # 段2d-2：样品收货入样品仓 / RMA 货回入库带来源标记（物流货物到仓时操作）。
        "rma", "rma_line",
        "sample_sdn", "sample_sdn_line",
    },
}

# 未知角色的兜底:只给最小公共集,比"什么都不能查"稍好,避免 Agent 直接失效
_DEFAULT_ALLOWED_TABLES = _COMMON_TABLES


def _user_allowed_tables(user: m.UserAccount) -> set[str] | None:
    """返回用户允许查询的表名集合。None 表示全开(FULL_ACCESS_ROLES)。"""
    if user.role in FULL_ACCESS_ROLES:
        return None
    return ROLE_ALLOWED_TABLES.get(user.role, _DEFAULT_ALLOWED_TABLES)


def _user_can_access_table(user: m.UserAccount, table_name: str) -> bool:
    allowed = _user_allowed_tables(user)
    if allowed is None:
        return True
    return table_name in allowed


def _visible_tables(user: m.UserAccount) -> set[str]:
    """用户可见的表集合(做过与 table_map 的交集,防止白名单拼写错误)。"""
    all_tables = set(table_map().keys())
    allowed = _user_allowed_tables(user)
    if allowed is None:
        return all_tables
    return allowed & all_tables


# ============================================================
# Tool 1: query_data
# ============================================================

async def query_data(db: AsyncSession, user: m.UserAccount, params: dict) -> dict:
    """
    查任何表的数据
    params:
      table: 表名
      filters: {字段: 值} 精确过滤
      search: 关键词模糊搜索
      order_by: 排序字段
      limit: 返回数量 (默认20)
    """
    table_name = params.get("table", "")
    model = table_map().get(table_name)
    visible = sorted(_visible_tables(user))
    if not model:
        return {"error": f"表 '{table_name}' 不存在", "available_tables": visible}
    if not _user_can_access_table(user, table_name):
        return {"error": f"角色 '{user.role}' 无权查询 '{table_name}' 表", "available_tables": visible}

    # 构造所有where条件 — 数据查询和总数查询用同一套
    from sqlalchemy import or_
    where_clauses = []

    # 公司过滤
    company_ids = _company_filter(user)
    if company_ids and hasattr(model, "company_id"):
        where_clauses.append(model.company_id.in_(company_ids))

    # 精确过滤
    filters = params.get("filters", {})
    for field, value in filters.items():
        if hasattr(model, field):
            where_clauses.append(getattr(model, field) == value)

    # 模糊搜索
    search = params.get("search", "")
    if search:
        search_fields = {
            "name", "code", "sku", "description", "short_name",
            "order_number", "receipt_number", "shipment_number", "voucher_number", "invoice_number",
            "customer_po_number", "inquiry_number", "quotation_number", "notice_number",
            "batch_number", "inbound_number", "serial_lot_number", "source_doc_number",
            "tracking_number", "customer_part_number", "customer_pr_number", "supplier_part_number",
        }
        for col in model.__table__.columns:
            if col.name.endswith("_number"):
                search_fields.add(col.name)
        conditions = [getattr(model, f).ilike(f"%{search}%") for f in search_fields if hasattr(model, f)]
        if conditions:
            where_clauses.append(or_(*conditions))

    stmt = select(model)
    for c in where_clauses:
        stmt = stmt.where(c)

    # 排序
    order_by = params.get("order_by", "id")
    if order_by.startswith("-") and hasattr(model, order_by[1:]):
        stmt = stmt.order_by(getattr(model, order_by[1:]).desc())
    elif hasattr(model, order_by):
        stmt = stmt.order_by(getattr(model, order_by))

    # 限制
    limit = min(int(params.get("limit", 20)), 100)
    stmt = stmt.limit(limit)

    result = await db.execute(stmt)
    rows = result.scalars().all()

    # 序列化 + 权限过滤字段
    data = [_serialize_row(row, table_name, user) for row in rows]

    # 总数 — 应用相同的过滤条件
    count_stmt = select(func.count()).select_from(model)
    for c in where_clauses:
        count_stmt = count_stmt.where(c)
    total = (await db.execute(count_stmt)).scalar()

    return {"table": table_name, "data": data, "count": len(data), "total": total}


def _serialize_row(row, table_name: str, user: m.UserAccount) -> dict:
    """把ORM对象转dict，同时按权限过滤字段"""
    d = {}
    for col in row.__table__.columns:
        val = getattr(row, col.name)
        # 类型转换
        if isinstance(val, Decimal):
            val = float(val)
        elif hasattr(val, "isoformat"):
            val = val.isoformat()

        # 价格防火墙
        if table_name in BUY_TABLES and col.name in BUY_PRICE_FIELDS and not _can_view_buy_price(user):
            continue
        if table_name in SELL_TABLES and col.name in SELL_PRICE_FIELDS and not _can_view_sell_price(user):
            continue

        # 段2d-2 (表×角色) 防火墙：RMA 双视图（决策⑨）+ 样品成本侧（§00-8）
        if _table_role_field_masked(table_name, col.name, user):
            continue

        # user_account 字段防火墙
        if table_name == "user_account":
            if col.name in USER_ACCOUNT_ALWAYS_HIDDEN:
                continue
            if col.name in USER_ACCOUNT_ADMIN_ONLY and user.role not in ("ADMIN", "BOSS"):
                continue

        d[col.name] = val
    return d


# ============================================================
# Tool 2: calculate
# ============================================================

async def calculate(db: AsyncSession, user: m.UserAccount, params: dict) -> dict:
    """
    计算数学表达式
    params:
      expression: "185000 * 0.6" 或 "1150000 - 850000"
    """
    expr = params.get("expression", "")
    try:
        # 安全计算：只允许数字和基本运算符
        allowed = set("0123456789.+-*/() ")
        if not all(c in allowed for c in expr):
            return {"error": "表达式包含不允许的字符", "expression": expr}
        result = eval(expr)  # 已做安全检查
        return {"expression": expr, "result": result}
    except Exception as e:
        return {"error": str(e), "expression": expr}


# ============================================================
# Tool 3: compare
# ============================================================

async def compare(db: AsyncSession, user: m.UserAccount, params: dict) -> dict:
    """
    比较两个值
    params:
      a: 第一个值
      operator: ">", "<", ">=", "<=", "==", "!="
      b: 第二个值
    """
    a = float(params.get("a", 0))
    op = params.get("operator", "==")
    b = float(params.get("b", 0))

    ops = {
        ">": a > b, "<": a < b, ">=": a >= b,
        "<=": a <= b, "==": a == b, "!=": a != b,
    }
    result = ops.get(op)
    if result is None:
        return {"error": f"不支持的运算符: {op}"}
    return {"a": a, "operator": op, "b": b, "result": result}


# ============================================================
# Tool 4: aggregate
# ============================================================

async def aggregate(db: AsyncSession, user: m.UserAccount, params: dict) -> dict:
    """
    聚合统计
    params:
      table: 表名
      field: 聚合字段
      function: SUM/COUNT/AVG/MAX/MIN
      filters: {字段: 值}
      group_by: 分组字段 (可选)
    """
    table_name = params.get("table", "")
    model = table_map().get(table_name)
    if not model:
        return {"error": f"表 '{table_name}' 不存在", "available_tables": sorted(_visible_tables(user))}
    if not _user_can_access_table(user, table_name):
        return {"error": f"角色 '{user.role}' 无权查询 '{table_name}' 表", "available_tables": sorted(_visible_tables(user))}

    field = params.get("field", "id")
    agg_func = params.get("function", "COUNT").upper()
    if not hasattr(model, field):
        return {"error": f"字段 '{field}' 不存在于表 '{table_name}'"}

    col = getattr(model, field)
    func_map = {
        "SUM": func.sum(col),
        "COUNT": func.count(col),
        "AVG": func.avg(col),
        "MAX": func.max(col),
        "MIN": func.min(col),
    }
    agg = func_map.get(agg_func)
    if agg is None:
        return {"error": f"不支持的函数: {agg_func}"}

    group_by = params.get("group_by", "")

    if group_by and hasattr(model, group_by):
        group_col = getattr(model, group_by)
        stmt = select(group_col, agg.label("value")).group_by(group_col)
    else:
        stmt = select(agg.label("value"))

    # 公司过滤
    company_ids = _company_filter(user)
    if company_ids and hasattr(model, "company_id"):
        stmt = stmt.where(model.company_id.in_(company_ids))

    # 额外过滤
    filters = params.get("filters", {})
    for f, v in filters.items():
        if hasattr(model, f):
            stmt = stmt.where(getattr(model, f) == v)

    result = await db.execute(stmt)

    if group_by:
        rows = result.all()
        return {
            "function": agg_func, "field": field, "group_by": group_by,
            "data": [{"group": str(r[0]), "value": float(r[1]) if r[1] else 0} for r in rows],
        }
    else:
        value = result.scalar()
        return {"function": agg_func, "field": field, "value": float(value) if value else 0}


# ============================================================
# 工具注册表（给Agent用）
# 写操作不在这里:统一走 workflow.execute_transition / preview_transition,
# 由 agent.py 内联处理 request_action 这个 LLM 工具,避免 LLM 拿到"直写"能力。
# ============================================================

TOOLS = {
    "query_data": {
        "function": query_data,
        "schema": {
            "name": "query_data",
            "description": "查询任何业务表的数据。支持过滤、搜索、排序。自动继承用户权限。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "table": {"type": "string", "description": "表名(按用户权限的可查列表由 get_tool_schemas 运行时注入)"},
                    "filters": {"type": "object", "description": "精确过滤条件 {字段: 值}"},
                    "search": {"type": "string", "description": "模糊搜索关键词"},
                    "order_by": {"type": "string", "description": "排序字段，加-前缀倒序"},
                    "limit": {"type": "integer", "description": "返回数量，默认20，最大100"},
                },
                "required": ["table"],
            },
        },
    },
    "calculate": {
        "function": calculate,
        "schema": {
            "name": "calculate",
            "description": "计算数学表达式。如: '185000 * 0.6', '2000000 - 850000'",
            "input_schema": {
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "数学表达式"},
                },
                "required": ["expression"],
            },
        },
    },
    "compare": {
        "function": compare,
        "schema": {
            "name": "compare",
            "description": "比较两个数值。返回布尔结果。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "a": {"type": "number", "description": "第一个值"},
                    "operator": {"type": "string", "description": "运算符: > < >= <= == !="},
                    "b": {"type": "number", "description": "第二个值"},
                },
                "required": ["a", "operator", "b"],
            },
        },
    },
    "aggregate": {
        "function": aggregate,
        "schema": {
            "name": "aggregate",
            "description": "对业务表做聚合统计（求和/计数/平均/最大/最小），可按字段分组。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "table": {"type": "string", "description": "表名"},
                    "field": {"type": "string", "description": "聚合字段"},
                    "function": {"type": "string", "description": "SUM/COUNT/AVG/MAX/MIN"},
                    "filters": {"type": "object", "description": "过滤条件"},
                    "group_by": {"type": "string", "description": "分组字段"},
                },
                "required": ["table", "field", "function"],
            },
        },
    },
}


def get_tool_schemas(user: m.UserAccount) -> list[dict]:
    """按用户角色定制工具 schema 列表。

    query_data / aggregate 的 table description 注入当前可查表清单,
    让 LLM 第一时间知道自己能查什么,减少无谓的试探。其他工具走静态 schema。
    """
    visible = sorted(_visible_tables(user))
    table_hint = ", ".join(visible) if visible else "(当前角色无可查表)"

    def _with_table_desc(src_schema: dict, desc: str) -> dict:
        return {
            **src_schema,
            "input_schema": {
                **src_schema["input_schema"],
                "properties": {
                    **src_schema["input_schema"]["properties"],
                    "table": {"type": "string", "description": desc},
                },
            },
        }

    return [
        _with_table_desc(TOOLS["query_data"]["schema"], f"表名,你当前角色可查询: {table_hint}"),
        TOOLS["calculate"]["schema"],
        TOOLS["compare"]["schema"],
        _with_table_desc(TOOLS["aggregate"]["schema"], f"表名,你当前角色可查询: {table_hint}"),
    ]
