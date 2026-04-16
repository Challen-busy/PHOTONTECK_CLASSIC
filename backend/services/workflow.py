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

from sqlalchemy import select, Boolean, Date, DateTime, Integer, Numeric, SmallInteger, BigInteger
from sqlalchemy.ext.asyncio import AsyncSession

import models as m


def _coerce_value(col, value):
    """把 JSON / LLM 卡片送来的字符串值转成列对应的 Python 类型。"""
    if value is None or col is None:
        return value
    t = col.type
    if isinstance(t, DateTime) and isinstance(value, str):
        if not value.strip():
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    if isinstance(t, Date) and isinstance(value, str):
        if not value.strip():
            return None
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return value
    if isinstance(t, (Integer, SmallInteger, BigInteger)) and isinstance(value, str):
        s = value.strip()
        if s == "":
            return None
        try:
            return int(s)
        except ValueError:
            return value
    if isinstance(t, Numeric) and isinstance(value, str):
        s = value.strip()
        if s == "":
            return None
        try:
            return Decimal(s)
        except (ValueError, ArithmeticError):
            return value
    if isinstance(t, Boolean) and isinstance(value, str):
        s = value.strip().lower()
        if s in ("true", "1", "yes", "y", "t"):
            return True
        if s in ("false", "0", "no", "n", "f", ""):
            return False
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
    from services.tools import TABLE_MAP
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

    # ========== 创建模式（B 模型：入 START 态，可带初始字段）==========
    if not doc_id:
        return await _create_blank(
            db, model, workflow, doc_type, user, comment, ip_address,
            field_updates=field_updates, sub_updates=sub_updates,
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
        # 编辑模式：允许所有出边可编辑字段的并集
        editable: set[str] = set()
        for n in (current_state.get("next") or []):
            editable.update(n.get("editable_fields") or [])
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
        from services.rules import evaluate_rules
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
        from services.hooks import execute_hooks_sync
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
    field_updates: dict | None = None, sub_updates: list | None = None,
) -> dict:
    """
    B 模型创建路径：入 START 态。
    - 接受 field_updates（业务外键如 supplier_id 必须由调用方提供）
    - 接受 sub_updates（明细行，外键自动指向新单据 id）
    - 系统字段自动填：status、company_id、created_by_id、*_number、可推断默认值
    """
    field_updates = field_updates or {}
    sub_updates = sub_updates or []

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

    for k, v in field_updates.items():
        if hasattr(model, k):
            col = model.__table__.columns.get(k)
            fields[k] = _coerce_value(col, v)

    auto = await _auto_fill_required_fields(db, model, fields, doc_type)
    fields.update(auto)

    try:
        doc = model(**{k: v for k, v in fields.items() if hasattr(model, k)})
        db.add(doc)
        await db.flush()

        sub_results = await _apply_sub_updates(db, sub_updates, doc.id) if sub_updates else []
        if sub_results:
            await db.flush()

        hook_log: list[str] = []
        hooks_to_run = list(target_state.get("hooks") or [])
        if hooks_to_run:
            from services.hooks import execute_hooks_sync
            hook_log = await db.run_sync(lambda s: execute_hooks_sync(s, doc, hooks_to_run))

        changed_fields = {k: {"old": "", "new": str(v)} for k, v in fields.items()}
        log = m.WorkflowLog(
            doc_type=doc_type, doc_id=doc.id,
            company_id=getattr(doc, "company_id", user.company_id),
            workflow_version=workflow.version,
            transition_name="创建",
            from_state="", to_state=target_state["code"],
            triggered_by_id=user.id,
            changed_fields={**changed_fields, "sub_changes": sub_results} if sub_results else changed_fields,
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
            "changed_fields": changed_fields,
            "sub_changes": sub_results,
            "log_id": log.id,
        }
    except Exception as e:
        await db.rollback()
        return {"success": False, "error": f"创建失败: {e}"}


# ============================================================
# 卡片协议（preview / commit）— 非 LLM，确定性两步提交
# ============================================================

def _json_safe(v):
    """把列值转成 JSON 兼容：date/datetime → ISO，Decimal → 字符串（保留精度）。
    int/str/bool/float/None 原样返回，类型不丢失。"""
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, Decimal):
        return str(v)
    return v


