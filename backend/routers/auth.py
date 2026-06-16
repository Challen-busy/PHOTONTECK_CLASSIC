"""认证路由：登录/登出/当前用户/公司切换"""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import models as m
from core.auth import authenticate, authorized_company_ids, get_current_user
from core.database import get_db
from services.tools import _user_allowed_tables

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


async def _user_payload(db: AsyncSession, user: m.UserAccount) -> dict:
    allowed = _user_allowed_tables(user)
    company_ids = getattr(user, "_authorized_company_ids", None)
    if company_ids is None:
        company_ids = await authorized_company_ids(db, user)
    active = getattr(user, "_active_company_id", None) or user.company_id
    # 拉已开通公司的简表（供前端切换器）
    rows = (
        await db.execute(
            select(m.Company.id, m.Company.code, m.Company.short_name, m.Company.name)
            .where(m.Company.id.in_(company_ids))
        )
    ).all()
    companies = [
        {"id": cid, "code": code, "short_name": short or name, "name": name}
        for cid, code, short, name in rows
    ]
    return {
        "id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "role": user.role,
        "company_id": user.company_id,
        "active_company_id": active,
        "authorized_company_ids": company_ids,
        "companies": companies,
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
    request.session["session_version"] = user.session_version
    # 默认 active 公司 = 主属公司（决策B）
    request.session["active_company_id"] = user.company_id
    user._active_company_id = user.company_id
    user._authorized_company_ids = await authorized_company_ids(db, user)
    return await _user_payload(db, user)


@router.post("/api/logout")
async def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@router.get("/api/me")
async def me(db: AsyncSession = Depends(get_db), user: m.UserAccount = Depends(get_current_user)):
    return await _user_payload(db, user)


class SwitchCompanyRequest(BaseModel):
    company_id: int


@router.post("/api/me/switch-company")
async def switch_company(
    req: SwitchCompanyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: m.UserAccount = Depends(get_current_user),
):
    """公司切换器（决策B，EXT-01-L）：仅可在已开通公司间切换，重写会话 active_company_id。

    无 DB 写（只改签名 Cookie），符合架构边界（写路径只在允许的层）。
    """
    allowed = getattr(user, "_authorized_company_ids", None) or await authorized_company_ids(db, user)
    if req.company_id not in allowed:
        raise HTTPException(status_code=403, detail="无权切换到该公司（未开通）")
    request.session["active_company_id"] = req.company_id
    user._active_company_id = req.company_id
    return await _user_payload(db, user)
