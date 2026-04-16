"""
LLM Agent 层：用户自然语言对话 -> 调工具查数据 / 提交操作申请

注意：卡片协议（preview / commit / list_user_actions）不在这里 -- 那部分是确定性代码，
已搬到 services/workflow.py。本文件只关心真 LLM 调度。
"""

import json
import time
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agents import llm
from services import workflow
from services.tools import TOOLS
import models as m


# ============================================================
# 辅助：工具摘要（给思维链用）
# ============================================================

def _tool_call_summary(name: str, params: dict) -> str:
    if name == "query_data":
        s = f"查询 {params.get('table', '?')}"
        if params.get("search"):
            s += f" (搜索: {params['search']})"
        if params.get("filters"):
            s += f" (过滤: {params['filters']})"
        return s
    if name == "calculate":
        return f"计算 {params.get('expression', '?')}"
    if name == "aggregate":
        return f"聚合 {params.get('table', '?')}.{params.get('field', '?')}"
    if name == "compare":
        return "比较数据"
    if name == "request_action":
        return f"提交 {params.get('action_label') or '操作'} 申请"
    return name


def _tool_result_summary(name: str, result) -> str:
    if name == "query_data" and isinstance(result, dict):
        return f"返回 {len(result.get('data', []))} 条记录"
    if name in ("calculate", "compare", "aggregate") and isinstance(result, dict):
        return f"结果: {result.get('result', '?')}"
    if name == "request_action":
        return "已生成修改申请"
    return "完成"


# ============================================================
# 知识库辅助
# ============================================================

async def _get_company_intro(db: AsyncSession) -> str:
    result = await db.execute(
        select(m.KnowledgeEntry).where(m.KnowledgeEntry.entry_type == "SYSTEM_PROMPT", m.KnowledgeEntry.is_active == True)
    )
    entry = result.scalar_one_or_none()
    return entry.content if entry else "PHOTONTECK是一家高端光电/量子科技设备代理商。"


async def _get_role_intro(user: m.UserAccount) -> str:
    role_desc = {
        "BOSS": "老板/总经理，可查看所有公司全部数据，审批重大决策",
        "OPERATIONS": "运营管理，各部门协调核心，两边价格都能看",
        "FINANCE": "财务人员，负责记账、审批、收付款",
        "SALES_ASSISTANT": "销售助理(SA)，负责录单、跟单，可看卖价不可看买价",
        "PRODUCT_ASSISTANT": "产品助理(PA)，负责采购下单，可看买价不可看卖价",
        "PRODUCT_MANAGER": "产品经理，负责技术选型和审批",
        "SALES_ENGINEER": "销售工程师，负责客户关系",
        "LOGISTICS": "物流人员，负责收货、拣货、发货",
    }
    return f"当前用户: {user.full_name}，角色: {user.role}。{role_desc.get(user.role, '')}"


async def _get_workflows_summary(db: AsyncSession, user_role: str) -> str:
    """所有流程的概览（流程→节点→出边）"""
    lines = []
    for doc_type in workflow.DOC_MODEL_MAP:
        wf = await workflow.get_active_workflow(db, doc_type)
        if not wf:
            continue
        lines.append(f"\n## {wf.name} ({doc_type})")
        if wf.description:
            lines.append(f"  {wf.description[:200]}")
        for s in (wf.states or []):
            roles = s.get("allowed_roles") or []
            if user_role not in ("ADMIN", "BOSS") and roles and user_role not in roles:
                continue
            tag = ""
            if s.get("is_initial"): tag += "[起]"
            if s.get("is_terminal"): tag += "[终]"
            lines.append(f"  {tag}[{s['code']}] {s.get('name', s['code'])}")
            for n in (s.get("next") or []):
                n_roles = n.get("roles") or roles
                if user_role not in ("ADMIN", "BOSS") and n_roles and user_role not in n_roles:
                    continue
                lines.append(f"    → {n.get('label', n['to'])} ⇒ {n['to']}")
    return "\n".join(lines) if lines else "无可用流程"


async def _get_knowledge_rules(db: AsyncSession, doc_type: str = "") -> str:
    result = await db.execute(
        select(m.KnowledgeEntry).where(m.KnowledgeEntry.entry_type.in_(["RULE", "ALERT"]), m.KnowledgeEntry.is_active == True)
    )
    entries = result.scalars().all()
    relevant = [f"- {e.title}: {e.content}" for e in entries
                if not doc_type or not e.applicable_doc_types or doc_type in e.applicable_doc_types]
    return "\n".join(relevant) if relevant else "无特殊规则"