def _make_card(
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
        "transition_name": action_label,  # 兼容旧字段
        "changes": changes,
        "checks": checks,
        "recommendation": recommendation,
        "reason": reason,
    }


async def preview_transition(
    db: AsyncSession,
    doc_type: str,
    doc_id: int | None,
    to_state: str,
    action_label: str,
    user: m.UserAccount,
    field_updates: dict | None = None,
) -> dict:
    """确定性预览：角色 / editable / hard_rules 都检查一遍，返回卡片（不写库）。"""
    field_updates = field_updates or {}
    to_state = to_state or ""
    action_label = action_label or ""

    wf = await get_active_workflow(db, doc_type)
    if not wf:
        return _make_card(doc_type, doc_id, "", to_state, action_label or "未知", [], ["流程不存在"], "reject", "流程不存在")

    # 创建模式
    if not doc_id:
        initials = _initial_states(wf)
        target = next((s for s in initials if not to_state or s["code"] == to_state), None)
        if not target:
            return _make_card(doc_type, None, "", to_state, action_label or "创建", [],
                              ["找不到合适的初始节点"], "reject", "无法创建")
        checks = [f"创建模式：进入 '{target.get('name', target['code'])}'"]
        if user.role not in ("ADMIN", "BOSS") and target.get("allowed_roles") and user.role not in target["allowed_roles"]:
            return _make_card(doc_type, None, "", target["code"], action_label or "创建",
                              [], [f"角色 {user.role} 无权创建"], "reject", "角色无权")
        changes = [{"field": "status", "from": "", "to": target["code"]}]
        for field, val in field_updates.items():
            changes.append({"field": field, "from": None, "to": _json_safe(val)})
        return _make_card(doc_type, None, "", target["code"], action_label or "创建", changes, checks)

    # 加载已有单据
    model = DOC_MODEL_MAP.get(doc_type)
    doc = None
    if model:
        r = await db.execute(select(model).where(model.id == doc_id))
        doc = r.scalar_one_or_none()
    if not doc:
        return _make_card(doc_type, doc_id, "", to_state, action_label or "未知", [],
                          [f"{doc_type}#{doc_id}不存在"], "reject", "单据不存在")

    current_code = doc.status
    current_state = _find_state(wf, current_code)
    if not current_state:
        return _make_card(doc_type, doc_id, current_code, to_state, action_label or "未知", [],
                          [f"流程未定义状态 '{current_code}'"], "reject", "状态定义缺失")

    checks = [f"当前状态: {current_state.get('name', current_code)} ✓"]
    recommendation = "proceed"
    reason = ""

    state_roles = current_state.get("allowed_roles") or []
    if user.role not in ("ADMIN", "BOSS") and state_roles and user.role not in state_roles:
        return _make_card(doc_type, doc_id, current_code, to_state, action_label or "操作", [],
                          [f"角色校验: {user.role} 不在 {state_roles}"], "reject", "角色无权")
    checks.append(f"角色: {user.role} ✓")

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
            return _make_card(doc_type, doc_id, current_code, to_state, action_label or "推进", [],
                              [f"非法跳转 {current_code}→{to_state}"], "reject", "不允许此跳转")
        n_roles = next_entry.get("roles")
        if n_roles and user.role not in ("ADMIN", "BOSS") and user.role not in n_roles:
            return _make_card(doc_type, doc_id, current_code, to_state, action_label or next_entry.get("label", to_state), [],
                              [f"动作角色限制：需 {n_roles}"], "reject", "动作角色无权")
        new_status = to_state
        action_label = action_label or next_entry.get("label", to_state)
        editable = set(next_entry.get("editable_fields") or [])

    if field_updates and not editable:
        return _make_card(doc_type, doc_id, current_code, to_state, action_label or "操作", [],
                          ["当前动作不允许录入字段"], "reject", "无可编辑字段")
    for field in field_updates:
        if field not in editable:
            return _make_card(doc_type, doc_id, current_code, to_state, action_label or "操作", [],
                              [f"字段 {field} 在此动作不可编辑"], "reject", f"字段 {field} 不可编辑")

    changes = []
    if new_status != current_code:
        changes.append({"field": "status", "from": current_code, "to": new_status})
    for field, new_val in field_updates.items():
        old_val = getattr(doc, field, None)
        changes.append({
            "field": field,
            "from": _json_safe(old_val),
            "to": _json_safe(new_val),
        })

    rules_to_check = list(current_state.get("hard_rules") or [])
    if next_entry:
        rules_to_check.extend(next_entry.get("hard_rules") or [])
    if rules_to_check:
        from services.rules import evaluate_rules
        passed, failures = await evaluate_rules(db, doc, rules_to_check)
        if passed:
            checks.append(f"硬规则: {len(rules_to_check)} 条全部通过 ✓")
        else:
            checks.extend(failures)
            recommendation = "reject"
            reason = "硬规则未通过"

    return _make_card(doc_type, doc_id, current_code, new_status, action_label, changes, checks, recommendation, reason)


