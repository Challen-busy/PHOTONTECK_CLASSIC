# 后端架构

PHOTONTECK 是一个面向 CRM / WMS / ERP / Finance 的通用业务底座。引擎本身不认识任何业务术语,所有业务模块通过**注册器**接入。

## 零、核心哲学

1. **业务 = 状态机 + 字段变更 + 副作用。**
   把业务拆成这三件事,各有归属、互不耦合。流程引擎只管状态机,Workflow 出边的 `editable_fields` 只管字段变更,Effect 注册器只管副作用。不允许把三者混在同一段代码里。

2. **引擎不认业务术语。**
   引擎里搜不到 "客户"、"库存"、"凭证"。CRM / WMS / ERP / Finance 在引擎眼里都是注册进来的插件 —— 想接入哪个行业就注册哪一套 Validator / Effect / Command,引擎自身永远不动。

3. **元数据是一等公民,代码是最后手段。**
   能用 `WorkflowDefinition.states` JSONB 表达的,不写代码;能用 `__doc_types__` 声明的,不维护映射表;能用注册器自动发现的,不写硬编 if-else。**改流程 ≈ 改一行 JSONB,不发版**。

4. **唯一写入路径。**
   所有跨模块写都走 `Command → Workflow → Domain` 这一条路。**没有捷径、没有后门**。这是幂等、事务、审计三件套能成立的前提 —— 任何绕过都会让这套底座崩塌。

5. **追溯优先于灵活。**
   `CommandLog` / `WorkflowLog` / `AgentLog` / `WorkflowDefAuditLog` 强制留痕,任何写动作都必须能被回放、能被归因。**"静默写" 在这套架构里是 bug,不是优化**。

6. **该硬编就硬编。**
   复式记账、会计科目、凭证借贷平衡这类业务不变量**故意不做元数据化** —— 因为它们不是"配置",是数学。把不变量假装成可配置项,就是给系统埋雷。元数据化只用在真正会因客户/行业不同而变的地方。

## 一、写入边界(只有三条路径)

跨模块的业务写动作只允许从这三层下去,严禁绕过:

1. **Command 层** —— `services/commands.py::execute_command`
   用户、Agent、系统操作的统一入口。承担命令日志、幂等性校验、事务边界、统一错误结构。命令通过 `@register_command` 装饰器注册。

2. **Workflow 层** —— `services/workflow.py::execute_transition`
   状态机推进、角色校验、`editable_fields` 白名单、硬规则(`hard_rules`)、待办、流程日志。流程触发的业务副作用必须以**已注册的 effects** 形式出现,不允许在流程定义里写内联写入钩子。

3. **Domain 层** —— `services/wms.py`、`services/phase1_effects.py`、`services/finance_commands.py` 等
   WMS / ERP / CRM / Finance 自有的业务不变式与数据变更。由 Command 直接调用,或被 Workflow effect 触发。

**允许的例外**:
- Admin/元数据写:用户、流程定义、知识条目,以及 admin 路由/admin agent 写的审计日志。
- 仅追加的运行时日志:`CommandLog`、`WorkflowLog`、`AgentLog`。
- Seed / migration 脚本。

## 二、流程引擎(元数据驱动)

唯一事实源:`WorkflowDefinition.states` 这个 JSONB 字段。**一张表一个字段就是整套流程**。

每个 state 节点结构:

```
code / name / is_initial / is_terminal
allowed_roles / editable_fields / hard_rules / agent_tools
hooks / effects
next: [{ to, label, editable_fields, hard_rules, effects }]
```

`execute_transition` 用 `to_state` 区分三种写入模式:

| 模式 | doc_id | to_state | 含义 |
|---|---|---|---|
| 创建 | None | 初始态 | 新建单据进入 `is_initial=True` 的状态 |
| 编辑 | 给 | 与当前态相同 / 不传 | 只改字段,不切状态 |
| 推进 | 给 | 在 `current.next` 中 | 改字段 + 切状态 |

字段级安全:`field_updates` 必须落在当前出边声明的 `editable_fields` 集合内,越界直接拒绝。

## 三、注册器:业务模块如何接入引擎

引擎不认业务术语。模块通过下列四个注册点把自己绑上去。

### 3.1 实体自动注册 —— `core/registry.py`

SQLAlchemy 模型上加约定:

- 主单据类:`__doc_types__ = ("SALES_ORDER",)`(元组,支持一类对应多 doc_type)
- 子表 / 主数据 / 日志:`__queryable__ = True`
- 内部表(权限映射、Admin 审计):不加任何标注,默认对 Agent 与流程引擎不可见