# ============================================================
# Tier 1: 用户Agent
# ============================================================

async def chat(db: AsyncSession, user_query: str, user: m.UserAccount) -> dict:
    start_time = time.time()

    company_intro = await _get_company_intro(db)
    role_intro = await _get_role_intro(user)
    workflows_summary = await _get_workflows_summary(db, user.role)

    system_prompt = f"""# 公司背景
{company_intro}

# 你的身份
{role_intro}

# 你的职责
你是用户Agent（调度员）。
- 回答查询问题: 用query_data/aggregate/calculate/compare工具
- 当用户想执行写操作: 用request_action工具提交申请，不要说"已执行"，说"已提交申请，等待您确认"
- 回答简洁准确，中文，金额加千分位
- 没有权限的数据直接说明，不猜测
- 查不到就说没有，不编造

# 当前日期
{date.today().isoformat()}

# 可用的流程和操作
{workflows_summary}

# 重要: 你不能执行任何修改。所有修改都通过request_action提交申请，由用户确认后才执行。一次可以提交多个申请。"""

    tool_schemas = [TOOLS[t]["schema"] for t in ["query_data", "calculate", "compare", "aggregate"]]

    available_actions = await workflow.list_user_actions(db, user)
    action_desc = "\n".join(
        f"- {a['action_label']} ({a['doc_type']}: {a['from_state']}→{a['to_state']})" for a in available_actions[:50]
    )
    tool_schemas.append({
        "name": "request_action",
        "description": f"提交写操作申请。可在一次对话中多次调用。\n\n可用操作（部分）:\n{action_desc}",
        "input_schema": {
            "type": "object",
            "properties": {
                "doc_type": {"type": "string", "description": "单据类型，如 SALES_ORDER"},
                "doc_id": {"type": "integer", "description": "单据ID（创建时不传）"},
                "to_state": {"type": "string", "description": "目标状态。不传=纯编辑（不改状态）"},
                "action_label": {"type": "string", "description": "动作名（用于多路径同target时区分）"},
                "field_updates": {"type": "object", "description": "要修改的字段 {字段名: 新值}"},
            },
            "required": ["doc_type"],
        },
    })

    messages = [{"role": "user", "content": user_query}]
    tools_called = []
    total_tokens = 0
    cards = []
    response_text = ""

    for _ in range(5):
        llm_result = await llm.call_llm(messages=messages, system=system_prompt, tools=tool_schemas)
        total_tokens += llm_result["tokens"]

        if not llm_result["tool_calls"]:
            response_text = llm_result["text"]
            break

        tool_results = []
        for tc in llm_result["tool_calls"]:
            if tc["name"] == "request_action":
                inp = tc["input"]
                card = await workflow.preview_transition(
                    db,
                    doc_type=inp.get("doc_type", ""),
                    doc_id=inp.get("doc_id"),
                    to_state=inp.get("to_state") or "",
                    action_label=inp.get("action_label") or "",
                    user=user,
                    field_updates=inp.get("field_updates") or {},
                )
                cards.append(card)
                tools_called.append({"tool": "request_action", "params": tc["input"]})
                tool_results.append(f"[Tool Result]: 已生成修改申请: {card['action_label']} on {card['doc_type']}#{card['doc_id']}，等待用户确认。")
            else:
                func = TOOLS.get(tc["name"], {}).get("function")
                if func:
                    result = await func(db, user, tc["input"])
                    result_str = json.dumps(result, ensure_ascii=False, default=str)
                    tools_called.append({"tool": tc["name"], "params": tc["input"], "result": result})
                else:
                    result_str = json.dumps({"error": f"工具 {tc['name']} 未注册"})
                tool_results.append(f"[Tool Result]: {result_str}")

        raw_msg = llm_result["raw"].get("choices", [{}])[0].get("message", {})
        messages.append({"role": "assistant", "content": raw_msg.get("content", "") or ""})
        messages.append({"role": "user", "content": "\n".join(tool_results)})
    else:
        response_text = response_text or "处理超时"

    duration_ms = int((time.time() - start_time) * 1000)

    db.add(m.AgentLog(
        agent_type="USER", user_id=user.id, company_id=user.company_id,
        user_query=user_query, tools_called=tools_called,
        response=response_text, tokens_used=total_tokens, duration_ms=duration_ms,
    ))
    await db.commit()

    return {
        "response": response_text,
        "tools_called": tools_called,
        "cards": cards,
        "tokens_used": total_tokens,
        "duration_ms": duration_ms,
    }


