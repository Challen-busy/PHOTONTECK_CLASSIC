# 06 · Agent 引擎

## 6.1 模块定位

一个供应商无关的 LLM Agent 运行时：把用户自然语言变成一个有界的工具调用循环，在通用、权限作用域内的数据/动作工具集上跑。它**严格只读或只提案**——Agent 能查询/计算任意已注册表（受行/列/表权限约束），但**永不写库**；任何变更都以确定性的 **ChangeCard 提案**呈现，必须人确认后经独立的 Command 边界重放才落库。一个薄 LLM 适配器集中 model/base-url/key 配置，让整套引擎只说一种 OpenAI 兼容 HTTP 方言；每次运行写一条审计日志。引擎还托管同循环的"管理员 Agent"（不同工具集）与"节点检查 Agent"（同循环、给咨询性布尔判定）。

> 关键文件：`agents/agent.py`、`agents/admin_agent.py`、`agents/llm.py`、`services/tools.py`、`routers/agent.py`、`models.py:1361 AgentLog`

## 6.2 不变量

- **INV-6.1 Agent 永不直接写**：任何变更须表达成 `preview_transition` 的 ChangeCard，人确认后经 Command 边界重放。
- **INV-6.2 单一 LLM 适配器**：所有 LLM 流量经 `agents/llm.py` 一个出口，统一规范化结果。
- **INV-6.3 有界循环**：工具轮次有硬上限，超限给超时/安全默认答复。
- **INV-6.4 权限随工具**：Agent 可见/可查范围由数据引擎的四层闸（表/注册/行/列）和流程角色枚举共同界定。

## 6.3 核心循环（`agents/agent.py:121 chat / :236 chat_stream`）

1. 由注入上下文拼系统提示；`get_tool_schemas(user)` 拼**权限作用域**的工具 schema；seed `messages=[{role:user, content:query}]`。
2. 定界循环（用户 `range(5)`、admin `range(6)`、节点 `range(4)`）：每轮 `llm.call_llm(messages, system, tools)`。
   - 无 `tool_calls` → 取 `text` 收尾 break。
   - 有 → 逐个派发：特殊名 `request_action` 引擎内拦截（永不到写手）；其余在 `TOOLS` 注册表查 `await func(db, user, input)`；结果 `json.dumps` 后作为合成 user 轮 `"[Tool Result]: ..."` 回灌。
   - `for/else` 耗尽 → `response_text="处理超时"`。
3. 算 `duration_ms`，写一条 `AgentLog`，`db.commit()`。

## 6.4 LLM 适配器（`agents/llm.py`）

- 模块常量读环境：`API_KEY=OPENROUTER_API_KEY`、`MODEL=LLM_MODEL`(默认 `z-ai/glm-5.1`)、`BASE_URL=LLM_BASE_URL`(默认 OpenRouter chat completions)；缺 key 只 `warnings.warn`，不硬失败。
- `call_llm` 把内部消息/工具形状转 OpenAI chat 格式，POST `{model,messages,max_tokens(默认2048),tools?}`（httpx 超时 60，Bearer 鉴权），规范化为 `{text, tool_calls:[{id,name,input}], tokens, stop_reason, raw}`；provider 报错被吞为 `{text:"LLM错误: ...", stop_reason:"error"}` 让循环优雅降级。

## 6.5 五个通用工具（`services/tools.py`）

| 工具 | 作用 |
|---|---|
| `query_data` | 按名查任意已注册表（表权限 + 公司过滤 + 精确 filters + 模糊 ILIKE + order_by + limit≤100）；行经 `_serialize_row` 字段防火墙 |
| `calculate` | 字符白名单(`0-9.+-*/() `)后 `eval` 数学表达式，其它字符拒绝 |
| `compare` | `float(a) OP float(b)`，固定 op 映射 |
| `aggregate` | SUM/COUNT/AVG/MAX/MIN（+group_by+filters），同表权限/公司闸 |
| `request_action` | **不在 TOOLS**：运行时作为 schema 注入、由循环内联处理，故 LLM 永不获得直接写能力 |

## 6.6 人确认闭环（ChangeCard）

LLM 发 `request_action{doc_type,doc_id?,to_state?,action_label?,field_updates?}` → 引擎调 `workflow.preview_transition(...)`（跑角色/边合法性/editable_fields/hard_rules 全部检查，**不写**）→ `_make_card` 产出卡片 → 追加到本次 `cards[]` 并告诉 LLM "已生成修改申请…等待用户确认"。**Agent 只提案、不提交**。人后续经 `POST /api/transition/commit` → `execute_command("workflow_commit_card")` → `commit_card` → `execute_transition` 真正落库。链条：**Agent 提案 → 人确认 → Command 引擎执行**。

## 6.7 权限/可见性闸（四层叠加）

(a) **表可见**：`_user_allowed_tables` 全权角色=全部，余者硬编白名单∪`_COMMON_TABLES`，未知落最小默认；`_visible_tables` 与 `table_map()` 取交集；可见集在运行时注入 `query_data/aggregate` 的 `table` schema 描述，明确告诉 LLM 能查什么。
(b) **注册暴露**：模型不声明 `__doc_types__/__queryable__` 即对 Agent 不可寻址。
(c) **行/公司**：`_company_filter`，非全权角色限本公司。
(d) **列防火墙**：`_serialize_row` 删买/卖价、口令哈希、`is_admin`。
此外可提案哪些推进由 `workflow.list_user_actions` 预算并嵌进 `request_action` 工具描述。

