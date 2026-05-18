"""
判定式 DSL — 只读、只判定，无副作用

语法（基于 Python ast 子集）：
  字段访问:   doc.field, lookup("table", id=x).field, entries[0].field
  比较:       == != > >= < <= in not in is is_not
  逻辑:       and or not
  算术:       + - * / // % **
  聚合:       sum, len, count, all, any, min, max, abs
  列表推导:   sum(e.amount for e in entries)
  跨表查询:   lookup / query / count / sum_field

禁止：赋值、函数定义、import、class、调用对象方法（防 doc.delete()）

每条规则 = 一个表达式，结果必须 True
"""

import ast
from sqlalchemy import func, select


# ============================================================
# AST 白名单
# ============================================================

_ALLOWED_NODE_NAMES = [
    "Expression", "BoolOp", "BinOp", "UnaryOp", "Compare",
    "Call", "Attribute", "Subscript", "Name", "Constant", "Load",
    "Store",  # 列表推导的目标变量需要（不允许 Assign，所以 Store 单独安全）
    "Tuple", "List", "Dict", "Set",
    "GeneratorExp", "ListComp", "SetComp", "DictComp", "comprehension",
    # operators
    "And", "Or", "Not", "USub", "UAdd",
    "Add", "Sub", "Mult", "Div", "FloorDiv", "Mod", "Pow",
    "Eq", "NotEq", "Lt", "LtE", "Gt", "GtE", "In", "NotIn", "Is", "IsNot",
    "Slice", "keyword",
    # 兼容旧 Python
    "Index",
]
ALLOWED_NODES = {getattr(ast, n) for n in _ALLOWED_NODE_NAMES if hasattr(ast, n)}

ALLOWED_FUNCS = {"sum", "len", "min", "max", "all", "any", "abs",
                 "lookup", "query", "count", "sum_field",
                 "str", "int", "float", "bool"}


def validate_rule(rule_str: str) -> tuple[bool, str]:
    """检查规则是否合法（只用允许的语法）"""
    try:
        tree = ast.parse(rule_str, mode="eval")
    except SyntaxError as e:
        return False, f"语法错误: {e}"
    for node in ast.walk(tree):
        if type(node) not in ALLOWED_NODES:
            return False, f"不允许的语法: {type(node).__name__}"
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id not in ALLOWED_FUNCS:
                    return False, f"不允许调用函数 {node.func.id}"
            elif isinstance(node.func, ast.Attribute):
                # 禁止调用对象方法（如 doc.delete()）
                return False, "不允许调用对象方法"
            else:
                return False, "不允许的调用形式"
    return True, ""


def _make_helpers(sync_session):
    """跨表查询助手，使用当前 AsyncSession 的底层同步 session。"""
    from core.registry import table_map

    def _query_internal(table_name, **filters):
        m = table_map().get(table_name)
        if not m:
            return []
        stmt = select(m)
        for k, v in filters.items():
            if hasattr(m, k):
                stmt = stmt.where(getattr(m, k) == v)
        return list(sync_session.execute(stmt).scalars().all())

    def _count_internal(table_name, **filters):
        m = table_map().get(table_name)
        if not m:
            return 0
        stmt = select(func.count()).select_from(m)
        for k, v in filters.items():
            if hasattr(m, k):
                stmt = stmt.where(getattr(m, k) == v)
        return sync_session.execute(stmt).scalar() or 0

    def _sum_internal(table_name, field_name, **filters):
        m = table_map().get(table_name)
        if not m or not hasattr(m, field_name):
            return 0
        stmt = select(func.coalesce(func.sum(getattr(m, field_name)), 0))
        for k, v in filters.items():
            if hasattr(m, k):
                stmt = stmt.where(getattr(m, k) == v)
        return sync_session.execute(stmt).scalar() or 0

    def lookup(table_name, **filters):
        rows = _query_internal(table_name, **filters)
        return rows[0] if rows else None

    def query(table_name, **filters):
        return _query_internal(table_name, **filters)

    def count(table_name, **filters):
        return _count_internal(table_name, **filters)

    def sum_field(table_name, field_name, **filters):
        return _sum_internal(table_name, field_name, **filters)

    return {"lookup": lookup, "query": query, "count": count, "sum_field": sum_field}


# ============================================================
# 子表加载
# ============================================================

def _build_subtables_context_sync(sync_session, doc) -> dict:
    """加载 doc 的子表（_line / _entry）"""
    from core.registry import table_map
    parent_table = doc.__table__.name
    ctx = {}
    for sub_name, sub_model in table_map().items():
        if sub_name == parent_table:
            continue
        for col in sub_model.__table__.columns:
            if col.foreign_keys:
                fk = list(col.foreign_keys)[0]
                if fk.column.table.name == parent_table:
                    if any(x in sub_name for x in ["_line", "_entry"]):
                        r = sync_session.execute(select(sub_model).where(getattr(sub_model, col.name) == doc.id))
                        rows = list(r.scalars().all())
                        ctx[sub_name] = rows
                        if "entry" in sub_name:
                            ctx.setdefault("entries", rows)
                        if "line" in sub_name:
                            ctx.setdefault("lines", rows)
                    break
    return ctx


# ============================================================
# 评估
# ============================================================

SAFE_BUILTINS = {
    "sum": sum, "len": len, "min": min, "max": max,
    "all": all, "any": any, "abs": abs,
    "True": True, "False": False, "None": None,
    "str": str, "int": int, "float": float, "bool": bool,
}


def _evaluate_rules_sync(sync_session, doc, rules: list[str]) -> tuple[bool, list[str]]:
    subtables = _build_subtables_context_sync(sync_session, doc)
    helpers = _make_helpers(sync_session)
    context = {**helpers, **subtables, "doc": doc}

    failures = []
    for rule in rules:
        rule = (rule or "").strip()
        if not rule:
            continue
        ok, err = validate_rule(rule)
        if not ok:
            failures.append(f"✗ {rule}    ({err})")
            continue
        try:
            tree = ast.parse(rule, mode="eval")
            code = compile(tree, "<rule>", "eval")
            eval_context = {"__builtins__": SAFE_BUILTINS, **context}
            result = eval(code, eval_context, eval_context)
            if not result:
                failures.append(f"✗ {rule}")
        except Exception as e:
            failures.append(f"✗ {rule}    (报错: {type(e).__name__}: {e})")

    return len(failures) == 0, failures


async def evaluate_rules(db, doc, rules: list[str]) -> tuple[bool, list[str]]:
    """
    评估一组规则。返回 (all_pass, failure_messages)
    失败格式: "✗ <规则原文>" 或 "✗ <规则原文> (报错: ...)"
    """
    if not rules:
        return True, []

    return await db.run_sync(lambda sync_session: _evaluate_rules_sync(sync_session, doc, rules))
