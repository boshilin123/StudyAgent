from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


# 用 PostgreSQL 事务锁串行处理同一资源，事务结束后自动释放。
async def transaction_lock(session: AsyncSession, key: UUID) -> None:
    lock_id = int.from_bytes(key.bytes[:8], "big", signed=True)
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_id})
