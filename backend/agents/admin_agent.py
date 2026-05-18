"""
流程创建Agent — 超级管理员专用

只有一张表 WorkflowDefinition，所有节点信息在 states JSONB 里。
管理员通过 update_workflow_states 工具直接改 states JSONB。
"""

import json
import time
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agents import llm
from core.database import Base
import models as m


# ============================================================
# 工具
# ============================================================

async def list_tables(db: AsyncSession, user: m.UserAccount, params: dict) -> dict:
    """列出所有数据表和字段"""
    tables = {}
    for table_name, table in Base.metadata.tables.items():
        cols = []
        for col in table.columns:
            cols.append({
                "name": col.name,
                "type": str(col.type),
                "nullable": col.nullable,
                "primary_key": col.primary_key,
            })
        tables[table_name] = cols
    keyword = params.get("keyword", "")
    if keyword:
        tables = {k: v for k, v in tables.items() if keyword.lower() in k.lower()}
    return {"tables": {k: v for k, v in list(tables.items())[:20]}, "total_tables": len(Base.metadata.tables)}


async def list_workflows(db: AsyncSession, user: m.UserAccount, params: dict) -> dict:
    """查看所有流程定义（含 states JSONB）"""
    result = await db.execute(select(m.WorkflowDefinition).order_by(m.WorkflowDefinition.doc_type))
    wfs = result.scalars().all()
    return {"workflows": [{
        "id": wf.id, "doc_type": wf.doc_type, "name": wf.name,
        "version": wf.version, "description": wf.description,
        "is_active": wf.is_active, "is_frozen": wf.is_frozen,
        "states": wf.states,
    } for wf in wfs]}


async def create_workflow(db: AsyncSession, user: m.UserAccount, params: dict) -> dict:
    """创建新流程定义（含完整 states）"""
    doc_type = params.get("doc_type", "")
    name = params.get("name", "")
    description = params.get("description", "")
    states = params.get("states", [])

    if not doc_type or not name or not states:
        return {"error": "需要 doc_type, name, states"}

    existing = await db.execute(
        select(m.WorkflowDefinition).where(
            m.WorkflowDefinition.doc_type == doc_type,
            m.WorkflowDefinition.is_active == True,
        )
    )
    existing_wf = existing.scalar_one_or_none()
    version = (existing_wf.version + 1) if existing_wf else 1
    if existing_wf:
        existing_wf.is_active = False

    wf = m.WorkflowDefinition(
        doc_type=doc_type, name=name, version=version,
        description=description, states=states,
        is_active=True, created_by_id=user.id,
    )
    db.add(wf)
    await db.flush()
    return {"id": wf.id, "doc_type": doc_type, "name": name, "version": version, "state_count": len(states)}


async def update_workflow_states(db: AsyncSession, user: m.UserAccount, params: dict) -> dict:
    """更新流程的 states（整个 JSONB 替换）"""
    workflow_id = params.get("workflow_id")
    states = params.get("states")
    if not workflow_id or states is None:
        return {"error": "需要 workflow_id, states"}

    result = await db.execute(select(m.WorkflowDefinition).where(m.WorkflowDefinition.id == workflow_id))
    wf = result.scalar_one_or_none()
    if not wf:
        return {"error": f"流程 #{workflow_id} 不存在"}
    if wf.is_frozen:
        return {"error": f"流程 {wf.name} v{wf.version} 已冻结，请创建新版本"}

    wf.states = states
    await db.flush()
    return {"id": wf.id, "state_count": len(states)}


async def freeze_workflow(db: AsyncSession, user: m.UserAccount, params: dict) -> dict:
    workflow_id = params.get("workflow_id")
    result = await db.execute(select(m.WorkflowDefinition).where(m.WorkflowDefinition.id == workflow_id))
    wf = result.scalar_one_or_none()
    if not wf:
        return {"error": "流程不存在"}
    wf.is_frozen = True
    await db.flush()
    return {"id": wf.id, "name": wf.name, "version": wf.version, "frozen": True}