启动时 `doc_model_map()` / `table_map()` 扫描 `Base.registry.mappers` 一次并缓存。**Agent、流程引擎、前端流程图、数据浏览器、待办列表全部自动识别**,加新单据零额外硬编码。

### 3.2 Command 注册 —— `services/command_registry.py`

```python
@register_command(
    "reserve_inventory",
    module="WMS",
    affected_tables=("inventory", "inventory_reservation"),
)
async def reserve_inventory(ctx: CommandContext, payload: dict) -> dict:
    ...
```

注册命令自动获得幂等键、命令日志、事务边界、统一错误结构。当前 Command 模块清单:

- `WORKFLOW`:`workflow_transition`、`workflow_commit_card`
- `WMS`:11 个命令(预留 / 释放 / 自动分配 / 库存导入 / 盘点等)
- `FINANCE`:`create_accounts_receivable`、`create_accounts_payable`、`upsert_customer_credit`

### 3.3 Transition Validator(领域校验)

```python
@register_transition_validator(
    "wms.validate_shipment",
    doc_type="SHIPMENT",
    to_state="SALES_OUTBOUND",
)
async def validate_shipment(db, doc_type, doc, to_state, user) -> list[str]:
    return await wms.validate_shipment_constraints(db, doc)
```

引擎在进入推进流程时按 `(doc_type, to_state)` 匹配并执行所有 `auto=True` 的校验器;返回错误信息列表即可阻断。

### 3.4 Transition Effect(领域副作用)

```python
@register_transition_effect(
    "wms.apply_shipment_costs",
    doc_type="SHIPMENT",
    to_state="SALES_OUTBOUND",
)
async def apply_shipment_costs(db, doc_type, doc, to_state, user, command_log_id):
    ...
```

两种触发方式:

- `auto=True`:命中 `(doc_type, to_state)` 自动执行(如出库扣库存、入库结成本)
- `auto=False`:仅当流程节点的 JSONB 中显式声明 `effects: ["..."]` 才执行(如询价→报价、订单→采购通知 这类跨单据派生)

**CRM / WMS / ERP / Finance 跨模块的全链路打通在这一层完成**:
`phase1_effects.py` 串起了 询价 → 报价 → 销售订单 → 采购通知 → 采购单 → 预收/预付 → 入库 → 出库 → 发票 → 应收/应付 全流程。

## 四、横切能力

| 能力 | 位置 | 说明 |
|---|---|---|
| 规则 DSL | `services/rules.py` | AST 白名单,声明于 `state.hard_rules` / `next.hard_rules` |
| 钩子 DSL | `services/hooks.py` | 同上,默认禁用;新代码用 effects |
| Agent 工具 | `services/tools.py` | 5 个通用工具:`query` / `aggregate` / `calculate` / `compare` / `request_action`,所有写操作必须生成 ChangeCard 由人确认后再走 Command 落库 |
| 字段中文化 | `services/labels.py` | 表/字段 → 中文 label,Agent 与前端共用 |
| 多公司隔离 | `_company_filter(user)` 贯穿 commands / tools | 基于 `UserAccount.company_id` |

## 五、审计三本(追加,不可改)

| 表 | 写者 | 用途 |
|---|---|---|
| `CommandLog` | `execute_command` | 幂等键、原子边界、整命令回放 |
| `WorkflowLog` | `execute_transition` | 状态变更、字段 diff、hook/effect 执行轨迹 |
| `AgentLog` | `agents/agent.py` | LLM 调用、工具调用、ChangeCard 提案 |

配置面有 `WorkflowDefAuditLog`(配置变更前后快照),运行面有上面三本。配置与运行两条线均可完整回溯。

## 六、迁移开关

写入钩子默认禁用。`ALLOW_LEGACY_WORKFLOW_WRITE_HOOKS=1` 只用于跑迁移期残留的老流程定义;新增或维护的业务流必须使用已注册的 effects 或 commands。

## 七、扩展一个新业务的代价

| 改动 | 工作量 |
|---|---|
| 新增 doc_type | `models.py` 加类并写 `__doc_types__`;alembic 迁移;插一行 `WorkflowDefinition` |
| 新增跨模块命令 | 一个 `@register_command` 函数 |
| 新增流程校验 | 一个 `@register_transition_validator` 函数 |
| 新增流程副作用 | 一个 `@register_transition_effect` 函数;auto=False 时还要在 state JSONB 的 `effects` 数组里列出来 |

**不应该改动**的部分:引擎本身、Command 框架、Registry、审计三本。这是判断"是否走对了通用化方向"的硬标准。
