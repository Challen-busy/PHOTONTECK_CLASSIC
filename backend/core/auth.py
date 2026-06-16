"""认证：登录 + Session + 获取当前用户 + 多租户 active 公司解析"""

import hashlib
from datetime import date

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import models as m
from core.database import get_db


def hash_password(password: str) -> str:
    salt = "photonteck_salt"  # 生产环境换成随机盐（EXT-01-K，引擎自身欠账）
    return hashlib.sha256(f"{salt}{password}".encode()).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    return hash_password(password) == password_hash


async def authenticate(db: AsyncSession, username: str, password: str) -> m.UserAccount | None:
    stmt = select(m.UserAccount).where(
        m.UserAccount.username == username,
        m.UserAccount.is_active == True,
    )
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if user and verify_password(password, user.password_hash):
        return user
    return None


async def authorized_company_ids(db: AsyncSession, user: m.UserAccount) -> list[int]:
    """用户「已开通公司集」= UserCompanyAccess 行(未过期) ∪ 主属 company_id。

    临时代管(EXT-01-C)：valid_until 早于今天的授权行不计入。
    """
    today = date.today()
    rows = (
        await db.execute(
            select(m.UserCompanyAccess.company_id, m.UserCompanyAccess.valid_until)
            .where(m.UserCompanyAccess.user_id == user.id)
        )
    ).all()
    ids = {user.company_id}
    for company_id, valid_until in rows:
        if valid_until is not None and valid_until < today:
            continue
        ids.add(company_id)
    return sorted(ids)


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> m.UserAccount:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")
    stmt = select(m.UserAccount).where(m.UserAccount.id == user_id, m.UserAccount.is_active == True)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在或已禁用")

    # 服务端会话吊销（D-05f 升级）：会话里的 session_version 落后于账号当前值 → 强制下线
    session_ver = request.session.get("session_version", 0)
    if session_ver != user.session_version:
        request.session.clear()
        raise HTTPException(status_code=401, detail="会话已失效，请重新登录")

    # 多租户：解析「已开通公司集」与会话里的 active_company_id（决策B）
    allowed = await authorized_company_ids(db, user)
    active = request.session.get("active_company_id")
    if active not in allowed:
        active = user.company_id  # 越权/未设 → 回落主属公司
    # 把租户上下文挂到 user 对象上（请求级，不入库），供 _company_filter 读取
    user._authorized_company_ids = allowed
    user._active_company_id = active
    return user
