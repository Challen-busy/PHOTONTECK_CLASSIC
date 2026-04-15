"""
钩子 DSL — 读写脚本，副作用只能通过白名单写函数发生

与 rules.py 对称：
  硬规则 = 表达式（单行、返回 bool、只读）
  钩  子 = 脚本（多行、带副作用、可 insert/update 其他表）

语法（Python ast 子集 + exec 模式）：
  读:        doc.field, lookup/query/count/sum_field
  赋值:      local_var = expr          只允许赋给局部变量名
  循环:      for x in seq: ...
  条件:      if cond: ... else: ...
  写:        insert("table", {fields}) → 返回新对象（有 id）
             update("table", {where}, {fields}) → 返回更新行数

禁止：import/def/class/lambda/while/try/with/return/yield/raise/delete
禁止：doc.xxx = val（对象属性赋值）、d[k] = val（下标赋值）
禁止：调用对象方法（doc.something()）

失败处理：钩子抛异常由 execute_transition 捕获并回滚事务。
"""

import ast
from datetime import date, datetime

from sqlalchemy import select, update as sql_update


_ALLOWED_NODE_NAMES = [
    "Module", "Expression",
    "Expr",
    "Assign", "AugAssign",
    "For", "If", "IfExp",
    "BoolOp", "BinOp", "UnaryOp", "Compare",
    "Call", "Attribute", "Subscript", "Name", "Constant", "Load", "Store",
    "Tuple", "List", "Dict", "Set",
    "GeneratorExp", "ListComp", "SetComp", "DictComp", "comprehension",
    "And", "Or", "Not", "USub", "UAdd",
    "Add", "Sub", "Mult", "Div", "FloorDiv", "Mod", "Pow",
    "Eq", "NotEq", "Lt", "LtE", "Gt", "GtE", "In", "NotIn", "Is", "IsNot",
    "Slice", "keyword",
    "Index",
    "Pass",
]
ALLOWED_NODES = {getattr(ast, n) for n in _ALLOWED_NODE_NAMES if hasattr(ast, n)}

ALLOWED_FUNCS = {
    # 读
    "sum", "len", "min", "max", "all", "any", "abs",
    "lookup", "query", "count", "sum_field",
    # 写
    "insert", "update",
    # 日期
    "today", "now",
    # 类型转换（拼字符串、算数用）
    "str", "int", "float", "bool", "list", "dict", "range", "enumerate",
}


def validate_hook(script: str) -> tuple[bool, str]:
    """静态检查：语法 + AST 白名单 + 赋值目标限制"""
    try:
        tree = ast.parse(script, mode="exec")
    except SyntaxError as e:
        return False, f"语法错误: {e}"
    for node in ast.walk(tree):
        if type(node) not in ALLOWED_NODES:
            return False, f"不允许的语法: {type(node).__name__}"
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if not isinstance(tgt, ast.Name):
                    return False, "赋值只允许到局部变量名，不能 obj.attr = x 或 d[k] = v"
        if isinstance(node, ast.AugAssign):
            if not isinstance(node.target, ast.Name):
                return False, "复合赋值只允许到局部变量名"
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id not in ALLOWED_FUNCS:
                    return False, f"不允许调用函数 {node.func.id}"
            elif isinstance(node.func, ast.Attribute):
                return False, "不允许调用对象方法（如 doc.delete()）"
            else:
                return False, "不允许的调用形式"
    return True, ""


def _build_subtables_sync(sync_session, doc) -> dict:
    """从 sync session 加载子表（_line / _entry）"""
    from services.tools import TABLE_MAP
    parent_table = doc.__table__.name
    ctx = {}
    for sub_name, sub_model in TABLE_MAP.items():
        if sub_name == parent_table:
            continue
        for col in sub_model.__table__.columns:
            if not col.foreign_keys:
                continue
            fk = list(col.foreign_keys)[0]
            if fk.column.table.name != parent_table:
                continue
            if any(x in sub_name for x in ["_line", "_entry"]):
                rows = list(sync_session.execute(
                    select(sub_model).where(getattr(sub_model, col.name) == doc.id)
                ).scalars().all())
                ctx[sub_name] = rows
                if "entry" in sub_name:
                    ctx.setdefault("entries", rows)
                if "line" in sub_name:
                    ctx.setdefault("lines", rows)
            break
    return ctx