async def manage_knowledge(db: AsyncSession, user: m.UserAccount, params: dict) -> dict:
    """管理跨流程知识库条目（RULE/ALERT/SYSTEM_PROMPT/GUIDE/FAQ）"""
    action = params.get("action", "list")

    if action == "list":
        stmt = select(m.KnowledgeEntry).where(m.KnowledgeEntry.is_active == True)
        if params.get("entry_type"):
            stmt = stmt.where(m.KnowledgeEntry.entry_type == params["entry_type"])
        result = await db.execute(stmt)
        entries = result.scalars().all()
        return {"entries": [
            {"id": e.id, "type": e.entry_type, "title": e.title, "content": e.content,
             "applicable_doc_types": e.applicable_doc_types}
            for e in entries
        ]}
    elif action == "create":
        e = m.KnowledgeEntry(
            entry_type=params.get("entry_type", "RULE"),
            title=params.get("title", ""),
            content=params.get("content", ""),
            applicable_doc_types=params.get("applicable_doc_types", []),
        )
        db.add(e)
        await db.flush()
        return {"id": e.id, "title": e.title}
    elif action == "update":
        result = await db.execute(select(m.KnowledgeEntry).where(m.KnowledgeEntry.id == params.get("entry_id")))
        e = result.scalar_one_or_none()
        if not e:
            return {"error": "条目不存在"}
        for f in ["entry_type", "title", "content", "applicable_doc_types"]:
            if f in params:
                setattr(e, f, params[f])
        await db.flush()
        return {"id": e.id, "updated": True}

    return {"error": f"不支持的action: {action}"}


# ============================================================
# 工具注册
# ============================================================

ADMIN_TOOLS = {
    "list_tables": {
        "function": list_tables,
        "schema": {
            "name": "list_tables",
            "description": "列出系统所有数据表和字段",
            "input_schema": {"type": "object", "properties": {"keyword": {"type": "string"}}},
        },
    },
    "list_workflows": {
        "function": list_workflows,
        "schema": {
            "name": "list_workflows",
            "description": "查看所有流程定义（含 states JSONB 全量）",
            "input_schema": {"type": "object", "properties": {}},
        },
    },
    "create_workflow": {
        "function": create_workflow,
        "schema": {
            "name": "create_workflow",
            "description": "创建新流程。states 是节点列表，每个节点含 code/name/allowed_roles/description/next/is_initial?/is_terminal?；每条 next 含 to/label/editable_fields",
            "input_schema": {
                "type": "object",
                "properties": {
                    "doc_type": {"type": "string"},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "states": {"type": "array", "description": "节点列表，结构见 description"},
                },
                "required": ["doc_type", "name", "states"],
            },
        },
    },
    "update_workflow_states": {
        "function": update_workflow_states,
        "schema": {
            "name": "update_workflow_states",
            "description": "整体替换流程的 states 数组。先用 list_workflows 看当前结构再改。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "workflow_id": {"type": "integer"},
                    "states": {"type": "array"},
                },
                "required": ["workflow_id", "states"],
            },
        },
    },
    "freeze_workflow": {
        "function": freeze_workflow,
        "schema": {
            "name": "freeze_workflow",
            "description": "冻结流程版本",
            "input_schema": {
                "type": "object",
                "properties": {"workflow_id": {"type": "integer"}},
                "required": ["workflow_id"],
            },
        },
    },
    "manage_knowledge": {
        "function": manage_knowledge,
        "schema": {
            "name": "manage_knowledge",
            "description": "管理跨流程知识条目（RULE/ALERT/GUIDE/FAQ/SYSTEM_PROMPT）。节点描述请直接改 state.description 用 update_workflow_states。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "description": "list/create/update"},
                    "entry_id": {"type": "integer"},
                    "entry_type": {"type": "string"},
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "applicable_doc_types": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["action"],
            },
        },
    },
}


