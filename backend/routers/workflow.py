"""流程路由：流转/预览/提交/转换列表/历史/流程列表/节点详情"""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import models as m
from core.auth import get_current_user
from core.database import get_db
from services.commands import execute_command
from services import workflow

router = APIRouter()


class TransitionRequest(BaseModel):
    doc_type: str
    doc_id: int | None = None
    to_state: str | None = None
    action_label: str = ""
    field_updates: dict = {}
    sub_updates: list = []
    comment: str = ""


class TransitionPreviewRequest(BaseModel):
    doc_type: str
    doc_id: int | None = None
    to_state: str = ""
    action_label: str = ""
    field_updates: dict = {}


class TransitionCommitRequest(BaseModel):
    card: dict
    comment: str = ""


def _workflow_command_response(result: dict) -> dict:
    if result.get("success"):
        return result
    details = result.get("details")
    if isinstance(details, dict) and details.get("success") is False:
        return details
    return result


@router.post("/api/transition")
async def transition(req: TransitionRequest, request: Request, db: AsyncSession = Depends(get_db), user: m.UserAccount = Depends(get_current_user)):
    result = await execute_command(
        db,
        user,
        "workflow_transition",
        {
            "doc_type": req.doc_type,
            "doc_id": req.doc_id,
            "to_state": req.to_state,
            "action_label": req.action_label,
            "field_updates": req.field_updates,
            "sub_updates": req.sub_updates,
            "comment": req.comment,
            "ip_address": request.client.host if request.client else None,
        },
        log_payload={
            "doc_type": req.doc_type,
            "doc_id": req.doc_id,
            "to_state": req.to_state,
            "action_label": req.action_label,
            "field_update_fields": sorted((req.field_updates or {}).keys()),
            "sub_update_count": len(req.sub_updates or []),
            "comment": req.comment,
        },
    )
    return _workflow_command_response(result)


@router.post("/api/transition/preview")
async def transition_preview(req: TransitionPreviewRequest, db: AsyncSession = Depends(get_db), user: m.UserAccount = Depends(get_current_user)):
    return await workflow.preview_transition(
        db=db, doc_type=req.doc_type, doc_id=req.doc_id,
        to_state=req.to_state, action_label=req.action_label,
        user=user, field_updates=req.field_updates,
    )


@router.post("/api/transition/commit")
async def transition_commit(req: TransitionCommitRequest, request: Request, db: AsyncSession = Depends(get_db), user: m.UserAccount = Depends(get_current_user)):
    result = await execute_command(
        db,
        user,
        "workflow_commit_card",
        {
            "card": req.card,
            "comment": req.comment,
            "ip_address": request.client.host if request.client else None,
        },
        log_payload={
            "doc_type": (req.card or {}).get("doc_type"),
            "doc_id": (req.card or {}).get("doc_id"),
            "from_state": (req.card or {}).get("from_state"),
            "to_state": (req.card or {}).get("to_state"),
            "action_label": (req.card or {}).get("action_label"),
            "change_count": len((req.card or {}).get("changes") or []),
            "comment": req.comment,
        },
    )
    return _workflow_command_response(result)


@router.get("/api/transitions")
async def transitions(db: AsyncSession = Depends(get_db), user: m.UserAccount = Depends(get_current_user)):
    return await workflow.list_user_actions(db, user)


@router.get("/api/my-todos")
async def my_todos(db: AsyncSession = Depends(get_db), user: m.UserAccount = Depends(get_current_user)):
    return await workflow.list_user_todos(db, user)


@router.get("/api/history/{doc_type}/{doc_id}")
async def history(doc_type: str, doc_id: int, db: AsyncSession = Depends(get_db), user: m.UserAccount = Depends(get_current_user)):
    stmt = select(m.WorkflowLog).where(
        m.WorkflowLog.doc_type == doc_type,
        m.WorkflowLog.doc_id == doc_id,
    ).order_by(m.WorkflowLog.timestamp)
    result = await db.execute(stmt)
    logs = result.scalars().all()
    user_ids = {l.triggered_by_id for l in logs if l.triggered_by_id}
    operators = {}
    if user_ids:
        user_result = await db.execute(select(m.UserAccount).where(m.UserAccount.id.in_(user_ids)))
        operators = {u.id: u for u in user_result.scalars().all()}

    return [
        {
            "id": l.id, "transition": l.transition_name,
            "from_state": l.from_state, "to_state": l.to_state,
            "triggered_by_id": l.triggered_by_id,
            "triggered_by": {
                "id": operators[l.triggered_by_id].id,
                "username": operators[l.triggered_by_id].username,
                "full_name": operators[l.triggered_by_id].full_name,
                "role": operators[l.triggered_by_id].role,
            } if l.triggered_by_id in operators else None,
            "timestamp": l.timestamp.isoformat() if l.timestamp else None,
            "changed_fields": l.changed_fields,
            "comment": l.comment,
        }
        for l in logs
    ]


@router.get("/api/workflows")
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


@router.get("/api/state-detail/{doc_type}/{state_code}")
async def state_detail(doc_type: str, state_code: str, db: AsyncSession = Depends(get_db), user: m.UserAccount = Depends(get_current_user)):
    wf = await workflow.get_active_workflow(db, doc_type)
    if not wf:
        return {"error": "流程不存在"}
    state = next((s for s in (wf.states or []) if s.get("code") == state_code), None)
    if not state:
        return {"error": "节点不存在"}
    return state
