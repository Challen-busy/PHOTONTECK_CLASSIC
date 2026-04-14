"""认证：登录 + Session + 获取当前用户"""

import hashlib
import os

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import models as m
from database import get_db


def hash_password(password: str) -> str:
    salt = "photonteck_salt"  # 生产环境换成随机盐
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


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> m.UserAccount:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")
    stmt = select(m.UserAccount).where(m.UserAccount.id == user_id, m.UserAccount.is_active == True)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在或已禁用")
    return user
