"""
第二层：流程引擎（极简版）

execute_transition = 唯一写入点
流程定义只有 WorkflowDefinition.states JSONB（一张表一个字段）

三种写入模式（用 to_state 区分）：
  - 创建: doc_id=None → 新建单据进入某个 is_initial=True 的状态
  - 编辑: 不传 to_state（或与当前状态相同）→ 改字段不改状态
  - 推进: to_state 给出且在当前 state.next 中 → 改字段并切换状态

每个 state 包含：
  code/name/is_initial/is_terminal/allowed_roles/editable_fields
  description/agent_tools/custom_html/hard_rules/next
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select, Date, DateTime
from sqlalchemy.ext.asyncio import AsyncSession

import models as m


def _coerce_value(col, value):
    """把 JSON 送来的字符串日期/日期时间转成 date/datetime 对象"""
    if value is None or col is None:
        return value
    t = col.type
    if isinstance(t, DateTime) and isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    if isinstance(t, Date) and isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return value
    return value


# 单据类型 → 模型映射
DOC_MODEL_MAP = {
    "SALES_ORDER": m.SalesOrder,
    "PURCHASE_ORDER": m.PurchaseOrder,
    "SHIPMENT": m.ShipmentRequest,
    "VOUCHER": m.Voucher,
    "GOODS_RECEIPT": m.GoodsReceipt,
    "CUSTOMER": m.Customer,
    "SUPPLIER": m.Supplier,
    "PROJECT": m.Project,
    "FRAMEWORK_CONTRACT": m.FrameworkContract,
    "ACCOUNTS_RECEIVABLE": m.AccountsReceivable,
    "ACCOUNTS_PAYABLE": m.AccountsPayable,
    "INVENTORY": m.Inventory,
    "INVENTORY_VIRTUAL": m.Inventory,
    "INVENTORY_COUNT": m.Inventory,
    "INVENTORY_COSTING": m.InventoryTransaction,
    "VOUCHER_ADJUSTMENT": m.Voucher,
}


def _serialize_doc(doc) -> dict:
    d = {}
    for col in doc.__table__.columns:
        val = getattr(doc, col.name)
        if isinstance(val, Decimal):
            val = float(val)
        elif hasattr(val, "isoformat"):
            val = val.isoformat()
        d[col.name] = val
    return d


async def get_active_workflow(db: AsyncSession, doc_type: str) -> m.WorkflowDefinition | None:
    stmt = select(m.WorkflowDefinition).where(
        m.WorkflowDefinition.doc_type == doc_type,
        m.WorkflowDefinition.is_active == True,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


def _find_state(workflow: m.WorkflowDefinition, code: str) -> dict | None:
    for s in (workflow.states or []):
        if s.get("code") == code:
            return s
    return None


def _initial_states(workflow: m.WorkflowDefinition) -> list[dict]:
    return [s for s in (workflow.states or []) if s.get("is_initial")]


async def get_user_actions_at_state(
    db: AsyncSession, doc_type: str, current_state: str, user_role: str
) -> list[dict]:
    """返回当前状态下用户可执行的动作（next 列表里他角色能执行的）"""
    workflow = await get_active_workflow(db, doc_type)
    if not workflow:
        return []
    state = _find_state(workflow, current_state)
    if not state:
        return []
    # ADMIN/BOSS 不受限
    if user_role not in ("ADMIN", "BOSS"):
        if state.get("allowed_roles") and user_role not in state["allowed_roles"]:
            return []
    return list(state.get("next") or [])


async def _auto_fill_required_fields(db, model, provided: dict, doc_type: str) -> dict:
    """
    为单据自动填充有意义的默认值：
      - *_number 列（标识符）即使 nullable 也生成 UUID 前缀（每单都该有号）
      - 其他 NOT NULL 且无默认值的列，给兜底值避开 DB 报错
    """
    defaults = {}
    prefix = doc_type.replace("_", "")[:4].upper()
    ts = date.today().strftime("%y%m%d")
    for col in model.__table__.columns:
        if col.name in provided or col.primary_key:
            continue
        # *_number 是单据标识，永远自动生成（即使 nullable）
        if col.name.endswith("_number") or col.name == "number":
            if col.name not in provided:
                defaults[col.name] = f"{prefix}-{ts}-{str(uuid.uuid4())[:6].upper()}"
            continue
        # 其他 nullable 的放着就行
        if col.nullable or col.default is not None or col.server_default is not None:
            continue
        # 剩下 NOT NULL + 无默认值 → 兜底
        if col.name == "period_id":
            r = await db.execute(select(m.AccountingPeriod).limit(1))
            p = r.scalar_one_or_none()
            if p:
                defaults[col.name] = p.id
        elif "date" in col.name:
            defaults[col.name] = date.today()
        elif col.name in (
            "quantity", "unit_price", "total_price", "amount", "credit_limit",
            "debit", "credit", "total_debit", "total_credit", "total_amount",
        ):
            defaults[col.name] = 0
    return defaults


async def _apply_sub_updates(db, sub_updates: list, parent_id: int) -> list[str]:
    from tools import TABLE_MAP
    changes = []
    for sub in sub_updates or []:
        sub_model = TABLE_MAP.get(sub.get("table"))
        if not sub_model:
            continue
        if sub.get("_delete"):
            r = await db.execute(select(sub_model).where(sub_model.id == sub["id"]))
            obj = r.scalar_one_or_none()
            if obj:
                await db.delete(obj)
                changes.append(f"删除{sub['table']}#{sub['id']}")
        elif sub.get("id"):
            r = await db.execute(select(sub_model).where(sub_model.id == sub["id"]))
            obj = r.scalar_one_or_none()
            if obj:
                for k, v in sub.get("fields", {}).items():
                    if hasattr(obj, k):
                        col = sub_model.__table__.columns.get(k)
                        v = _coerce_value(col, v)
                        setattr(obj, k, v)
                changes.append(f"更新{sub['table']}#{sub['id']}")
        else:
            fields = {**sub.get("fields", {})}
            parent_fk = sub.get("parent_fk")
            if parent_fk and parent_id:
                fields[parent_fk] = parent_id
            coerced = {}
            for k, v in fields.items():
                if hasattr(sub_model, k):
                    col = sub_model.__table__.columns.get(k)
                    coerced[k] = _coerce_value(col, v)
            obj = sub_model(**coerced)
            db.add(obj)
            changes.append(f"新增{sub['table']}")
    return changes


async def execute_transition(
    db: AsyncSession,
    doc_type: str,
    doc_id: int | None,
    user: m.UserAccount,
    to_state: str | None = None,
    action_label: str = "",
    field_updates: dict | None = None,
    sub_updates: list | None = None,
    comment: str = "",
    ip_address: str | None = None,
) -> dict:
    """
    唯一写入点。

    doc_id=None → 创建：to_state 指定初始状态（或自动选唯一的 is_initial）
    to_state 与当前状态相同/未传 → 编辑：只改字段
    to_state 在 current.next 中 → 推进：改字段+切状态
    """
    field_updates = field_updates or {}
    sub_updates = sub_updates or []

    model = DOC_MODEL_MAP.get(doc_type)
    if not model:
        return {"success": False, "error": f"不支持的单据类型: {doc_type}"}

    workflow = await get_active_workflow(db, doc_type)
    if not workflow:
        return {"success": False, "error": f"{doc_type} 没有活跃的流程定义"}

    # ========== 创建模式（B 模型：空 doc 入 START 态，无字段录入）==========
    if not doc_id:
        if field_updates or sub_updates:
            return {"success": False, "error": "创建时不接受字段，请在首个业务节点录入"}
        return await _create_blank(
            db, model, workflow, doc_type, user, comment, ip_address,
        )

    # ========== 加载已有单据 ==========
    stmt = select(model).where(model.id == doc_id)
    result = await db.execute(stmt)
    doc = result.scalar_one_or_none()
    if not doc:
        return {"success": False, "error": f"{doc_type}#{doc_id} 不存在"}

    current_state_code = doc.status
    current_state = _find_state(workflow, current_state_code)
    if not current_state:
        return {"success": False, "error": f"流程未定义状态 '{current_state_code}'"}

    # 角色校验（节点级）
    if user.role not in ("ADMIN", "BOSS") and current_state.get("allowed_roles") \
            and user.role not in current_state["allowed_roles"]:
        return {"success": False, "error": f"角色 '{user.role}' 无权在 '{current_state.get('name', current_state_code)}' 操作"}

    # 决定新状态 + 定位出边（editable 挂在出边上，先找到出边再校验字段）
    next_entry = None
    if not to_state or to_state == current_state_code:
        new_status = current_state_code
        action_label = action_label or "编辑"
        # 无出边 = 没有可编辑字段（需要推进才能改）
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
            return {"success": False, "error": f"非法跳转: '{current_state_code}' 不能直接到 '{to_state}'"}
        new_status = to_state
        action_label = action_label or next_entry.get("label", to_state)
        editable = set(next_entry.get("editable_fields") or [])

    # 字段校验（按出边允许的字段）
    if field_updates and not editable:
        return {"success": False, "error": "当前动作不允许录入字段"}
    for field in field_updates:
        if field not in editable:
            return {"success": False, "error": f"字段 '{field}' 在动作 '{action_label}' 不可编辑"}

    # 修改前快照（含老字段值，给规则用 old vs new 也能查）
    old_snapshot = _serialize_doc(doc)

    # 应用字段（先记录老值，再设新值）
    changed_fields = {}
    for field, value in field_updates.items():
        if hasattr(doc, field):
            col = model.__table__.columns.get(field)
            value = _coerce_value(col, value)
            old_val = getattr(doc, field)
            setattr(doc, field, value)
            changed_fields[field] = {"old": str(old_val), "new": str(value)}

    # 子表（同样先应用，让规则能看到全貌）
    sub_results = await _apply_sub_updates(db, sub_updates, doc_id)
    await db.flush()  # 让子表新增/修改对规则查询可见

    # 硬规则校验：state.hard_rules + 当前 next_entry.hard_rules
    rules_to_check = list(current_state.get("hard_rules") or [])
    if next_entry:
        rules_to_check.extend(next_entry.get("hard_rules") or [])
    if rules_to_check:
        from rules import evaluate_rules
        passed, failures = await evaluate_rules(db, doc, rules_to_check)
        if not passed:
            await db.rollback()
            return {
                "success": False,
                "error": "自动校验未通过",
                "rule_failures": failures,
            }

    # 状态推进（在钩子前，使钩子可见到新状态）
    if current_state_code != new_status:
        changed_fields["status"] = {"old": current_state_code, "new": new_status}
        doc.status = new_status

    if hasattr(doc, "updated_by_id"):
        doc.updated_by_id = user.id

    # 钩子执行：state.hooks + 当前 next_entry.hooks（commit 前，失败回滚全部）
    hooks_to_run = list(current_state.get("hooks") or [])
    if next_entry:
        hooks_to_run.extend(next_entry.get("hooks") or [])
    # 如果进入新状态，也跑新状态的 hooks（"进入该态"语义）
    if current_state_code != new_status:
        entered_state = _find_state(workflow, new_status)
        if entered_state:
            hooks_to_run.extend(entered_state.get("hooks") or [])
    hook_log: list[str] = []
    if hooks_to_run:
        from hooks import execute_hooks_sync
        try:
            await db.flush()
            hook_log = await db.run_sync(lambda s: execute_hooks_sync(s, doc, hooks_to_run))
        except Exception as e:
            await db.rollback()
            return {"success": False, "error": f"钩子执行失败: {e}"}

    log = m.WorkflowLog(
        doc_type=doc_type, doc_id=doc_id,
        company_id=getattr(doc, "company_id", user.company_id),
        workflow_version=workflow.version,
        transition_name=action_label,
        from_state=current_state_code, to_state=new_status,
        triggered_by_id=user.id,
        changed_fields={**changed_fields, "sub_changes": sub_results} if sub_results else changed_fields,
        data_snapshot=old_snapshot,
        hooks_executed=hook_log,
        comment=comment,
        ip_address=ip_address,
    )
    db.add(log)
    await db.commit()

    return {
        "success": True,
        "doc_type": doc_type, "doc_id": doc_id,
        "action": action_label,
        "from_state": current_state_code, "to_state": new_status,
        "changed_fields": changed_fields,
        "sub_changes": sub_results,
        "hooks_executed": hook_log,
        "log_id": log.id,
    }


async def _create_blank(
    db, model, workflow, doc_type, user, comment, ip_address,
) -> dict:
    """
    B 模型创建路径：只建空行。
    - 不接受 field_updates / sub_updates（由主路径处理）
    - 单据入 is_initial=True 的状态（约定为 START）
    - 系统字段自动填：status、company_id、created_by_id、NOT NULL 默认值
    """
    initials = _initial_states(workflow)
    if not initials:
        return {"success": False, "error": f"{doc_type} 流程没有起始节点"}
    if len(initials) > 1:
        return {"success": False, "error": f"{doc_type} 有多个起始节点: {[s['code'] for s in initials]}"}
    target_state = initials[0]

    if user.role not in ("ADMIN", "BOSS") and target_state.get("allowed_roles") \
            and user.role not in target_state["allowed_roles"]:
        return {"success": False, "error": f"角色 '{user.role}' 无权创建 '{doc_type}'"}

    fields = {}
    if hasattr(model, "status"):
        fields["status"] = target_state["code"]
    if hasattr(model, "company_id"):
        fields["company_id"] = user.company_id
    if hasattr(model, "created_by_id"):
        fields["created_by_id"] = user.id

    auto = await _auto_fill_required_fields(db, model, fields, doc_type)
    fields.update(auto)

    try:
        doc = model(**{k: v for k, v in fields.items() if hasattr(model, k)})
        db.add(doc)
        await db.flush()

        hook_log: list[str] = []
        hooks_to_run = list(target_state.get("hooks") or [])
        if hooks_to_run:
            from hooks import execute_hooks_sync
            hook_log = await db.run_sync(lambda s: execute_hooks_sync(s, doc, hooks_to_run))

        log = m.WorkflowLog(
            doc_type=doc_type, doc_id=doc.id,
            company_id=getattr(doc, "company_id", user.company_id),
            workflow_version=workflow.version,
            transition_name="创建",
            from_state="", to_state=target_state["code"],
            triggered_by_id=user.id,
            changed_fields={k: {"old": "", "new": str(v)} for k, v in fields.items()},
            data_snapshot={},
            hooks_executed=hook_log,
            comment=comment or f"创建{doc_type}",
            ip_address=ip_address,
        )
        db.add(log)
        await db.commit()
        await db.refresh(doc)

        return {
            "success": True, "doc_type": doc_type, "doc_id": doc.id,
            "action": "创建",
            "from_state": "", "to_state": target_state["code"],
            "changed_fields": {k: {"old": "", "new": str(v)} for k, v in fields.items()},
            "sub_changes": [],
            "log_id": log.id,
        }
    except Exception as e:
        await db.rollback()
        return {"success": False, "error": f"创建失败: {e}"}
