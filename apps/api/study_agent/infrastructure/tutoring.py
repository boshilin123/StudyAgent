from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.exc import TimeoutError as PoolTimeout
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from study_agent.domain.errors import DomainError
from study_agent.infrastructure.tutoring_models import (
    TutorConversationModel,
    TutorMessageModel,
    TutorTurnModel,
)


class TutorRepository:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], engine: AsyncEngine
    ) -> None:
        self.sessions = session_factory
        self.engine = engine

    @asynccontextmanager
    async def execution_lock(self, conversation_id: UUID) -> AsyncIterator[bool]:
        key = int.from_bytes(conversation_id.bytes[:8], "big", signed=True)
        try:
            connection = await self.engine.connect()
        except PoolTimeout as exc:
            raise DomainError(
                "TUTOR_CONCURRENCY_LIMIT", "辅导并发达到上限，请稍后重试", status_code=503
            ) from exc
        try:
            connection = await connection.execution_options(isolation_level="AUTOCOMMIT")
            acquired = await connection.scalar(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": key}
            )
            try:
                yield bool(acquired)
            finally:
                if acquired:
                    await connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
        finally:
            await connection.close()

    async def conversation(self, conversation_id: UUID) -> TutorConversationModel:
        async with self.sessions() as session:
            item = await session.get(TutorConversationModel, conversation_id)
            if item is None or item.scope_key != "single-user":
                raise DomainError("TUTOR_CONVERSATION_NOT_FOUND", "辅导会话不存在", status_code=404)
            return item

    async def create(
        self,
        knowledge_base_id: UUID,
        study_session_id: UUID | None,
        answered_question_id: UUID | None,
        checkpoint_id: str,
        thread_id: str,
    ) -> TutorConversationModel:
        async with self.sessions() as session:
            item = TutorConversationModel(
                id=uuid4(),
                knowledge_base_id=knowledge_base_id,
                study_session_id=study_session_id,
                answered_question_id=answered_question_id,
                graph_thread_id=thread_id,
                last_committed_checkpoint_id=checkpoint_id,
                scope_key="single-user",
                status="active",
                graph_version="tutor-v1",
            )
            session.add(item)
            await session.commit()
            return item

    async def turn(
        self,
        conversation_id: UUID,
        client_message_id: UUID | None = None,
        turn_id: UUID | None = None,
    ) -> TutorTurnModel | None:
        async with self.sessions() as session:
            statement = select(TutorTurnModel).where(
                TutorTurnModel.conversation_id == conversation_id
            )
            statement = (
                statement.where(TutorTurnModel.id == turn_id)
                if turn_id
                else statement.where(TutorTurnModel.client_message_id == client_message_id)
            )
            return await session.scalar(statement)

    async def running_turn(self, conversation_id: UUID) -> TutorTurnModel | None:
        async with self.sessions() as session:
            return await session.scalar(
                select(TutorTurnModel)
                .where(
                    TutorTurnModel.conversation_id == conversation_id,
                    TutorTurnModel.status.in_(["pending", "running"]),
                )
                .order_by(TutorTurnModel.started_at)
                .limit(1)
            )

    async def _next_sequence(self, session: AsyncSession, conversation_id: UUID) -> int:
        maximum = await session.scalar(
            select(func.max(TutorMessageModel.sequence)).where(
                TutorMessageModel.conversation_id == conversation_id
            )
        )
        return 1 + (maximum or 0)

    async def reserve(
        self,
        conversation_id: UUID,
        client_message_id: UUID,
        content: str,
        intent: str,
        request_hash: str,
        timeout_seconds: int,
        model: str | None,
    ) -> TutorTurnModel:
        async with self.sessions() as session:
            turn = TutorTurnModel(
                id=uuid4(),
                conversation_id=conversation_id,
                client_message_id=client_message_id,
                content=content,
                intent=intent,
                request_hash=request_hash,
                status="running",
                model=model,
                deadline_at=datetime.now(UTC) + timedelta(seconds=timeout_seconds),
            )
            session.add(turn)
            await session.flush()
            session.add(
                TutorMessageModel(
                    id=uuid4(),
                    conversation_id=conversation_id,
                    turn_id=turn.id,
                    sequence=await self._next_sequence(session, conversation_id),
                    role="user",
                    content=content,
                    citations=[],
                )
            )
            await session.commit()
            return turn

    async def complete(
        self,
        conversation_id: UUID,
        turn_id: UUID,
        response: dict[str, Any],
        checkpoint_id: str,
        trace: list[dict[str, Any]],
    ) -> None:
        # The accepted graph pointer and final business response share one short transaction.
        async with self.sessions() as session:
            conversation = await session.get(TutorConversationModel, conversation_id)
            turn = await session.get(TutorTurnModel, turn_id)
            if conversation is None or turn is None:
                raise DomainError("TUTOR_TURN_NOT_FOUND", "辅导轮次不存在", status_code=404)
            if turn.status == "completed":
                return
            turn.status = "completed"
            turn.response = response
            turn.usage = response["usage"]
            turn.trace = trace
            turn.finished_at = datetime.now(UTC)
            conversation.last_committed_checkpoint_id = checkpoint_id
            session.add(
                TutorMessageModel(
                    id=uuid4(),
                    conversation_id=conversation_id,
                    turn_id=turn_id,
                    sequence=await self._next_sequence(session, conversation_id),
                    role="assistant",
                    content=response["message"],
                    citations=response["citations"],
                )
            )
            await session.commit()

    async def fail(
        self,
        turn_id: UUID,
        code: str,
        message: str,
        usage: dict[str, Any],
        trace: list[dict[str, Any]],
        status: str = "failed",
    ) -> None:
        async with self.sessions() as session:
            turn = await session.get(TutorTurnModel, turn_id)
            if turn is None:
                raise DomainError("TUTOR_TURN_NOT_FOUND", "辅导轮次不存在", status_code=404)
            if turn.status == "completed":
                return
            turn.status, turn.error_code, turn.error_message = status, code, message
            turn.usage, turn.trace = usage, trace
            turn.finished_at = datetime.now(UTC)
            await session.commit()

    async def committed_history(self, conversation_id: UUID, limit: int) -> list[TutorMessageModel]:
        async with self.sessions() as session:
            items = (
                await session.scalars(
                    select(TutorMessageModel)
                    .join(TutorTurnModel, TutorMessageModel.turn_id == TutorTurnModel.id)
                    .where(
                        TutorMessageModel.conversation_id == conversation_id,
                        TutorTurnModel.status == "completed",
                    )
                    .order_by(TutorMessageModel.sequence.desc())
                    .limit(limit)
                )
            ).all()
            return list(reversed(items))

    async def list_conversations(
        self, knowledge_base_id: UUID | None, page: int, page_size: int
    ) -> tuple[Sequence[TutorConversationModel], int]:
        async with self.sessions() as session:
            criteria = [TutorConversationModel.scope_key == "single-user"]
            if knowledge_base_id:
                criteria.append(TutorConversationModel.knowledge_base_id == knowledge_base_id)
            total = await session.scalar(
                select(func.count()).select_from(TutorConversationModel).where(*criteria)
            )
            items = (
                await session.scalars(
                    select(TutorConversationModel)
                    .where(*criteria)
                    .order_by(
                        TutorConversationModel.created_at.desc(), TutorConversationModel.id.desc()
                    )
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
            return items, total or 0

    async def messages(
        self, conversation_id: UUID, page: int, page_size: int
    ) -> tuple[Sequence[TutorMessageModel], int]:
        async with self.sessions() as session:
            total = await session.scalar(
                select(func.count())
                .select_from(TutorMessageModel)
                .where(TutorMessageModel.conversation_id == conversation_id)
            )
            items = (
                await session.scalars(
                    select(TutorMessageModel)
                    .where(TutorMessageModel.conversation_id == conversation_id)
                    .order_by(TutorMessageModel.sequence)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
            return items, total or 0

    async def archive(self, conversation_id: UUID) -> TutorConversationModel:
        async with self.sessions() as session:
            item = await session.get(TutorConversationModel, conversation_id)
            if item is None:
                raise DomainError("TUTOR_CONVERSATION_NOT_FOUND", "辅导会话不存在", status_code=404)
            item.status = "archived"
            await session.commit()
            return item
