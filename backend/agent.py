"""
第五层：双层Agent引擎（极简版，跟新流程模型对齐）

用户Agent: 理解意图 → 读数据 → 返回修改卡片（不执行）
节点Agent: 检查条件 → 返回修改卡片（不执行）
执行: 用户批复卡片后才调 execute_transition

节点描述直接来自 WorkflowDefinition.states[i].description，不再走 KnowledgeEntry NODE
"""

import json
import time
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import llm
import models as m
import workflow
from tools import TOOLS


# ============================================================
# 卡片
# ============================================================

def make_card(
    doc_type: str, doc_id: int | None,
    from_state: str, to_state: str, action_label: str,
    changes: list, checks: list,
    recommendation: str = "proceed", reason: str = "",
) -> dict:
    return {
        "card_id": str(uuid.uuid4())[:8],
        "doc_type": doc_type,
        "doc_id": doc_id,
        "from_state": from_state,
        "to_state": to_state,
        "action_label": action_label,
        # 兼容字段（前端 ChangeCard 已用过 transition_name）
        "transition_name": action_label,
        "changes": changes,
        "checks": checks,
        "recommendation": recommendation,
        "reason": reason,
    }


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

    available_actions = await _get_user_actions(db, user)
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
                card = await _build_card_from_request(db, tc["input"], user)
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


# ============================================================
# Tier 2: 节点Agent（检查，不执行）
# ============================================================

async def check_node(
    db: AsyncSession,
    doc_type: str,
    doc_id: int,
    to_state: str,
    action_label: str,
    user: m.UserAccount,
    field_updates: dict | None = None,
) -> dict:
    return await _build_card_from_request(db, {
        "doc_type": doc_type,
        "doc_id": doc_id,
        "to_state": to_state,
        "action_label": action_label,
        "field_updates": field_updates or {},
    }, user)


