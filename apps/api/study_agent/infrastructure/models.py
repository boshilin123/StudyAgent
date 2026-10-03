from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from study_agent.infrastructure.database import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class KnowledgeBaseModel(TimestampMixin, Base):
    __tablename__ = "knowledge_bases"
    __table_args__ = (
        CheckConstraint("status in ('active', 'archived', 'deleted')", name="ck_kb_status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(20), default="zh-CN", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)


class MaterialModel(TimestampMixin, Base):
    __tablename__ = "materials"
    __table_args__ = (
        UniqueConstraint("knowledge_base_id", "sha256", name="uq_material_kb_sha256"),
        CheckConstraint("size_bytes > 0", name="ck_material_size_positive"),
        CheckConstraint(
            "parse_status in ('pending', 'parsing', 'ready', 'partial', 'failed')",
            name="ck_material_parse_status",
        ),
        Index("ix_materials_knowledge_base_created", "knowledge_base_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    knowledge_base_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    media_type: Mapped[str] = mapped_column(String(100), nullable=False)
    storage_uri: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    language: Mapped[str] = mapped_column(String(20), nullable=False)
    parse_status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    parser_version: Mapped[str | None] = mapped_column(String(50))
    error_message: Mapped[str | None] = mapped_column(Text)


class WorkflowRunModel(Base):
    """Workflow trace mapped to the historical agent_runs physical table."""

    __tablename__ = "agent_runs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    agent_type: Mapped[str] = mapped_column(String(30), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(30), nullable=False)
    subject_id: Mapped[UUID] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    model: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(50))
    input_summary: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    output_summary: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentChunkModel(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("material_id", "chunk_index", name="uq_chunk_material_index"),
        Index("ix_chunks_content_hash", "content_hash"),
        Index("ix_chunks_vector_id", "vector_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    material_id: Mapped[UUID] = mapped_column(
        ForeignKey("materials.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    heading_path: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    parent_chunk_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="SET NULL")
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    vector_id: Mapped[str | None] = mapped_column(String(100))
    embedding_model: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class KnowledgePointModel(TimestampMixin, Base):
    __tablename__ = "knowledge_points"
    __table_args__ = (
        UniqueConstraint("knowledge_base_id", "canonical_key", name="uq_kp_kb_canonical"),
        CheckConstraint("importance >= 0 and importance <= 1", name="ck_kp_importance"),
        CheckConstraint("difficulty >= 1 and difficulty <= 5", name="ck_kp_difficulty"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    knowledge_base_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    canonical_key: Mapped[str] = mapped_column(String(300), nullable=False)
    importance: Mapped[Decimal] = mapped_column(Numeric(4, 3), default=Decimal("0.5"))
    difficulty: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    source: Mapped[str] = mapped_column(String(20), default="agent", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)


class KnowledgePointSourceModel(Base):
    __tablename__ = "knowledge_point_sources"

    knowledge_point_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="CASCADE"), primary_key=True
    )
    chunk_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="CASCADE"), primary_key=True
    )
    relevance: Mapped[Decimal] = mapped_column(Numeric(4, 3), default=Decimal("1"))


class QuestionModel(TimestampMixin, Base):
    __tablename__ = "questions"
    __table_args__ = (
        UniqueConstraint("knowledge_base_id", "content_hash", name="uq_question_kb_hash"),
        CheckConstraint(
            "question_type in ('single_choice', 'fill_blank', 'true_false', 'short_answer')",
            name="ck_question_type",
        ),
        CheckConstraint("difficulty >= 1 and difficulty <= 5", name="ck_question_difficulty"),
        CheckConstraint("max_score > 0", name="ck_question_max_score"),
        CheckConstraint(
            "status in ('draft', 'active', 'disabled', 'rejected', 'deleted')",
            name="ck_question_status",
        ),
        Index(
            "ix_questions_kb_kp_status_difficulty",
            "knowledge_base_id",
            "knowledge_point_id",
            "status",
            "difficulty",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    knowledge_base_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False
    )
    knowledge_point_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="CASCADE"), nullable=False
    )
    question_type: Mapped[str] = mapped_column(String(30), nullable=False)
    stem: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list[dict[str, str]] | None] = mapped_column(JSON)
    correct_answer: Mapped[object] = mapped_column(JSON, nullable=False)
    scoring_points: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    difficulty: Mapped[int] = mapped_column(Integer, nullable=False)
    max_score: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=Decimal("10"))
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    generation_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL")
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    vector_id: Mapped[str | None] = mapped_column(String(100))


class QuestionSourceModel(Base):
    __tablename__ = "question_sources"

    question_id: Mapped[UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), primary_key=True
    )
    chunk_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="CASCADE"), primary_key=True
    )
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class QuestionGenerationJobModel(Base):
    __tablename__ = "question_generation_jobs"
    __table_args__ = (
        CheckConstraint("progress >= 0 and progress <= 100", name="ck_question_job_progress"),
        CheckConstraint("target_question_count > 0", name="ck_question_job_target_positive"),
        Index("ix_question_jobs_material_created", "material_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    material_id: Mapped[UUID] = mapped_column(
        ForeignKey("materials.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    stage: Mapped[str] = mapped_column(String(40), nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    target_question_count: Mapped[int] = mapped_column(Integer, nullable=False)
    allowed_types: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    difficulty_min: Mapped[int] = mapped_column(Integer, nullable=False)
    difficulty_max: Mapped[int] = mapped_column(Integer, nullable=False)
    language: Mapped[str] = mapped_column(String(20), nullable=False)
    generated_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rejected_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rejected_candidates: Mapped[list[dict[str, object]]] = mapped_column(
        JSON, default=list, server_default="[]", nullable=False
    )
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class IngestionJobModel(Base):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        CheckConstraint("progress >= 0 and progress <= 100", name="ck_job_progress"),
        Index("ix_jobs_material_created", "material_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    material_id: Mapped[UUID] = mapped_column(
        ForeignKey("materials.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    stage: Mapped[str] = mapped_column(String(30), nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    generation_config: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class WorkflowStepModel(Base):
    """Workflow step trace; a row alone does not imply Agent Tool Calling."""
    __tablename__ = "agent_steps"
    __table_args__ = (UniqueConstraint("run_id", "sequence", name="uq_agent_step_sequence"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    node_name: Mapped[str] = mapped_column(String(100), nullable=False)
    tool_name: Mapped[str | None] = mapped_column(String(100))
    input_summary: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    output_summary: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class StudySessionModel(Base):
    __tablename__ = "study_sessions"
    __table_args__ = (
        CheckConstraint(
            "mode in ('diagnostic', 'practice', 'review', 'mock_exam')",
            name="ck_study_mode",
        ),
        CheckConstraint("status in ('active', 'completed', 'abandoned')", name="ck_study_status"),
        Index("ix_study_sessions_kb_started", "knowledge_base_id", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    knowledge_base_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="RESTRICT"), nullable=False
    )
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    planned_question_count: Mapped[int] = mapped_column(Integer, nullable=False)
    answered_question_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    correct_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    incorrect_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_score: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0"))
    max_total_score: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0"))
    question_types: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    difficulty_min: Mapped[int] = mapped_column(Integer, nullable=False)
    difficulty_max: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SessionQuestionModel(Base):
    __tablename__ = "session_questions"
    __table_args__ = (UniqueConstraint("session_id", "question_id", name="uq_session_question"),)

    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("study_sessions.id", ondelete="CASCADE"), primary_key=True
    )
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True)
    question_id: Mapped[UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="RESTRICT"), nullable=False
    )
    selection_reason: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    priority_score: Mapped[Decimal] = mapped_column(
        Numeric(7, 6), default=Decimal("0"), nullable=False
    )


class AnswerRecordModel(Base):
    __tablename__ = "answer_records"
    __table_args__ = (
        UniqueConstraint("submission_id", name="uq_answer_submission"),
        UniqueConstraint("session_id", "question_id", name="uq_answer_session_question"),
        CheckConstraint("verdict in ('correct', 'incorrect')", name="ck_answer_verdict"),
        Index("ix_answer_records_session_answered", "session_id", "answered_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    submission_id: Mapped[UUID] = mapped_column(nullable=False)
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("study_sessions.id", ondelete="CASCADE"), nullable=False
    )
    question_id: Mapped[UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="RESTRICT"), nullable=False
    )
    knowledge_point_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="RESTRICT"), nullable=False
    )
    answer: Mapped[object] = mapped_column(JSON, nullable=False)
    score: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    max_score: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    verdict: Mapped[str] = mapped_column(String(20), nullable=False)
    feedback: Mapped[str] = mapped_column(Text, nullable=False)
    elapsed_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    answered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    explanation_data: Mapped[dict[str, object] | None] = mapped_column(JSON)


class MasteryRecordModel(Base):
    __tablename__ = "mastery_records"
    __table_args__ = (
        CheckConstraint("mastery_score >= 0 and mastery_score <= 1", name="ck_mastery_score"),
        CheckConstraint(
            "recent_accuracy >= 0 and recent_accuracy <= 1", name="ck_mastery_accuracy"
        ),
        CheckConstraint("confidence >= 0 and confidence <= 1", name="ck_mastery_confidence"),
        Index("ix_mastery_records_kb", "knowledge_base_id"),
    )

    knowledge_point_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="CASCADE"), primary_key=True
    )
    knowledge_base_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False
    )
    mastery_score: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    answered_count: Mapped[int] = mapped_column(Integer, nullable=False)
    correct_count: Mapped[int] = mapped_column(Integer, nullable=False)
    recent_accuracy: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReviewTaskModel(Base):
    __tablename__ = "review_tasks"
    __table_args__ = (
        UniqueConstraint("knowledge_point_id", name="uq_review_knowledge_point"),
        CheckConstraint("status in ('pending', 'completed')", name="ck_review_status"),
        Index("ix_review_tasks_due", "status", "due_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    knowledge_point_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="CASCADE"), nullable=False
    )
    knowledge_base_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False
    )
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    interval_days: Mapped[int] = mapped_column(Integer, nullable=False)
    repetitions: Mapped[int] = mapped_column(Integer, nullable=False)
    ease_factor: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False)
    last_quality: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# Compatibility aliases; remove with the next internal interface cleanup.
AgentRunModel = WorkflowRunModel
AgentStepModel = WorkflowStepModel