def _build_context(sync_session, doc):
    """构建钩子可见的函数/变量，并返回操作日志 list"""
    from services.tools import TABLE_MAP

    op_log: list[str] = []

    def _query_rows(table_name, **filters):
        mdl = TABLE_MAP.get(table_name)
        if not mdl:
            raise ValueError(f"未知表: {table_name}")
        stmt = select(mdl)
        for k, v in filters.items():
            if hasattr(mdl, k):
                stmt = stmt.where(getattr(mdl, k) == v)
        return list(sync_session.execute(stmt).scalars().all())

    def lookup(table_name, **filters):
        rs = _query_rows(table_name, **filters)
        return rs[0] if rs else None

    def query(table_name, **filters):
        return _query_rows(table_name, **filters)

    def count_fn(table_name, **filters):
        return len(_query_rows(table_name, **filters))

    def sum_field(table_name, field_name, **filters):
        total = 0
        for r in _query_rows(table_name, **filters):
            v = getattr(r, field_name, None)
            if v is not None:
                total += float(v)
        return total

    def insert(table_name, fields):
        mdl = TABLE_MAP.get(table_name)
        if not mdl:
            raise ValueError(f"未知表: {table_name}")
        clean = {k: v for k, v in (fields or {}).items() if hasattr(mdl, k)}
        obj = mdl(**clean)
        sync_session.add(obj)
        sync_session.flush()
        op_log.append(f"insert {table_name}#{getattr(obj, 'id', '?')}")
        return obj

    def update(table_name, where, fields):
        mdl = TABLE_MAP.get(table_name)
        if not mdl:
            raise ValueError(f"未知表: {table_name}")
        if not where:
            raise ValueError("update 必须提供 where 条件（防全表更新）")
        stmt = sql_update(mdl)
        for k, v in (where or {}).items():
            if hasattr(mdl, k):
                stmt = stmt.where(getattr(mdl, k) == v)
        clean = {k: v for k, v in (fields or {}).items() if hasattr(mdl, k)}
        if not clean:
            return 0
        stmt = stmt.values(**clean)
        r = sync_session.execute(stmt)
        op_log.append(f"update {table_name} x{r.rowcount}")
        return r.rowcount

    subtables = _build_subtables_sync(sync_session, doc)

    ctx = {
        "doc": doc,
        **subtables,
        "lookup": lookup, "query": query, "count": count_fn, "sum_field": sum_field,
        "insert": insert, "update": update,
        "today": date.today, "now": datetime.now,
    }
    return ctx, op_log


def execute_hooks_sync(sync_session, doc, scripts: list[str]) -> list[str]:
    """
    在 sync session 中执行钩子脚本列表。
    安全靠 AST 白名单（禁 import/def/class/attr assign/对象方法调用等）。
    Python 运行时和 SQLAlchemy 需要完整 builtins，所以 exec 的 globals 开放 builtins，
    用户级恶意用法在 validate_hook 阶段已拦下。
    """
    all_log: list[str] = []
    for script in scripts or []:
        s = (script or "").strip()
        if not s:
            continue
        ok, err = validate_hook(s)
        if not ok:
            raise ValueError(f"钩子语法错误: {err}")
        tree = ast.parse(s, mode="exec")
        code = compile(tree, "<hook>", "exec")
        ctx, log = _build_context(sync_session, doc)
        exec(code, {}, ctx)  # 空 globals → Python 用默认 __builtins__
        all_log.extend(log)
    return all_log