async def _build_card_from_request(db: AsyncSession, request: dict, user: m.UserAccount) -> dict:
    """根据操作请求，调节点Agent检查，返回卡片"""
    doc_type = request.get("doc_type", "")
    doc_id = request.get("doc_id")
    to_state = request.get("to_state") or ""
    action_label = request.get("action_label") or ""
    field_updates = request.get("field_updates", {})

    wf = await workflow.get_active_workflow(db, doc_type)
    if not wf:
        return make_card(doc_type, doc_id, "", to_state, action_label or "未知", [], ["流程不存在"], "reject", "流程不存在")

    # 创建模式（doc_id=None）
    if not doc_id:
        initials = workflow._initial_states(wf)
        target = next((s for s in initials if not to_state or s["code"] == to_state), None)
        if not target:
            return make_card(doc_type, None, "", to_state, action_label or "创建", [],
                             ["找不到合适的初始节点"], "reject", "无法创建")
        checks = [f"创建模式：进入 '{target.get('name', target['code'])}'"]
        if user.role not in ("ADMIN", "BOSS") and target.get("allowed_roles") and user.role not in target["allowed_roles"]:
            return make_card(doc_type, None, "", target["code"], action_label or "创建",
                             [], [f"角色 {user.role} 无权创建"], "reject", "角色无权")
        changes = [{"field": "status", "from": "", "to": target["code"]}]
        for field, val in field_updates.items():
            changes.append({"field": field, "from": "", "to": str(val)})
        return make_card(doc_type, None, "", target["code"], action_label or "创建", changes, checks)

    # 加载单据
    model = workflow.DOC_MODEL_MAP.get(doc_type)
    doc = None
    if model:
        r = await db.execute(select(model).where(model.id == doc_id))
        doc = r.scalar_one_or_none()
    if not doc:
        return make_card(doc_type, doc_id, "", to_state, action_label or "未知", [],
                         [f"{doc_type}#{doc_id}不存在"], "reject", "单据不存在")

    current_code = doc.status
    current_state = workflow._find_state(wf, current_code)
    if not current_state:
        return make_card(doc_type, doc_id, current_code, to_state, action_label or "未知", [],
                         [f"流程未定义状态 '{current_code}'"], "reject", "状态定义缺失")

    checks = [f"当前状态: {current_state.get('name', current_code)} ✓"]
    recommendation = "proceed"
    reason = ""

    # 角色校验
    state_roles = current_state.get("allowed_roles") or []
    if user.role not in ("ADMIN", "BOSS") and state_roles and user.role not in state_roles:
        return make_card(doc_type, doc_id, current_code, to_state, action_label or "操作", [],
                         [f"角色校验: {user.role} 不在 {state_roles}"], "reject", "角色无权")
    checks.append(f"角色: {user.role} ✓")

    # 决定目标状态 + 定位出边（editable 挂在出边上）
    next_entry = None
    if not to_state or to_state == current_code:
        new_status = current_code
        action_label = action_label or "编辑"
        editable: set[str] = set()
    else:
        next_entry = next(
            (n for n in (current_state.get("next") or []) if n.get("to") == to_state and (not action_label or n.get("label") == action_label)),
            None,
        ) or next(
            (n for n in (current_state.get("next") or []) if n.get("to") == to_state),
            None,
        )
        if not next_entry:
            return make_card(doc_type, doc_id, current_code, to_state, action_label or "推进", [],
                             [f"非法跳转 {current_code}→{to_state}"], "reject", "不允许此跳转")
        # next 项可能有自己的角色限制
        n_roles = next_entry.get("roles")
        if n_roles and user.role not in ("ADMIN", "BOSS") and user.role not in n_roles:
            return make_card(doc_type, doc_id, current_code, to_state, action_label or next_entry.get("label", to_state), [],
                             [f"动作角色限制：需 {n_roles}"], "reject", "动作角色无权")
        new_status = to_state
        action_label = action_label or next_entry.get("label", to_state)
        editable = set(next_entry.get("editable_fields") or [])

    # 字段校验
    if field_updates and not editable:
        return make_card(doc_type, doc_id, current_code, to_state, action_label or "操作", [],
                         ["当前动作不允许录入字段"], "reject", "无可编辑字段")
    for field in field_updates:
        if field not in editable:
            return make_card(doc_type, doc_id, current_code, to_state, action_label or "操作", [],
                             [f"字段 {field} 在此动作不可编辑"], "reject", f"字段 {field} 不可编辑")

    # 变更列表
    changes = []
    if new_status != current_code:
        changes.append({"field": "status", "from": current_code, "to": new_status})
    for field, new_val in field_updates.items():
        old_val = getattr(doc, field, None)
        changes.append({"field": field, "from": str(old_val), "to": str(new_val)})

    # 调 LLM 用 state.description 做智能检查
    node_desc = current_state.get("description", "")
    if node_desc:
        llm_check = await _run_node_agent_check(db, wf, current_state, doc_type, doc_id, user, node_desc, action_label, new_status)
        checks.extend(llm_check.get("steps", []))
        if not llm_check.get("proceed", True):
            recommendation = "reject"
            reason = llm_check.get("reason", "节点Agent判断不通过")

    return make_card(doc_type, doc_id, current_code, new_status, action_label, changes, checks, recommendation, reason)


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


# ============================================================
# 执行已批准的卡片
# ============================================================

async def execute_card(
    db: AsyncSession,
    card: dict,
    user: m.UserAccount,
    comment: str = "",
    ip_address: str | None = None,
) -> dict:
    """执行用户已批准的卡片 — 调 execute_transition"""
    field_updates = {}
    for change in card.get("changes", []):
        if change["field"] != "status":
            field_updates[change["field"]] = change["to"]

    return await workflow.execute_transition(
        db=db,
        doc_type=card["doc_type"],
        doc_id=card.get("doc_id"),
        to_state=card.get("to_state"),
        action_label=card.get("action_label", ""),
        user=user,
        field_updates=field_updates,
        comment=comment,
        ip_address=ip_address,
    )


# ============================================================
# 辅助
# ============================================================

async def _get_user_actions(db: AsyncSession, user: m.UserAccount) -> list[dict]:
    """返回所有 (doc_type, current_state, next_action) 组合，用户能用的"""
    actions = []
    for doc_type in workflow.DOC_MODEL_MAP:
        wf = await workflow.get_active_workflow(db, doc_type)
        if not wf:
            continue
        for s in (wf.states or []):
            roles = s.get("allowed_roles") or []
            if user.role not in ("ADMIN", "BOSS") and roles and user.role not in roles:
                continue
            for n in (s.get("next") or []):
                n_roles = n.get("roles") or roles
                if user.role not in ("ADMIN", "BOSS") and n_roles and user.role not in n_roles:
                    continue
                actions.append({
                    "doc_type": doc_type,
                    "from_state": s["code"],
                    "to_state": n["to"],
                    "action_label": n.get("label", n["to"]),
                    "editable_fields": n.get("editable_fields", []),
                })
    return actions
