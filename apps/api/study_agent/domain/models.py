from dataclasses import dataclass, field
from datetime import datetime
from typing import BinaryIO
from uuid import UUID


@dataclass(slots=True)
class KnowledgeBase:
    id: UUID
    name: str
    description: str | None
    language: str
    status: str
    created_at: datetime
    updated_at: datetime
    material_count: int = 0
    question_count: int = 0


@dataclass(slots=True)
class Material:
    id: UUID
    knowledge_base_id: UUID
    title: str
    original_filename: str
    media_type: str
    storage_uri: str
    sha256: str
    size_bytes: int
    language: str
    parse_status: str
    parser_version: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class IngestionJob:
    id: UUID
    material_id: UUID
    status: str
    stage: str
    progress: int
    generation_config: dict[str, object] = field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime | None = None


@dataclass(slots=True)
class UploadPayload:
    stream: BinaryIO
    original_filename: str
    title: str
    media_type: str
    size_bytes: int
    sha256: str
    suffix: str


@dataclass(slots=True)
class StoredObject:
    uri: str
    object_name: str


@dataclass(slots=True)
class DocumentChunk:
    id: UUID
    material_id: UUID
    chunk_index: int
    content: str
    token_count: int
    page_start: int | None
    page_end: int | None
    heading_path: list[str]
    content_hash: str
    vector_id: str | None
    embedding_model: str | None
    created_at: datetime | None = None


@dataclass(slots=True)
class SearchHit:
    chunk_id: UUID
    material_id: UUID
    content: str
    score: float
    page_start: int | None
    page_end: int | None
    heading_path: list[str] = field(default_factory=list)


@dataclass(slots=True)
class QuestionGenerationJob:
    id: UUID
    material_id: UUID
    status: str
    stage: str
    progress: int
    target_question_count: int
    allowed_types: list[str]
    difficulty_min: int
    difficulty_max: int
    language: str
    generated_count: int = 0
    rejected_count: int = 0
    rejected_candidates: list[dict[str, object]] = field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime | None = None


@dataclass(slots=True)
class QuestionSource:
    chunk_id: UUID
    quote: str
    rank: int


@dataclass(slots=True)
class Question:
    id: UUID
    knowledge_base_id: UUID
    knowledge_point_id: UUID
    question_type: str
    stem: str
    options: list[dict[str, str]] | None
    correct_answer: object
    scoring_points: list[str]
    explanation: str
    difficulty: int
    max_score: float
    status: str
    content_hash: str
    vector_id: str | None
    sources: list[QuestionSource] = field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(slots=True)
class StudySession:
    id: UUID
    knowledge_base_id: UUID
    mode: str
    status: str
    planned_question_count: int
    answered_question_count: int
    correct_count: int
    incorrect_count: int
    total_score: float
    max_total_score: float
    question_types: list[str]
    difficulty_min: int
    difficulty_max: int
    started_at: datetime
    finished_at: datetime | None = None


@dataclass(slots=True)
class SessionQuestion:
    session_id: UUID
    question_id: UUID
    sequence: int
    selection_reason: dict[str, object] = field(default_factory=dict)
    priority_score: float = 0.0


@dataclass(slots=True)
class AnswerRecord:
    id: UUID
    submission_id: UUID
    session_id: UUID
    question_id: UUID
    knowledge_point_id: UUID
    answer: object
    score: float
    max_score: float
    verdict: str
    feedback: str
    elapsed_seconds: int
    answered_at: datetime
    explanation_data: dict[str, object] | None = None


@dataclass(slots=True)
class MasteryRecord:
    knowledge_point_id: UUID
    knowledge_base_id: UUID
    mastery_score: float
    answered_count: int
    correct_count: int
    recent_accuracy: float
    confidence: float
    updated_at: datetime


@dataclass(slots=True)
class ReviewTask:
    id: UUID
    knowledge_point_id: UUID
    knowledge_base_id: UUID
    due_at: datetime
    interval_days: int
    repetitions: int
    ease_factor: float
    last_quality: int
    status: str
    updated_at: datetime
