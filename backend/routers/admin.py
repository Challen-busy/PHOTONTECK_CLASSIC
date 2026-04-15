"""管理员路由：流程管理/用户管理/知识库管理/审计"""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

import models as m
from agents.admin_agent import admin_chat
from core.auth import get_current_user, hash_password
from core.database import get_db
from services import workflow

router = APIRouter()


def require_admin(user: m.UserAccount = Depends(get_current_user)):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


# ============================================================
# 管理员 Agent
# ============================================================

class AdminChatRequest(BaseModel):
    query: str


@router.post("/api/admin/agent/chat")
async def admin_agent_chat(req: AdminChatRequest, db: AsyncSession = Depends(get_db), user: m.UserAccount = Depends(get_current_user)):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return await admin_chat(db, req.query, user)


# ============================================================
# 流程图坐标
# ============================================================

class SavePositionsRequest(BaseModel):
    workflow_id: int
    positions: dict


@router.post("/api/admin/save-positions")
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


# ============================================================
# 用户管理
# ============================================================

@router.get("/api/admin/users")
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


@router.post("/api/admin/users")
async def admin_create_user(req: CreateUserRequest, db: AsyncSession = Depends(get_db), admin: m.UserAccount = Depends(require_admin)):
    u = m.UserAccount(username=req.username, password_hash=hash_password(req.password),
                      full_name=req.full_name, role=req.role, company_id=req.company_id, is_admin=req.is_admin)
    db.add(u)
    await db.commit()
    return {"id": u.id, "username": u.username}


# ============================================================
# 流程管理
# ============================================================

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


@router.get("/api/admin/workflows")
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
    force: bool = False


@router.patch("/api/admin/workflows/{workflow_id}/states")
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


class CreateWorkflowRequest(BaseModel):
    doc_type: str
    name: str
    description: str = ""
    group_name: str = ""


@router.post("/api/admin/workflows")
async def admin_create_workflow(req: CreateWorkflowRequest, request: Request, db: AsyncSession = Depends(get_db), admin: m.UserAccount = Depends(require_admin)):
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


@router.delete("/api/admin/workflows/{workflow_id}")
async def admin_delete_workflow(workflow_id: int, request: Request, db: AsyncSession = Depends(get_db), admin: m.UserAccount = Depends(require_admin)):
    result = await db.execute(select(m.WorkflowDefinition).where(m.WorkflowDefinition.id == workflow_id))
    wf = result.scalar_one_or_none()
    if not wf:
        return {"error": "流程不存在"}
    if wf.is_published:
        return {"error": "流程已上线，无法删除（可改为停用）"}
    # 清掉该流程的审计历史再删主表（WorkflowDefAuditLog 对父表是 FK，级联在代码层）
    await db.execute(delete(m.WorkflowDefAuditLog).where(m.WorkflowDefAuditLog.workflow_id == workflow_id))
    await db.delete(wf)
    await db.commit()
    return {"ok": True}


@router.post("/api/admin/workflows/{workflow_id}/fork")
async def admin_fork_workflow(workflow_id: int, request: Request, db: AsyncSession = Depends(get_db), admin: m.UserAccount = Depends(require_admin)):
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


@router.post("/api/admin/workflows/{workflow_id}/publish")
async def admin_publish_workflow(workflow_id: int, request: Request, db: AsyncSession = Depends(get_db), admin: m.UserAccount = Depends(require_admin)):
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


@router.post("/api/admin/workflows/{workflow_id}/disable")
async def admin_disable_workflow(workflow_id: int, request: Request, db: AsyncSession = Depends(get_db), admin: m.UserAccount = Depends(require_admin)):
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


@router.post("/api/admin/workflows/{workflow_id}/enable")
async def admin_enable_workflow(workflow_id: int, request: Request, db: AsyncSession = Depends(get_db), admin: m.UserAccount = Depends(require_admin)):
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


@router.patch("/api/admin/workflows/{workflow_id}/group")
async def admin_set_group(workflow_id: int, req: UpdateGroupRequest, request: Request, db: AsyncSession = Depends(get_db), admin: m.UserAccount = Depends(require_admin)):
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


@router.get("/api/admin/workflows/{workflow_id}/audit")
async def admin_workflow_audit(workflow_id: int, db: AsyncSession = Depends(get_db), admin: m.UserAccount = Depends(require_admin)):
    r = await db.execute(
        select(m.WorkflowDefAuditLog)
        .where(m.WorkflowDefAuditLog.workflow_id == workflow_id)
        .order_by(m.WorkflowDefAuditLog.timestamp.desc())
    )
    logs = r.scalars().all()
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


# ============================================================
# 知识库管理
# ============================================================

class KnowledgeRequest(BaseModel):
    entry_type: str
    title: str
    content: str
    applicable_doc_types: list[str] = []


@router.post("/api/admin/knowledge")
async def admin_create_knowledge(req: KnowledgeRequest, db: AsyncSession = Depends(get_db), admin: m.UserAccount = Depends(require_admin)):
    e = m.KnowledgeEntry(**req.model_dump())
    db.add(e)
    await db.commit()
    return {"id": e.id, "title": e.title}


@router.patch("/api/admin/knowledge/{entry_id}")
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
