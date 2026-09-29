from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PageResponse(BaseModel):
    page: int
    page_size: int
    total: int


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    language: str = Field(default="zh-CN", min_length=2, max_length=20)


class KnowledgeBaseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    language: str | None = Field(default=None, min_length=2, max_length=20)
    status: Literal["active", "archived"] | None = None


class KnowledgeBaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    language: str
    status: str
    material_count: int = 0
    question_count: int = 0
    created_at: datetime
    updated_at: datetime


class KnowledgeBasePage(PageResponse):
    items: list[KnowledgeBaseResponse]


class MaterialResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    knowledge_base_id: UUID
    title: str
    original_filename: str
    media_type: str
    sha256: str
    size_bytes: int
    language: str
    parse_status: str
    parser_version: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class MaterialPage(PageResponse):
    items: list[MaterialResponse]


class IngestionJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    material_id: UUID
    status: str
    stage: str
    progress: int
    generation_config: dict[str, object]
    error_code: str | None
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime | None


class MaterialUploadResponse(BaseModel):
    material: MaterialResponse
    job: IngestionJobResponse


class DocumentChunkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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
    created_at: datetime | None


class SearchHitResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    chunk_id: UUID
    material_id: UUID
    content: str
    score: float
    page_start: int | None
    page_end: int | None
    heading_path: list[str]


class SearchResponse(BaseModel):
    query: str
    items: list[SearchHitResponse]


QuestionType = Literal["single_choice", "fill_blank", "true_false"]


def _default_question_types() -> list[QuestionType]:
    return ["single_choice", "fill_blank", "true_false"]


class QuestionGenerationCreate(BaseModel):
    target_question_count: int = Field(default=10, ge=1, le=100)
    allowed_types: list[QuestionType] = Field(
        default_factory=_default_question_types,
        min_length=1,
    )
    difficulty_min: int = Field(default=1, ge=1, le=5)
    difficulty_max: int = Field(default=3, ge=1, le=5)
    language: str = Field(default="zh-CN", min_length=2, max_length=20)


class QuestionGenerationJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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
    generated_count: int
    rejected_count: int
    error_code: str | None
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime | None


class QuestionSourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    chunk_id: UUID
    quote: str
    rank: int


class QuestionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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
    vector_id: str | None
    sources: list[QuestionSourceResponse]
    created_at: datetime | None
    updated_at: datetime | None


class QuestionPage(PageResponse):
    items: list[QuestionResponse]


class QuestionUpdate(BaseModel):
    stem: str | None = Field(default=None, min_length=5, max_length=1000)
    options: list[dict[str, str]] | None = None
    correct_answers: list[str] | None = Field(default=None, min_length=1, max_length=10)
    explanation: str | None = Field(default=None, min_length=5, max_length=3000)
    difficulty: int | None = Field(default=None, ge=1, le=5)


class StudySessionCreate(BaseModel):
    knowledge_base_id: UUID
    mode: Literal["diagnostic", "practice", "review", "mock_exam"] = "practice"
    question_count: int = Field(default=10, ge=1, le=100)
    question_types: list[QuestionType] = Field(
        default_factory=_default_question_types, min_length=1
    )
    difficulty_min: int = Field(default=1, ge=1, le=5)
    difficulty_max: int = Field(default=5, ge=1, le=5)


class PublicQuestionResponse(BaseModel):
    id: UUID
    sequence: int
    question_type: str
    stem: str
    options: list[dict[str, str]] | None
    difficulty: int
    max_score: float
    selection_reason: dict[str, object] | None = None


class StudySessionResponse(BaseModel):
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
    started_at: datetime
    finished_at: datetime | None
    current_question: PublicQuestionResponse | None


class AnswerSubmit(BaseModel):
    submission_id: UUID
    question_id: UUID
    answer: str | bool | int = Field(union_mode="left_to_right")
    elapsed_seconds: int = Field(default=0, ge=0, le=86400)


class MasteryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    knowledge_point_id: UUID
    knowledge_base_id: UUID
    mastery_score: float
    answered_count: int
    correct_count: int
    recent_accuracy: float
    confidence: float
    updated_at: datetime


class ReviewTaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    knowledge_point_id: UUID
    knowledge_base_id: UUID
    due_at: datetime
    interval_days: int
    repetitions: int
    ease_factor: float
    last_quality: int
    status: str


class AnswerResultResponse(BaseModel):
    submission_id: UUID
    question_id: UUID
    verdict: str
    score: float
    max_score: float
    feedback: str
    explanation: str
    rag_explanation: dict[str, object]
    idempotent_replay: bool
    mastery: MasteryResponse
    review_task: ReviewTaskResponse
    session: StudySessionResponse


class StudyHistoryPage(PageResponse):
    items: list[StudySessionResponse]
