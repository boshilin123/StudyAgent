from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from study_agent.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
engine = create_async_engine(settings.database_url, pool_pre_ping=True)
session_factory = async_sessionmaker(engine, expire_on_commit=False)


# 为一次请求提供数据库会话，用完后自动关闭连接。
async def get_session() -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session
