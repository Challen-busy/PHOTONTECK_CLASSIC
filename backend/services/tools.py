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

def _company_filter(user: m.UserAccount):
    """返回用户可访问的company_id列表"""
    if user.role in ("BOSS", "FINANCE"):
        return None  # 不过滤，看全部
    return [user.company_id]  # 普通用户只看自己公司


def _can_view_buy_price(user: m.UserAccount) -> bool:
    return user.role in ("BOSS", "OPERATIONS", "FINANCE", "PRODUCT_ASSISTANT", "PRODUCT_MANAGER")


def _can_view_sell_price(user: m.UserAccount) -> bool:
    return user.role in ("BOSS", "OPERATIONS", "FINANCE", "SALES_ENGINEER", "SALES_ASSISTANT")


# 表名→模型 映射:统一在 core.registry.table_map() 中从 __queryable__/__doc_types__ 自动生成。

# 需要隐藏买价的字段
BUY_PRICE_FIELDS = {"unit_price", "total_price", "total_amount", "current_unit_cost", "total_value", "unit_cost", "total_cost"}
# 需要隐藏卖价的字段（在sales相关表上）
SELL_PRICE_FIELDS = {"unit_price", "total_price", "total_amount"}

# 买价相关的表
BUY_TABLES = {"purchase_order", "purchase_order_line", "accounts_payable", "supplier_credit", "inventory_valuation", "inventory_transaction"}
SELL_TABLES = {"sales_order", "sales_order_line", "accounts_receivable", "customer_credit"}

# user_account 里的敏感字段:对任何人屏蔽 password_hash,对非 ADMIN/BOSS 屏蔽 is_admin
USER_ACCOUNT_ALWAYS_HIDDEN = {"password_hash"}
USER_ACCOUNT_ADMIN_ONLY = {"is_admin"}

# ============================================================
# 表级权限:哪些角色能查哪些表
# ============================================================
# 短期方案:硬编白名单。长期会搬到 role_definition 表(手术 3)。
# 没列在 ROLE_ALLOWED_TABLES 里的角色 → 用 _DEFAULT_ALLOWED_TABLES(最小可用集)。
# FULL_ACCESS_ROLES 不做表级限制(仍受公司过滤和字段防火墙约束)。

FULL_ACCESS_ROLES = {"BOSS", "FINANCE", "OPERATIONS", "ADMIN"}

_COMMON_TABLES = {
    # 所有受限角色都能看的:自己经手单据的历史、同事信息、公司信息、物料/库存基础
    "workflow_log", "company", "user_account",
    "material", "material_category",
}

ROLE_ALLOWED_TABLES = {
    "SALES_ASSISTANT": _COMMON_TABLES | {
        "customer", "framework_contract",
        "sales_order", "sales_order_line",
        "shipment_request", "shipment_line",
        "accounts_receivable",
        "inventory",  # 承诺发货前查库存
    },
    "SALES_ENGINEER": _COMMON_TABLES | {
        "customer", "framework_contract",
        "sales_order", "sales_order_line",
        "project", "project_material", "project_activity",
        "inventory",
    },
    "PRODUCT_ASSISTANT": _COMMON_TABLES | {
        "supplier",
        "purchase_order", "purchase_order_line",
        "goods_receipt", "goods_receipt_line",
        "accounts_payable",
        "inventory", "warehouse", "warehouse_location",
    },
    "PRODUCT_MANAGER": _COMMON_TABLES | {
        "supplier", "customer",
        "project", "project_material", "project_activity",
        "purchase_order", "sales_order",
        "inventory",
    },
    "LOGISTICS": _COMMON_TABLES | {
        "shipment_request", "shipment_line",
        "picking_list", "picking_list_line",
        "goods_receipt", "goods_receipt_line",
        "inventory", "warehouse", "warehouse_location",
        "label_template",
        "sales_order", "sales_order_line", "customer",
        "purchase_order", "purchase_order_line", "supplier",
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
        search_fields = ["name", "code", "sku", "order_number", "description", "short_name",
                        "receipt_number", "shipment_number", "voucher_number", "invoice_number"]
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