async def admin_chat(db: AsyncSession, user_query: str, user: m.UserAccount) -> dict:
    if not user.is_admin:
        return {"response": "需要超级管理员权限", "tools_called": []}

    start_time = time.time()

    system_prompt = f"""# 你的身份
你是 PHOTONTECK 系统的流程配置助手。

# 当前日期
{date.today().isoformat()}

# 架构（极简）
- 流程定义只有一张表 WorkflowDefinition，全部内容在 states JSONB
- 每个节点（state）含: code, name, is_initial?, is_terminal?, allowed_roles, description (给Agent), custom_html, hard_rules, hooks, effects, next
- 每条 next 含: to, label, editable_fields, roles?, hard_rules?, hooks?, effects?
- next: [{{to: "下个状态码", label: "动作名", roles?: [...], hard_rules?: [...], effects?: [...]}}]
- 改业务逻辑 = 改 state.description 中文
- 改流程结构 = update_workflow_states 整体替换 states 数组

# 硬规则 hard_rules（判定式 DSL）
挂在 state 或 next 项上。每条是一个表达式字符串，结果必须 True，否则动作被拦下。
**只能读，不能写。**

可用语法：
  字段：    doc.字段名（主单），entries[i].字段（凭证分录），lines[i].字段（订单明细）
  比较：    == != > >= < <= in not in
  逻辑：    and / or / not
  算术：    + - * / // % **
  聚合：    sum, len, min, max, all, any, abs
  推导：    sum(e.debit for e in entries)
  跨表查询: lookup("表名", 字段=值)→单条 / query→多条 / count→数 / sum_field("表","字段",过滤)→求和

禁止：赋值 = / 函数定义 def / lambda / import / class / 调用对象方法 doc.delete() —— 一旦出现报错。

示例：
  - 借贷平衡：     sum(e.debit for e in entries) == sum(e.credit for e in entries)
  - 至少2分录：    len(entries) >= 2
  - 金额>0：       doc.total_amount > 0
  - 期间开着：     lookup("accounting_period", id=doc.period_id).status == "OPEN"
  - 信用额度：     (lookup("customer_credit", customer_id=doc.customer_id) is None) or (lookup("customer_credit", customer_id=doc.customer_id).credit_limit - lookup("customer_credit", customer_id=doc.customer_id).used_amount >= doc.total_amount)
  - 库存够：       all(sum_field("inventory", "quantity", material_id=line.material_id) >= line.quantity for line in lines)

# 钩子 hooks（只读脚本 DSL）
挂在 state 或 next 项上。commit 前执行，失败则整个事务回滚，状态不改。
默认只读，用于复杂的只读校验或日志性计算；业务写入必须使用已注册的 effects / command，不能用 hooks 写表。

每条 = 一段多行 Python 脚本。可用：
  语法：    for / if / local_var = expr  （**禁止** obj.attr = val、d[k] = val、while、try、import）
  读：      doc.字段 / entries[i] / lines[i] / lookup/query/count/sum_field
  日期：    today() / now()

钩子运行时机：
  1. 如果是 next.hooks → 在 next_entry 的硬规则通过后执行
  2. 如果是 state.hooks（当前状态）→ 同上
  3. 如果进入新状态，新状态的 state.hooks 也会执行一次

# effects（注册式业务副作用）
业务写入使用 effects 字段引用后端已注册 effect 名称，例如：
  - "effects": ["crm.create_quotation_from_inquiry"]
  - "effects": ["wms.stock_goods_receipt", "erp.complete_purchase_receipt_followup"]
不要在流程 JSON 里写 insert/update 脚本。

**硬规则 vs 钩子选择**：
  - 只是"不满足就禁止" → 硬规则
  - "满足后自动在别的表记录" → effects / command
  - 两者都要：硬规则先过，过了再跑 effects

# 工具
1. list_tables — 查表结构
2. list_workflows — 查所有流程的完整 states
3. create_workflow — 新建流程
4. update_workflow_states — 整体替换某个流程的 states
5. freeze_workflow — 冻结版本
6. manage_knowledge — 跨流程规则/预警/指南

# 规则
- 改前先用 list_workflows 看现状
- update_workflow_states 是整体替换，要先把旧 states 拷出来改完再传回
- 冻结的流程不能改，需要 create_workflow 创建新版本
- 中文回答"""

    tool_schemas = [t["schema"] for t in ADMIN_TOOLS.values()]
    messages = [{"role": "user", "content": user_query}]
    tools_called = []
    total_tokens = 0
    response_text = ""

    for _ in range(6):
        llm_result = await llm.call_llm(messages=messages, system=system_prompt, tools=tool_schemas)
        total_tokens += llm_result["tokens"]

        if not llm_result["tool_calls"]:
            response_text = llm_result["text"]
            break

        tool_results = []
        for tc in llm_result["tool_calls"]:
            func = ADMIN_TOOLS.get(tc["name"], {}).get("function")
            if func:
                result = await func(db, user, tc["input"])
                await db.commit()
                result_str = json.dumps(result, ensure_ascii=False, default=str)
                tools_called.append({"tool": tc["name"], "params": tc["input"], "result": result})
            else:
                result_str = json.dumps({"error": f"工具 {tc['name']} 未注册"})
            tool_results.append(f"[Tool Result for {tc['name']}]: {result_str}")

        raw_msg = llm_result["raw"].get("choices", [{}])[0].get("message", {})
        messages.append({"role": "assistant", "content": raw_msg.get("content", "") or ""})
        messages.append({"role": "user", "content": "\n".join(tool_results)})
    else:
        response_text = response_text or "处理超时"

    duration_ms = int((time.time() - start_time) * 1000)

    log = m.AgentLog(
        agent_type="ADMIN", user_id=user.id, company_id=user.company_id,
        user_query=user_query, tools_called=tools_called,
        response=response_text, tokens_used=total_tokens, duration_ms=duration_ms,
    )
    db.add(log)
    await db.commit()

    return {
        "response": response_text,
        "tools_called": tools_called,
        "tokens_used": total_tokens,
        "duration_ms": duration_ms,
    }