async def commit_card(
    db: AsyncSession,
    card: dict,
    user: m.UserAccount,
    comment: str = "",
    ip_address: str | None = None,
) -> dict:
    """执行用户已批准的卡片 — 把 changes 拆回 field_updates 后调 execute_transition。"""
    field_updates = {}
    for change in card.get("changes", []):
        if change["field"] != "status":
            field_updates[change["field"]] = change["to"]

    return await execute_transition(
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


async def list_user_actions(db: AsyncSession, user: m.UserAccount) -> list[dict]:
    """列出当前用户能触发的所有 (doc_type, from_state, next_action)。"""
    actions = []
    for doc_type in DOC_MODEL_MAP:
        wf = await get_active_workflow(db, doc_type)
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


_SUMMARY_STRING_FIELDS = (
    "order_number", "voucher_number", "shipment_number", "receipt_number",
    "contract_number", "invoice_number", "batch_number", "name", "code",
)
_SUMMARY_AMOUNT_FIELDS = ("total_amount", "amount", "total_cost", "quantity")


def _doc_summary(doc) -> str:
    parts = []
    for f in _SUMMARY_STRING_FIELDS:
        v = getattr(doc, f, None)
        if v:
            parts.append(str(v))
            break
    for f in _SUMMARY_AMOUNT_FIELDS:
        v = getattr(doc, f, None)
        if v is not None:
            try:
                parts.append(f"{float(v):,.0f}")
            except (TypeError, ValueError):
                parts.append(str(v))
            break
    cur = getattr(doc, "currency", None)
    if cur:
        parts.append(cur)
    return " · ".join(parts) if parts else f"#{doc.id}"


async def list_user_todos(db: AsyncSession, user: m.UserAccount) -> list[dict]:
    """当前用户的待办：遍历所有流程 × 角色可操作节点 × 该节点下的单据。

    多租户：只看 user.company_id。
    ADMIN / is_admin：系统管理员，豁免角色过滤，看所有非终态单据（便于全局调度）。
    其他角色（含 BOSS）：严格按 allowed_roles 匹配；allowed_roles 为空的节点视为"无限制"对所有人可见。
    """
    is_admin = bool(getattr(user, "is_admin", False)) or user.role == "ADMIN"
    todos = []
    for doc_type, model in DOC_MODEL_MAP.items():
        wf = await get_active_workflow(db, doc_type)
        if not wf:
            continue
        for s in (wf.states or []):
            if s.get("is_terminal"):
                continue
            roles = s.get("allowed_roles") or []
            if not is_admin and roles and user.role not in roles:
                continue
            stmt = select(model).where(
                model.status == s["code"],
                getattr(model, "company_id") == user.company_id,
            ).order_by(model.id.desc()).limit(200)
            r = await db.execute(stmt)
            docs = r.scalars().all()
            if not docs:
                continue
            actions = [
                {"label": n.get("label", n["to"]), "to_state": n["to"]}
                for n in (s.get("next") or [])
                if is_admin or not n.get("roles") or user.role in (n.get("roles") or [])
            ]
            for doc in docs:
                todos.append({
                    "doc_type": doc_type,
                    "doc_id": doc.id,
                    "workflow_id": wf.id,
                    "workflow_name": wf.name,
                    "state_code": s["code"],
                    "state_name": s.get("name", s["code"]),
                    "is_initial": bool(s.get("is_initial")),
                    "summary": _doc_summary(doc),
                    "actions": actions,
                    "updated_at": doc.updated_at.isoformat() if getattr(doc, "updated_at", None) else None,
                })
    return todos