## 6.8 托管变体
- **管理员 Agent**（`admin_agent.py:242 admin_chat`）：同循环、不同工具集 `ADMIN_TOOLS`、`is_admin` 闸。
- **节点检查 Agent**（`agent.py:362`）：同循环界 4 轮，给只读工具 + 终结 `confirm_check`，返回 `{proceed,reason,steps}`，不确定/超限时安全默认 `proceed=True`。
- 三者共享 `call_llm`、`TOOLS` 派发约定、`AgentLog`。

## 6.9 数据契约（引擎级）

```
agent_log (models.py:1361): id, agent_type(USER|ADMIN|NODE), user_id, company_id,
  user_query, tools_called JSONB[{tool,params,result?}], response, tokens_used, duration_ms, timestamp(idx)

ChangeCard(瞬态): {card_id, doc_type, doc_id|null, from_state, to_state, action_label,
  transition_name, changes:[{field,from,to}], checks:[], recommendation:'proceed'|'reject', reason}
LLM 结果(瞬态): {text, tool_calls:[{id,name,input}], tokens, stop_reason:'tool_use'|'end_turn'|'error', raw}
SSE 事件(瞬态): {type:'thinking'|'tool_call'|'tool_result'|'done', elapsed_ms, ...}
request_action 入参: {doc_type(必), doc_id?, to_state?, action_label?, field_updates?}
```

## 6.10 接口

| 端点 | 说明 |
|---|---|
| `POST /api/agent/chat` | 自然语言 → 跑有界循环 → `{response,tools_called,cards,tokens_used,duration_ms}` |
| `POST /api/agent/chat/stream` | 同输入，回 `text/event-stream`（thinking/tool_call/tool_result/done，`Cache-Control:no-cache, X-Accel-Buffering:no`） |
| `POST /api/transition/preview` | 确定性预览，返回 ChangeCard 不写（Agent `request_action` 复用的同一原语） |
| `POST /api/transition/commit` | 人确认后经 Command 边界执行 ChangeCard |

## 6.11 功能需求

- **FR-6.1** 提供单一 LLM 适配器，面向任意 OpenAI 兼容 chat-completions 端点，model/base-url/key 全经环境变量，响应统一规范为 `{text,tool_calls[],tokens,stop_reason}`。
- **FR-6.2** 用有界工具调用循环（可配最大轮次）跑查询：按名在 (函数, JSON-schema) 注册表派发工具，结果回灌为对话轮，首个无工具调用轮或触界（给超时/安全默认）终止。
- **FR-6.3** 内置一小组业务无关读/算工具：查任意暴露表（filter/search/order/limit，限页大小）、聚合、沙箱算术（字符白名单）、两数比较。
- **FR-6.4** 须保证 Agent 永不写：任何拟变更须产出确定性"变更卡"（含 diff、检查结果、建议），并须显式带外人确认，经独立 command/执行边界重放。
- **FR-6.5** 所有数据访问须经叠加的声明式权限：每主体表级可见（全权 vs 按角色白名单 + 安全默认）、注册驱动的表暴露（模型须 opt-in 才可寻址）、行级租户作用域、列级敏感字段遮蔽。
- **FR-6.6** 须在请求时把各主体当前可见表清单注入相关工具 schema，明确告知模型可访问范围。
- **FR-6.7** 须同时提供单响应端点与 SSE 流式端点，发带耗时戳的 typed 进度事件（thinking/tool_call/tool_result/done）与流式友好响应头。
- **FR-6.8** 须每次运行写一条审计：agent 类型、主体、租户、输入查询、有序工具调用(参/果)、最终响应、token、时长、时间戳。
- **FR-6.9** 须支持在同循环/适配器上托管多 Agent 变体——换工具注册表 + 访问谓词（如特权配置 Agent、返回布尔判定+安全默认的咨询检查 Agent）。
- **FR-6.10** 须在运行时由可插拔上下文源（主体/角色上下文、可用动作、知识条目）组装系统提示，而非每 Agent 存静态提示。

## 6.12 边界：本模块明确排除的业务

- 8 个硬编角色描述与语义、`ROLE_ALLOWED_TABLES`、具体业务表名、买/卖价机密策略**内容**（防火墙机制是引擎、价语义是业务）。
- 用户 Agent 系统提示文案（"调度员"、公司简介…）、`金额加千分位`/中文应答等本地化指令。
- 管理员 Agent 的整套提示与 DSL 文档及 `ADMIN_TOOLS`（属流程定义引擎/管理面）。
- 节点检查 Agent 绑定具体业务状态的校验语义、`request_action` 的示例 doc_type。
- `KnowledgeEntry` 来源的 RULE/ALERT/SYSTEM_PROMPT 业务内容。
- `/api/transition/commit` 下游整套 Command/Workflow 执行引擎（独立子系统）。

## 6.13 现状与差距

- **D-06a** `tools.py` docstring 称"5 个通用工具"，TOOLS 实际只 4 个可调用（query/calculate/compare/aggregate）；第 5 个 `request_action` 故意不注册、由循环内联——只在"算上 request_action"时为 5。
- **D-06b** `AgentLog` 注释只列 `USER/NODE`，但 admin_chat 写 `agent_type='ADMIN'`——注释过期。
- **D-06c** `ROLE_ALLOWED_TABLES` 旁注称将迁 `role_definition` 表，**未实现**——当前无 DB 驱动表权限模型。
- **D-06d** 内部消息是 Anthropic 风格 block，但实际循环把工具结果摊平成 `[Tool Result]: ...` 纯文本轮——`call_llm` 的 block 转换分支对当前调用方是死路径。
- **D-06e** 无 `OPENROUTER_API_KEY` 时引擎照常启动、非 LLM 功能全可用，仅 Agent 端点请求期报 LLM 错误。
