from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from study_agent.infrastructure.database import Base


class TutorConversationModel(Base):
    __tablename__ = "tutor_conversations"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    scope_key: Mapped[str] = mapped_column(String(50), default="single-user")
    knowledge_base_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="RESTRICT")
    )
    study_session_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("study_sessions.id", ondelete="RESTRICT")
    )
    answered_question_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("questions.id", ondelete="RESTRICT")
    )
    graph_thread_id: Mapped[str] = mapped_column(String(80), unique=True)
    last_committed_checkpoint_id: Mapped[str | None] = mapped_column(String(100))
    graph_version: Mapped[str] = mapped_column(String(50), default="tutor-v1")
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TutorTurnModel(Base):
    __tablename__ = "tutor_turns"
    __table_args__ = (
        UniqueConstraint("conversation_id", "client_message_id", name="uq_tutor_client_message"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("tutor_conversations.id", ondelete="CASCADE"), index=True
    )
    client_message_id: Mapped[UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
    content: Mapped[str] = mapped_column(Text)
    intent: Mapped[str] = mapped_column(String(30), default="materials")
    status: Mapped[str] = mapped_column(String(20), default="running")
    response: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    usage: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    trace: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(50), default="tutor-v1")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TutorMessageModel(Base):
    __tablename__ = "tutor_messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "sequence", name="uq_tutor_message_sequence"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("tutor_conversations.id", ondelete="CASCADE"), index=True
    )
    turn_id: Mapped[UUID] = mapped_column(ForeignKey("tutor_turns.id", ondelete="CASCADE"))
    sequence: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
