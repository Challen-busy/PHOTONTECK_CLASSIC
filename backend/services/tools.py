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


# 表名→模型 映射
TABLE_MAP = {
    "company": m.Company,
    "customer": m.Customer,
    "supplier": m.Supplier,
    "material": m.Material,
    "material_category": m.MaterialCategory,
    "sales_order": m.SalesOrder,
    "sales_order_line": m.SalesOrderLine,
    "purchase_order": m.PurchaseOrder,
    "purchase_order_line": m.PurchaseOrderLine,
    "inventory": m.Inventory,
    "warehouse": m.Warehouse,
    "goods_receipt": m.GoodsReceipt,
    "shipment_request": m.ShipmentRequest,
    "voucher": m.Voucher,
    "voucher_entry": m.VoucherEntry,
    "account": m.Account,
    "account_balance": m.AccountBalance,
    "accounts_receivable": m.AccountsReceivable,
    "accounts_payable": m.AccountsPayable,
    "supplier_credit": m.SupplierCredit,
    "customer_credit": m.CustomerCredit,
    "framework_contract": m.FrameworkContract,
    "project": m.Project,
    "exchange_rate": m.ExchangeRate,
    "workflow_log": m.WorkflowLog,
    "fiscal_year": m.FiscalYear,
    "accounting_period": m.AccountingPeriod,
    "shipment_line": m.ShipmentLine,
    "goods_receipt_line": m.GoodsReceiptLine,
    "warehouse_location": m.WarehouseLocation,
    "picking_list": m.PickingList,
    "picking_list_line": m.PickingListLine,
    "label_template": m.LabelTemplate,
    "inventory_valuation": m.InventoryValuation,
    "inventory_transaction": m.InventoryTransaction,
    "user_account": m.UserAccount,
    "project_material": m.ProjectMaterial,
    "project_activity": m.ProjectActivity,
}

# 需要隐藏买价的字段
BUY_PRICE_FIELDS = {"unit_price", "total_price", "total_amount", "current_unit_cost", "total_value", "unit_cost", "total_cost"}
# 需要隐藏卖价的字段（在sales相关表上）
SELL_PRICE_FIELDS = {"unit_price", "total_price", "total_amount"}

# 买价相关的表
BUY_TABLES = {"purchase_order", "purchase_order_line", "accounts_payable", "supplier_credit", "inventory_valuation", "inventory_transaction"}
SELL_TABLES = {"sales_order", "sales_order_line", "accounts_receivable", "customer_credit"}


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
    model = TABLE_MAP.get(table_name)
    if not model:
        return {"error": f"表 '{table_name}' 不存在", "available_tables": list(TABLE_MAP.keys())}

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
    model = TABLE_MAP.get(table_name)
    if not model:
        return {"error": f"表 '{table_name}' 不存在"}

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
# Tool 5: execute_transition — 在 workflow.py 中实现
# ============================================================

# execute_transition 是唯一的写入工具，定义在 workflow.py
# 这里只注册一个占位，实际调用转发到 workflow.execute_transition


# ============================================================
# 工具注册表（给Agent用）
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
                    "table": {"type": "string", "description": f"表名，可选: {', '.join(TABLE_MAP.keys())}"},
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
    "execute_transition": {
        "function": None,  # 由workflow.py提供
        "schema": {
            "name": "execute_transition",
            "description": "执行流程转换（唯一的数据写入方式）。需要用户确认后才能调用。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "doc_type": {"type": "string", "description": "单据类型"},
                    "doc_id": {"type": "integer", "description": "单据ID"},
                    "transition_name": {"type": "string", "description": "转换名称"},
                    "field_updates": {"type": "object", "description": "要修改的字段"},
                    "comment": {"type": "string", "description": "操作备注"},
                },
                "required": ["doc_type", "doc_id", "transition_name"],
            },
        },
    },
}
