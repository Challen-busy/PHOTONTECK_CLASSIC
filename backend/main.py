"""
主入口 — 整个系统的10个API端点

认证:    POST /api/login  GET /api/me
数据:    POST /api/query
流程:    POST /api/transition  GET /api/transitions  GET /api/history/{type}/{id}
Agent:   POST /api/agent/chat  POST /api/agent/confirm  GET /api/agent/list
知识库:  GET /api/knowledge
"""

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.sessions import SessionMiddleware

import agent
import models as m
import workflow
from fastapi import Depends, FastAPI, HTTPException, Request
from auth import authenticate, get_current_user, hash_password
from database import get_db
from tools import TOOLS

app = FastAPI(title="PHOTONTECK", version="2.0")

app.add_middleware(SessionMiddleware, secret_key="photonteck-session-secret-change-in-prod")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


# ============================================================
# 认证
# ============================================================

class LoginRequest(BaseModel):
    username: str
    password: str

@app.post("/api/login")
async def login(req: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    user = await authenticate(db, req.username, req.password)
    if not user:
        return {"error": "用户名或密码错误"}
    request.session["user_id"] = user.id
    return {"id": user.id, "username": user.username, "full_name": user.full_name,
            "role": user.role, "company_id": user.company_id, "is_admin": user.is_admin}

@app.post("/api/logout")
async def logout(request: Request):
    request.session.clear()
    return {"ok": True}

@app.get("/api/me")
async def me(user: m.UserAccount = Depends(get_current_user)):
    return {"id": user.id, "username": user.username, "full_name": user.full_name,
            "role": user.role, "company_id": user.company_id, "is_admin": user.is_admin}


# ============================================================
# 通用数据查询
# ============================================================

class QueryRequest(BaseModel):
    table: str
    filters: dict = {}
    search: str = ""
    order_by: str = "id"
    limit: int = 20

@app.post("/api/query")
async def query(req: QueryRequest, db: AsyncSession = Depends(get_db), user: m.UserAccount = Depends(get_current_user)):
    result = await TOOLS["query_data"]["function"](db, user, req.model_dump())
    return result

class AggregateRequest(BaseModel):
    table: str
    field: str
    function: str = "COUNT"
    filters: dict = {}
    group_by: str = ""

@app.post("/api/aggregate")
async def agg(req: AggregateRequest, db: AsyncSession = Depends(get_db), user: m.UserAccount = Depends(get_current_user)):
    result = await TOOLS["aggregate"]["function"](db, user, req.model_dump())
    return result


# ============================================================
# 流程
# ============================================================

class TransitionRequest(BaseModel):
    doc_type: str
    doc_id: int | None = None       # None/0 = 创建
    to_state: str | None = None     # 不传 = 编辑（不改状态）；传 = 推进到该状态
    action_label: str = ""           # 可选，用于多路径同target的区分（仅日志）
    field_updates: dict = {}
    sub_updates: list = []
    comment: str = ""

@app.post("/api/transition")
async def transition(req: TransitionRequest, request: Request, db: AsyncSession = Depends(get_db), user: m.UserAccount = Depends(get_current_user)):
    result = await workflow.execute_transition(
        db=db, doc_type=req.doc_type, doc_id=req.doc_id,
        to_state=req.to_state, action_label=req.action_label, user=user,
        field_updates=req.field_updates, sub_updates=req.sub_updates, comment=req.comment,
        ip_address=request.client.host if request.client else None,
    )
    return result

@app.get("/api/transitions")
async def transitions(db: AsyncSession = Depends(get_db), user: m.UserAccount = Depends(get_current_user)):
    actions = await agent._get_user_actions(db, user)
    return actions

@app.get("/api/history/{doc_type}/{doc_id}")
async def history(doc_type: str, doc_id: int, db: AsyncSession = Depends(get_db), user: m.UserAccount = Depends(get_current_user)):
    stmt = select(m.WorkflowLog).where(
        m.WorkflowLog.doc_type == doc_type,
        m.WorkflowLog.doc_id == doc_id,
    ).order_by(m.WorkflowLog.timestamp)
    result = await db.execute(stmt)
    logs = result.scalars().all()
    return [
        {
            "id": l.id, "transition": l.transition_name,
            "from_state": l.from_state, "to_state": l.to_state,
            "triggered_by_id": l.triggered_by_id,
            "timestamp": l.timestamp.isoformat() if l.timestamp else None,
            "changed_fields": l.changed_fields,
            "comment": l.comment,
        }
        for l in logs
    ]


# ============================================================
# Agent
# ============================================================

# 用户Agent对话 → 返回回复 + 修改卡片
class ChatRequest(BaseModel):
    query: str

@app.post("/api/agent/chat")
async def agent_chat(req: ChatRequest, db: AsyncSession = Depends(get_db), user: m.UserAccount = Depends(get_current_user)):
    return await agent.chat(db, req.query, user)

# 节点Agent检查（前端直接调用）→ 返回修改卡片
class CheckRequest(BaseModel):
    doc_type: str
    doc_id: int
    to_state: str
    action_label: str = ""
    field_updates: dict = {}

@app.post("/api/agent/check")
async def agent_check(req: CheckRequest, db: AsyncSession = Depends(get_db), user: m.UserAccount = Depends(get_current_user)):
    card = await agent.check_node(db, req.doc_type, req.doc_id, req.to_state, req.action_label, user, req.field_updates)
    return card

# 执行已批准的卡片
class ExecuteCardRequest(BaseModel):
    card: dict
    comment: str = ""

@app.post("/api/agent/execute")
async def agent_execute(req: ExecuteCardRequest, request: Request, db: AsyncSession = Depends(get_db), user: m.UserAccount = Depends(get_current_user)):
    return await agent.execute_card(db, req.card, user, req.comment, request.client.host if request.client else None)


# ============================================================
# 知识库
# ============================================================

@app.get("/api/knowledge")
async def knowledge(db: AsyncSession = Depends(get_db), user: m.UserAccount = Depends(get_current_user)):
    stmt = select(m.KnowledgeEntry).where(m.KnowledgeEntry.is_active == True)
    result = await db.execute(stmt)
    entries = result.scalars().all()
    return [
        {
            "id": e.id, "type": e.entry_type, "title": e.title, "content": e.content,
            "applicable_doc_types": e.applicable_doc_types,
        }
        for e in entries
    ]


# ============================================================
# 管理员端点
# ============================================================

# --- 元数据: 返回表的schema(字段/类型/外键/子表) ---
@app.get("/api/schema/{table_name}")
async def get_schema(table_name: str, user: m.UserAccount = Depends(get_current_user)):
    from database import Base
    from tools import TABLE_MAP
    from labels import get_label

    model = TABLE_MAP.get(table_name)
    if not model:
        raise HTTPException(status_code=404, detail=f"表 {table_name} 不存在")

    fields = []
    for col in model.__table__.columns:
        field_type = str(col.type)
        # 简化类型
        if "INT" in field_type.upper(): type_name = "integer"
        elif "NUMERIC" in field_type.upper() or "FLOAT" in field_type.upper() or "DECIMAL" in field_type.upper():
            type_name = "number"
        elif "DATE" in field_type.upper() and "TIME" in field_type.upper(): type_name = "datetime"
        elif "DATE" in field_type.upper(): type_name = "date"
        elif "BOOL" in field_type.upper(): type_name = "boolean"
        elif "JSON" in field_type.upper(): type_name = "json"
        elif "TEXT" in field_type.upper(): type_name = "text"
        else: type_name = "string"

        # 外键目标
        fk_target = None
        if col.foreign_keys:
            fk = list(col.foreign_keys)[0]
            fk_target = {"table": fk.column.table.name, "column": fk.column.name}

        fields.append({
            "name": col.name,
            "label": get_label(table_name, col.name),
            "type": type_name,
            "nullable": col.nullable,
            "primary_key": col.primary_key,
            "fk": fk_target,
            "has_default": col.default is not None or col.server_default is not None,
        })

    # 检测反向关系（子表）- 查找哪些表的FK指向本表
    from labels import get_table_label
    sub_tables = []
    for t_name, t_model in TABLE_MAP.items():
        if t_name == table_name:
            continue
        for col in t_model.__table__.columns:
            if col.foreign_keys:
                fk = list(col.foreign_keys)[0]
                if fk.column.table.name == table_name:
                    if any(x in t_name for x in ["_line", "_entry"]):
                        sub_tables.append({
                            "table": t_name,
                            "table_label": get_table_label(t_name),
                            "parent_fk": col.name,
                        })
                    break

    return {
        "table": table_name,
        "table_label": get_table_label(table_name),
        "fields": fields,
        "sub_tables": sub_tables,
    }


# --- 关联数据探索（FK 一跳）---
SKIP_FK_FIELDS = {"created_by_id", "updated_by_id", "company_id"}
SUBTABLE_HINTS = ("_line", "_entry")

@app.get("/api/related/{table_name}/{doc_id}")
async def get_related(table_name: str, doc_id: int, db: AsyncSession = Depends(get_db), user: m.UserAccount = Depends(get_current_user)):
    """
    自动探索一张单据的关联数据：
    - forward: 这张单引用的对象（FK → 单条 row）
    - reverse: 引用这张单的其他表（反向 FK → count + samples）
    """
    from tools import TABLE_MAP, _serialize_row
    model = TABLE_MAP.get(table_name)
    if not model:
        return {"error": "表不存在"}
    r = await db.execute(select(model).where(model.id == doc_id))
    doc = r.scalar_one_or_none()
    if not doc:
        return {"error": "单据不存在"}

    # === Forward FKs ===
    from labels import get_label, get_table_label
    forward = []
    for col in model.__table__.columns:
        if col.name in SKIP_FK_FIELDS or not col.foreign_keys:
            continue
        fk_val = getattr(doc, col.name, None)
        if fk_val is None:
            continue
        fk = list(col.foreign_keys)[0]
        target_table = fk.column.table.name
        target_model = TABLE_MAP.get(target_table)
        if not target_model:
            continue
        rr = await db.execute(select(target_model).where(target_model.id == fk_val))
        target_row = rr.scalar_one_or_none()
        if not target_row:
            continue
        try:
            row_data = _serialize_row(target_row, target_table, user)
        except Exception:
            continue
        forward.append({
            "field": col.name,
            "target_table": target_table,
            "target_table_label": get_table_label(target_table),
            "labels": {c.name: get_label(target_table, c.name) for c in target_model.__table__.columns},
            "row": row_data,
        })

    # === Reverse FKs ===
    reverse = []
    for sub_name, sub_model in TABLE_MAP.items():
        if sub_name == table_name:
            continue
        for col in sub_model.__table__.columns:
            if not col.foreign_keys:
                continue
            fk = list(col.foreign_keys)[0]
            if fk.column.table.name != table_name:
                continue
            # 子表（_line/_entry）不在反向里展示，因为已在子表区
            if any(h in sub_name for h in SUBTABLE_HINTS):
                break
            # 公司过滤
            stmt = select(sub_model).where(getattr(sub_model, col.name) == doc_id)
            from tools import _company_filter
            company_ids = _company_filter(user)
            if company_ids and hasattr(sub_model, "company_id"):
                stmt = stmt.where(sub_model.company_id.in_(company_ids))
            rr = await db.execute(stmt.limit(5))
            samples = []
            for row in rr.scalars().all():
                try:
                    samples.append(_serialize_row(row, sub_name, user))
                except Exception:
                    continue
            # 总数
            from sqlalchemy import func
            count_stmt = select(func.count()).select_from(sub_model).where(getattr(sub_model, col.name) == doc_id)
            if company_ids and hasattr(sub_model, "company_id"):
                count_stmt = count_stmt.where(sub_model.company_id.in_(company_ids))
            total = (await db.execute(count_stmt)).scalar()
            if total > 0 or samples:
                sub_labels = {c.name: get_label(sub_name, c.name) for c in sub_model.__table__.columns}
                # 解析 sample 里的 FK 值 → 中文名
                resolved = {}
                for sc in sub_model.__table__.columns:
                    if sc.name in SKIP_FK_FIELDS or sc.name == col.name or not sc.foreign_keys:
                        continue
                    target = list(sc.foreign_keys)[0].column.table.name
                    target_m = TABLE_MAP.get(target)
                    if not target_m:
                        continue
                    ids = {s[sc.name] for s in samples if s.get(sc.name) is not None}
                    if not ids:
                        continue
                    rr2 = await db.execute(select(target_m).where(target_m.id.in_(ids)))
                    id_to_label = {}
                    for row in rr2.scalars().all():
                        for f in ("name", "full_name", "short_name", "code", "sku", "order_number",
                                  "voucher_number", "invoice_number", "batch_number"):
                            v = getattr(row, f, None)
                            if v:
                                id_to_label[row.id] = v
                                break
                        else:
                            id_to_label[row.id] = f"#{row.id}"
                    resolved[sc.name] = id_to_label
                reverse.append({
                    "table": sub_name,
                    "table_label": get_table_label(sub_name),
                    "fk_field": col.name,
                    "count": total,
                    "samples": samples,
                    "labels": sub_labels,
                    "fk_resolved": resolved,
                })
            break

    return {"forward": forward, "reverse": reverse}


# --- 流程定义（所有用户可看，仅 active）---
@app.get("/api/workflows")
async def list_workflows(db: AsyncSession = Depends(get_db), user: m.UserAccount = Depends(get_current_user)):
    result = await db.execute(
        select(m.WorkflowDefinition)
        .where(m.WorkflowDefinition.is_active == True)
        .order_by(m.WorkflowDefinition.group_name, m.WorkflowDefinition.doc_type)
    )
    wfs = result.scalars().all()
    return [
        {
            "id": wf.id, "doc_type": wf.doc_type, "name": wf.name, "version": wf.version,
            "description": wf.description,
            "states": wf.states,
            "node_positions": wf.node_positions or {},
            "group_name": wf.group_name or "",
            "is_published": wf.is_published,
        }
        for wf in wfs
    ]

# --- 预警 ---
@app.get("/api/alerts")
async def alerts_check(user: m.UserAccount = Depends(get_current_user)):
    from alerts import run_all_alerts
    results = await run_all_alerts()
    return results

# --- 专用页面模板 ---
@app.get("/api/templates/{name}")
async def get_template(name: str):
    from pathlib import Path
    path = Path(__file__).parent / "templates" / f"{name}.html"
    if not path.exists():
        return {"html": ""}
    return {"html": path.read_text(encoding="utf-8")}

# --- 获取节点详情(含 description / custom_html) ---
@app.get("/api/state-detail/{doc_type}/{state_code}")
async def state_detail(doc_type: str, state_code: str, db: AsyncSession = Depends(get_db), user: m.UserAccount = Depends(get_current_user)):
    wf = await workflow.get_active_workflow(db, doc_type)
    if not wf:
        return {"error": "流程不存在"}
    state = next((s for s in (wf.states or []) if s.get("code") == state_code), None)
    if not state:
        return {"error": "节点不存在"}
    return state

# --- 流程创建Agent（超级管理员专用）---
class AdminChatRequest(BaseModel):
    query: str

@app.post("/api/admin/agent/chat")
async def admin_agent_chat(req: AdminChatRequest, db: AsyncSession = Depends(get_db), user: m.UserAccount = Depends(get_current_user)):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    from admin_agent import admin_chat
    return await admin_chat(db, req.query, user)

def require_admin(user: m.UserAccount = Depends(get_current_user)):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user

# --- 保存流程图节点坐标 ---
class SavePositionsRequest(BaseModel):
    workflow_id: int
    positions: dict

@app.post("/api/admin/save-positions")
async def save_positions(req: SavePositionsRequest, request: Request, db: AsyncSession = Depends(get_db), admin: m.UserAccount = Depends(require_admin)):
    result = await db.execute(select(m.WorkflowDefinition).where(m.WorkflowDefinition.id == req.workflow_id))
    wf = result.scalar_one_or_none()
    if not wf:
        return {"error": "流程不存在"}
    wf.node_positions = req.positions
    await _audit(db, request, admin, req.workflow_id, "save_positions",
                 summary=f"更新节点布局 ({len(req.positions)} 个节点)")
    await db.commit()
    return {"ok": True, "workflow_id": wf.id}

# --- 用户管理 ---
@app.get("/api/admin/users")
async def admin_users(db: AsyncSession = Depends(get_db), admin: m.UserAccount = Depends(require_admin)):
    result = await db.execute(select(m.UserAccount).order_by(m.UserAccount.id))
    return [{"id": u.id, "username": u.username, "full_name": u.full_name, "role": u.role,
             "company_id": u.company_id, "is_admin": u.is_admin, "is_active": u.is_active}
            for u in result.scalars().all()]

class CreateUserRequest(BaseModel):
    username: str
    password: str
    full_name: str
    role: str
    company_id: int
    is_admin: bool = False

@app.post("/api/admin/users")
async def admin_create_user(req: CreateUserRequest, db: AsyncSession = Depends(get_db), admin: m.UserAccount = Depends(require_admin)):
    u = m.UserAccount(username=req.username, password_hash=hash_password(req.password),
                      full_name=req.full_name, role=req.role, company_id=req.company_id, is_admin=req.is_admin)
    db.add(u)
    await db.commit()
    return {"id": u.id, "username": u.username}

# --- 流程管理 ---

def _diff_states_summary(old: list, new: list) -> str:
    """对比 states JSONB，输出简短描述"""
    old = old or []
    new = new or []
    old_map = {s.get("code"): s for s in old}
    new_map = {s.get("code"): s for s in new}
    added = sorted(set(new_map) - set(old_map))
    removed = sorted(set(old_map) - set(new_map))
    common = set(new_map) & set(old_map)
    modified = []
    for code in sorted(common):
        if old_map[code] != new_map[code]:
            changed_keys = []
            for k in set(old_map[code]) | set(new_map[code]):
                if old_map[code].get(k) != new_map[code].get(k):
                    changed_keys.append(k)
            modified.append((code, changed_keys))
    parts = []
    if added: parts.append(f"加节点 {added}")
    if removed: parts.append(f"删节点 {removed}")
    if modified:
        parts.append("改节点 " + "; ".join(f"{c}({','.join(ks)})" for c, ks in modified))
    return "; ".join(parts) or "无变化"


async def _audit(db, request: Request, admin: m.UserAccount, workflow_id: int,
                 change_type: str, summary: str = "",
                 before=None, after=None, danger: bool = False, comment: str = ""):
    """写一条审计日志"""
    log = m.WorkflowDefAuditLog(
        workflow_id=workflow_id,
        change_type=change_type,
        summary=summary,
        before_snapshot=before,
        after_snapshot=after,
        danger_mode=danger,
        changed_by_id=admin.id,
        ip_address=request.client.host if request.client else None,
        comment=comment,
    )
    db.add(log)


@app.get("/api/admin/workflows")
async def admin_workflows(db: AsyncSession = Depends(get_db), admin: m.UserAccount = Depends(require_admin)):
    result = await db.execute(select(m.WorkflowDefinition).order_by(m.WorkflowDefinition.group_name, m.WorkflowDefinition.doc_type))
    wfs = result.scalars().all()
    return [
        {
            "id": wf.id, "doc_type": wf.doc_type, "name": wf.name, "version": wf.version,
            "description": wf.description, "states": wf.states,
            "node_positions": wf.node_positions or {},
            "group_name": wf.group_name or "",
            "is_published": wf.is_published, "is_active": wf.is_active,
        }
        for wf in wfs
    ]


class UpdateStatesRequest(BaseModel):
    states: list[dict]
    force: bool = False  # 危险修改模式 — 已上线流程也允许改

@app.patch("/api/admin/workflows/{workflow_id}/states")
async def admin_update_workflow_states(workflow_id: int, req: UpdateStatesRequest, request: Request,
                                       db: AsyncSession = Depends(get_db), admin: m.UserAccount = Depends(require_admin)):
    result = await db.execute(select(m.WorkflowDefinition).where(m.WorkflowDefinition.id == workflow_id))
    wf = result.scalar_one_or_none()
    if not wf:
        return {"error": "流程不存在"}
    if wf.is_published and not req.force:
        return {"error": "流程已上线，内容不可改。请 Fork 一份新的去改，或开启「危险修改」模式。"}
    before = list(wf.states or [])
    wf.states = req.states
    summary = _diff_states_summary(before, req.states)
    await _audit(db, request, admin, workflow_id, "edit_states",
                 summary=summary, before=before, after=req.states,
                 danger=(wf.is_published and req.force))
    await db.commit()
    return {"ok": True, "id": wf.id, "state_count": len(req.states), "summary": summary}


# --- 流程生命周期 ---
class CreateWorkflowRequest(BaseModel):
    doc_type: str
    name: str
    description: str = ""
    group_name: str = ""

@app.post("/api/admin/workflows")
async def admin_create_workflow(req: CreateWorkflowRequest, request: Request, db: AsyncSession = Depends(get_db), admin: m.UserAccount = Depends(require_admin)):
    """新建空白草稿流程"""
    base = req.doc_type
    suffix = 1
    final_doc_type = base
    while True:
        r = await db.execute(select(m.WorkflowDefinition).where(m.WorkflowDefinition.doc_type == final_doc_type))
        if not r.scalar_one_or_none():
            break
        suffix += 1
        final_doc_type = f"{base}_{suffix}"
    wf = m.WorkflowDefinition(
        doc_type=final_doc_type, name=req.name, description=req.description,
        group_name=req.group_name, states=[], is_published=False, is_active=False,
        created_by_id=admin.id,
    )
    db.add(wf)
    await db.flush()
    await _audit(db, request, admin, wf.id, "create", summary=f"新建流程 {wf.name} ({wf.doc_type})")
    await db.commit()
    return {"id": wf.id, "doc_type": wf.doc_type, "name": wf.name}


@app.delete("/api/admin/workflows/{workflow_id}")
async def admin_delete_workflow(workflow_id: int, request: Request, db: AsyncSession = Depends(get_db), admin: m.UserAccount = Depends(require_admin)):
    """删除流程（仅未上线的草稿可删）"""
    result = await db.execute(select(m.WorkflowDefinition).where(m.WorkflowDefinition.id == workflow_id))
    wf = result.scalar_one_or_none()
    if not wf:
        return {"error": "流程不存在"}
    if wf.is_published:
        return {"error": "流程已上线，无法删除（可改为停用）"}
    snapshot = wf.states
    await _audit(db, request, admin, workflow_id, "delete", summary=f"删除流程 {wf.name}", before=snapshot)
    await db.delete(wf)
    await db.commit()
    return {"ok": True}


@app.post("/api/admin/workflows/{workflow_id}/fork")
async def admin_fork_workflow(workflow_id: int, request: Request, db: AsyncSession = Depends(get_db), admin: m.UserAccount = Depends(require_admin)):
    """Fork 一份新的"""
    result = await db.execute(select(m.WorkflowDefinition).where(m.WorkflowDefinition.id == workflow_id))
    src = result.scalar_one_or_none()
    if not src:
        return {"error": "流程不存在"}
    base = src.doc_type
    suffix = 2
    new_dt = f"{base}_{suffix}"
    while True:
        r = await db.execute(select(m.WorkflowDefinition).where(m.WorkflowDefinition.doc_type == new_dt))
        if not r.scalar_one_or_none():
            break
        suffix += 1
        new_dt = f"{base}_{suffix}"
    new_wf = m.WorkflowDefinition(
        doc_type=new_dt, name=f"{src.name} (Fork)", description=src.description,
        group_name=src.group_name, states=src.states,
        node_positions=src.node_positions or {},
        is_published=False, is_active=False,
        created_by_id=admin.id,
    )
    db.add(new_wf)
    await db.flush()
    await _audit(db, request, admin, new_wf.id, "fork",
                 summary=f"从 {src.name} (id={src.id}) Fork", after=src.states)
    await _audit(db, request, admin, src.id, "fork_source",
                 summary=f"被 Fork 为 {new_wf.name} (id={new_wf.id})")
    await db.commit()
    return {"id": new_wf.id, "doc_type": new_wf.doc_type, "name": new_wf.name}


@app.post("/api/admin/workflows/{workflow_id}/publish")
async def admin_publish_workflow(workflow_id: int, request: Request, db: AsyncSession = Depends(get_db), admin: m.UserAccount = Depends(require_admin)):
    """上线"""
    result = await db.execute(select(m.WorkflowDefinition).where(m.WorkflowDefinition.id == workflow_id))
    wf = result.scalar_one_or_none()
    if not wf:
        return {"error": "流程不存在"}
    if wf.is_published:
        return {"error": "已上线"}
    if not wf.states:
        return {"error": "流程没有任何节点，无法上线"}
    wf.is_published = True
    wf.is_active = True
    await _audit(db, request, admin, workflow_id, "publish", summary="流程上线")
    await db.commit()
    return {"ok": True, "id": wf.id}


async def _has_running_docs(db, doc_type: str, model) -> bool:
    """检查该 doc_type 是否有进行中的单据（status 不在终止节点）"""
    if not hasattr(model, "status"):
        return False
    r = await db.execute(select(model).where(model.status != ""))
    docs = r.scalars().all()
    return len(docs) > 0


@app.post("/api/admin/workflows/{workflow_id}/disable")
async def admin_disable_workflow(workflow_id: int, request: Request, db: AsyncSession = Depends(get_db), admin: m.UserAccount = Depends(require_admin)):
    """停用（仅当无在跑单据）"""
    result = await db.execute(select(m.WorkflowDefinition).where(m.WorkflowDefinition.id == workflow_id))
    wf = result.scalar_one_or_none()
    if not wf:
        return {"error": "流程不存在"}
    if not wf.is_active:
        return {"error": "已是停用状态"}
    model = workflow.DOC_MODEL_MAP.get(wf.doc_type)
    if model and hasattr(model, "status"):
        terminal_codes = [s["code"] for s in (wf.states or []) if s.get("is_terminal")]
        r = await db.execute(select(model).where(~model.status.in_(terminal_codes)) if terminal_codes else select(model))
        running = r.scalars().all()
        if running:
            return {"error": f"还有 {len(running)} 张单据在进行中，无法停用"}
    wf.is_active = False
    await _audit(db, request, admin, workflow_id, "disable", summary="流程停用")
    await db.commit()
    return {"ok": True, "id": wf.id}


@app.post("/api/admin/workflows/{workflow_id}/enable")
async def admin_enable_workflow(workflow_id: int, request: Request, db: AsyncSession = Depends(get_db), admin: m.UserAccount = Depends(require_admin)):
    """重新启用"""
    result = await db.execute(select(m.WorkflowDefinition).where(m.WorkflowDefinition.id == workflow_id))
    wf = result.scalar_one_or_none()
    if not wf:
        return {"error": "流程不存在"}
    wf.is_active = True
    await _audit(db, request, admin, workflow_id, "enable", summary="流程启用")
    await db.commit()
    return {"ok": True, "id": wf.id}


class UpdateGroupRequest(BaseModel):
    group_name: str

@app.patch("/api/admin/workflows/{workflow_id}/group")
async def admin_set_group(workflow_id: int, req: UpdateGroupRequest, request: Request, db: AsyncSession = Depends(get_db), admin: m.UserAccount = Depends(require_admin)):
    """改分组"""
    result = await db.execute(select(m.WorkflowDefinition).where(m.WorkflowDefinition.id == workflow_id))
    wf = result.scalar_one_or_none()
    if not wf:
        return {"error": "流程不存在"}
    old_group = wf.group_name
    wf.group_name = req.group_name
    await _audit(db, request, admin, workflow_id, "change_group",
                 summary=f"分组：{old_group or '无'} → {req.group_name}")
    await db.commit()
    return {"ok": True, "group_name": req.group_name}


# --- 审计日志查看 ---
@app.get("/api/admin/workflows/{workflow_id}/audit")
async def admin_workflow_audit(workflow_id: int, db: AsyncSession = Depends(get_db), admin: m.UserAccount = Depends(require_admin)):
    """查看流程的所有改动记录"""
    r = await db.execute(
        select(m.WorkflowDefAuditLog)
        .where(m.WorkflowDefAuditLog.workflow_id == workflow_id)
        .order_by(m.WorkflowDefAuditLog.timestamp.desc())
    )
    logs = r.scalars().all()
    # 加载用户名
    user_ids = list({l.changed_by_id for l in logs})
    users_r = await db.execute(select(m.UserAccount).where(m.UserAccount.id.in_(user_ids))) if user_ids else None
    users = {u.id: u.full_name for u in users_r.scalars().all()} if users_r else {}
    return [
        {
            "id": l.id,
            "change_type": l.change_type,
            "summary": l.summary,
            "danger_mode": l.danger_mode,
            "by": users.get(l.changed_by_id, f"#{l.changed_by_id}"),
            "timestamp": l.timestamp.isoformat() if l.timestamp else None,
            "ip": l.ip_address,
            "comment": l.comment,
            "before_snapshot": l.before_snapshot,
            "after_snapshot": l.after_snapshot,
        }
        for l in logs
    ]

# --- 知识库管理 ---
class KnowledgeRequest(BaseModel):
    entry_type: str  # SYSTEM_PROMPT / RULE / ALERT / GUIDE / FAQ
    title: str
    content: str
    applicable_doc_types: list[str] = []

@app.post("/api/admin/knowledge")
async def admin_create_knowledge(req: KnowledgeRequest, db: AsyncSession = Depends(get_db), admin: m.UserAccount = Depends(require_admin)):
    e = m.KnowledgeEntry(**req.model_dump())
    db.add(e)
    await db.commit()
    return {"id": e.id, "title": e.title}

@app.patch("/api/admin/knowledge/{entry_id}")
async def admin_update_knowledge(entry_id: int, req: KnowledgeRequest,
                                  db: AsyncSession = Depends(get_db), admin: m.UserAccount = Depends(require_admin)):
    result = await db.execute(select(m.KnowledgeEntry).where(m.KnowledgeEntry.id == entry_id))
    e = result.scalar_one_or_none()
    if not e:
        return {"error": "条目不存在"}
    for field, value in req.model_dump().items():
        setattr(e, field, value)
    await db.commit()
    return {"ok": True}