async def chat_stream(db: AsyncSession, user_query: str, user: m.UserAccount):
    """chat() 的流式版本，yield SSE 事件 dict（thinking / tool_call / tool_result / done）。"""
    start_time = time.time()
    elapsed = lambda: int((time.time() - start_time) * 1000)

    yield {"type": "thinking", "content": "正在准备上下文...", "elapsed_ms": elapsed()}

    company_intro = await _get_company_intro(db)
    role_intro = await _get_role_intro(user)
    workflows_summary = await _get_workflows_summary(db, user.role)

    system_prompt = f"""# 公司背景
{company_intro}

# 你的身份
{role_intro}

# 你的职责
你是用户Agent（调度员）。
- 回答查询问题: 用query_data/aggregate/calculate/compare工具
- 当用户想执行写操作: 用request_action工具提交申请，不要说"已执行"，说"已提交申请，等待您确认"
- 回答简洁准确，中文，金额加千分位
- 没有权限的数据直接说明，不猜测
- 查不到就说没有，不编造

# 当前日期
{date.today().isoformat()}

# 可用的流程和操作
{workflows_summary}

# 重要: 你不能执行任何修改。所有修改都通过request_action提交申请，由用户确认后才执行。一次可以提交多个申请。"""

    tool_schemas = [TOOLS[t]["schema"] for t in ["query_data", "calculate", "compare", "aggregate"]]
    available_actions = await workflow.list_user_actions(db, user)
    action_desc = "\n".join(
        f"- {a['action_label']} ({a['doc_type']}: {a['from_state']}->{a['to_state']})" for a in available_actions[:50]
    )
    tool_schemas.append({
        "name": "request_action",
        "description": f"提交写操作申请。可在一次对话中多次调用。\n\n可用操作（部分）:\n{action_desc}",
        "input_schema": {
            "type": "object",
            "properties": {
                "doc_type": {"type": "string", "description": "单据类型，如 SALES_ORDER"},
                "doc_id": {"type": "integer", "description": "单据ID（创建时不传）"},
                "to_state": {"type": "string", "description": "目标状态。不传=纯编辑（不改状态）"},
                "action_label": {"type": "string", "description": "动作名（用于多路径同target时区分）"},
                "field_updates": {"type": "object", "description": "要修改的字段 {字段名: 新值}"},
            },
            "required": ["doc_type"],
        },
    })

    yield {"type": "thinking", "content": "正在思考...", "elapsed_ms": elapsed()}

    messages = [{"role": "user", "content": user_query}]
    tools_called = []
    total_tokens = 0
    cards = []
    response_text = ""

    for round_num in range(5):
        if round_num > 0:
            yield {"type": "thinking", "content": f"第 {round_num + 1} 轮推理...", "elapsed_ms": elapsed()}

        llm_result = await llm.call_llm(messages=messages, system=system_prompt, tools=tool_schemas)
        total_tokens += llm_result["tokens"]

        if not llm_result["tool_calls"]:
            response_text = llm_result["text"]
            break

        tool_results = []
        for tc in llm_result["tool_calls"]:
            summary = _tool_call_summary(tc["name"], tc["input"])
            yield {"type": "tool_call", "tool": tc["name"], "summary": summary, "elapsed_ms": elapsed()}

            if tc["name"] == "request_action":
                inp = tc["input"]
                card = await workflow.preview_transition(
                    db, doc_type=inp.get("doc_type", ""), doc_id=inp.get("doc_id"),
                    to_state=inp.get("to_state") or "", action_label=inp.get("action_label") or "",
                    user=user, field_updates=inp.get("field_updates") or {},
                )
                cards.append(card)
                tools_called.append({"tool": "request_action", "params": tc["input"]})
                tool_results.append(f"[Tool Result]: 已生成修改申请: {card['action_label']} on {card['doc_type']}#{card['doc_id']}，等待用户确认。")
                yield {"type": "tool_result", "tool": tc["name"], "summary": "已生成修改申请", "elapsed_ms": elapsed()}
            else:
                func = TOOLS.get(tc["name"], {}).get("function")
                if func:
                    result = await func(db, user, tc["input"])
                    result_str = json.dumps(result, ensure_ascii=False, default=str)
                    tools_called.append({"tool": tc["name"], "params": tc["input"], "result": result})
                    yield {"type": "tool_result", "tool": tc["name"], "summary": _tool_result_summary(tc["name"], result), "elapsed_ms": elapsed()}
                else:
                    result_str = json.dumps({"error": f"工具 {tc['name']} 未注册"})
                    yield {"type": "tool_result", "tool": tc["name"], "summary": "工具未注册", "elapsed_ms": elapsed()}
                tool_results.append(f"[Tool Result]: {result_str}")

        raw_msg = llm_result["raw"].get("choices", [{}])[0].get("message", {})
        messages.append({"role": "assistant", "content": raw_msg.get("content", "") or ""})
        messages.append({"role": "user", "content": "\n".join(tool_results)})
    else:
        response_text = response_text or "处理超时"

    duration_ms = elapsed()

    db.add(m.AgentLog(
        agent_type="USER", user_id=user.id, company_id=user.company_id,
        user_query=user_query, tools_called=tools_called,
        response=response_text, tokens_used=total_tokens, duration_ms=duration_ms,
    ))
    await db.commit()

    yield {
        "type": "done",
        "response": response_text,
        "tools_called": tools_called,
        "cards": cards,
        "tokens_used": total_tokens,
        "duration_ms": duration_ms,
    }


