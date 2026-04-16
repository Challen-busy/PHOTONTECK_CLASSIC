"""第一层：数据库连接"""

import os

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://photonteck:photonteck@localhost:5432/photonteck",
)


class Base(DeclarativeBase):
    pass


def get_sync_engine():
    """同步引擎（Alembic用），延迟创建"""
    url = DATABASE_URL.replace("+asyncpg", "")
    return create_engine(url)


def get_async_engine():
    """异步引擎（应用运行时用），延迟创建"""
    return create_async_engine(
        DATABASE_URL,
        connect_args={"server_settings": {"timezone": "Asia/Shanghai"}},
    )


_async_session_factory = None


def get_session_factory():
    global _async_session_factory
    if _async_session_factory is None:
        _async_session_factory = sessionmaker(get_async_engine(), class_=AsyncSession, expire_on_commit=False)
    return _async_session_factory


async def get_db():
    factory = get_session_factory()
    async with factory() as session:
        yield session
