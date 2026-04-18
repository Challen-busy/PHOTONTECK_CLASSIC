"""认证路由：登录/登出/当前用户"""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

import models as m
from core.auth import authenticate, get_current_user
from core.database import get_db
from services.tools import _user_allowed_tables

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


def _user_payload(user: m.UserAccount) -> dict:
    allowed = _user_allowed_tables(user)
    return {
        "id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "role": user.role,
        "company_id": user.company_id,
        "is_admin": user.is_admin,
        # None = 全开(前端应视为"不过滤"), list = 受限表集合
        "allowed_tables": None if allowed is None else sorted(allowed),
    }


@router.post("/api/login")
async def login(req: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    user = await authenticate(db, req.username, req.password)
    if not user:
        return {"error": "用户名或密码错误"}
    request.session["user_id"] = user.id
    return _user_payload(user)


@router.post("/api/logout")
async def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@router.get("/api/me")
async def me(user: m.UserAccount = Depends(get_current_user)):
    return _user_payload(user)
