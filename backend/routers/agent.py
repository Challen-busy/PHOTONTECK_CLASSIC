"""Agent 路由：LLM 对话 + 知识库（preview / commit 已移至 routers/workflow.py）"""

import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

import models as m
from agents import agent
from core.auth import get_current_user
from core.database import get_db

router = APIRouter()


class ChatRequest(BaseModel):
    query: str


@router.post("/api/agent/chat")
async def agent_chat(req: ChatRequest, db: AsyncSession = Depends(get_db), user: m.UserAccount = Depends(get_current_user)):
    return await agent.chat(db, req.query, user)


@router.post("/api/agent/chat/stream")
async def agent_chat_stream(req: ChatRequest, db: AsyncSession = Depends(get_db), user: m.UserAccount = Depends(get_current_user)):
    async def event_generator():
        async for event in agent.chat_stream(db, req.query, user):
            yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/api/knowledge")
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