async def _run_node_agent_check(db, wf, state, doc_type, doc_id, user, node_desc, action_label, new_status) -> dict:
    """节点Agent LLM检查 — 描述直接来自 state.description"""
    company_intro = await _get_company_intro(db)
    role_intro = await _get_role_intro(user)
    knowledge_rules = await _get_knowledge_rules(db, doc_type)

    # 整个流程概览
    flow_lines = []
    for s in (wf.states or []):
        mark = " ← 当前" if s["code"] == state["code"] else ""
        flow_lines.append(f"  [{s['code']}] {s.get('name', s['code'])}{mark}")
        for n in (s.get("next") or []):
            flow_lines.append(f"    → {n.get('label')} ⇒ {n['to']}")
    flow_desc = "\n".join(flow_lines)

    system = f"""# 公司背景
{company_intro}

# 触发者
{role_intro}

# 你的职责
你是节点Agent，检查: {wf.name} > {state.get('name', state['code'])} 节点上的动作 [{action_label}]（{state['code']}→{new_status}）

# 节点描述
{node_desc}

# 当前日期
{date.today().isoformat()}

# 当前单据: {doc_type} #{doc_id}（用 query_data 查具体数据）

# 流程概览
{flow_desc}

# 业务规则
{knowledge_rules}

# 规则
- 用 query_data 查询需要的数据
- 检查完调 confirm_check 报告结果
- proceed=true 可执行，proceed=false 说明原因"""

    # Agent 工具始终全开 —— 节点级别不再限制
    node_tools = [TOOLS[t]["schema"] for t in TOOLS]
    node_tools.append({
        "name": "confirm_check",
        "description": "报告检查结果",
        "input_schema": {
            "type": "object",
            "properties": {
                "proceed": {"type": "boolean"},
                "reason": {"type": "string"},
                "checks_done": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["proceed"],
        },
    })

    messages = [{"role": "user", "content": f"检查 {doc_type}#{doc_id} 在节点 [{state['code']}] 能否执行 [{action_label}]"}]

    for _ in range(4):
        llm_result = await llm.call_llm(messages=messages, system=system, tools=node_tools, max_tokens=1024)
        if not llm_result["tool_calls"]:
            return {"proceed": True, "steps": ["检查完成（无明确结论，默认通过）"]}

        tool_results = []
        for tc in llm_result["tool_calls"]:
            if tc["name"] == "confirm_check":
                return {
                    "proceed": tc["input"].get("proceed", True),
                    "reason": tc["input"].get("reason", ""),
                    "steps": tc["input"].get("checks_done", []),
                }
            func = TOOLS.get(tc["name"], {}).get("function")
            if func:
                result = await func(db, user, tc["input"])
                tool_results.append(f"[Tool Result for {tc['name']}]: {json.dumps(result, ensure_ascii=False, default=str)}")
            else:
                tool_results.append(f"[Tool Result]: 工具未注册")

        raw_msg = llm_result["raw"].get("choices", [{}])[0].get("message", {})
        messages.append({"role": "assistant", "content": raw_msg.get("content", "") or ""})
        messages.append({"role": "user", "content": "\n".join(tool_results)})

    return {"proceed": True, "steps": ["4轮未完成，默认通过"]}





