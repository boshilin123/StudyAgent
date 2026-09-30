import json
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError


class RedisStudyStateStore:
    def __init__(self, *, redis_url: str, ttl_seconds: int) -> None:
        self.redis = Redis.from_url(redis_url, decode_responses=True)
        self.ttl_seconds = ttl_seconds

    def _key(self, session_id: UUID) -> str:
        return f"study:session:{session_id}:state"

    async def get(self, session_id: UUID) -> dict[str, object] | None:
        try:
            raw = await self.redis.get(self._key(session_id))
        except RedisError:
            return None
        if not raw:
            return None
        try:
            value = json.loads(raw)
        except (ValueError, TypeError):
            return None
        return value if isinstance(value, dict) else None

    async def save(self, session_id: UUID, state: dict[str, object]) -> None:
        try:
            await self.redis.set(
                self._key(session_id),
                json.dumps(state, ensure_ascii=False),
                ex=self.ttl_seconds,
            )
        except RedisError:
            return

    async def delete(self, session_id: UUID) -> None:
        try:
            await self.redis.delete(self._key(session_id))
        except RedisError:
            return
