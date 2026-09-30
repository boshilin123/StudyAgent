from collections.abc import Sequence
from datetime import datetime
from typing import BinaryIO, Protocol
from uuid import UUID

from study_agent.domain.models import (
    AnswerRecord,
    DocumentChunk,
    IngestionJob,
    KnowledgeBase,
    MasteryRecord,
    Material,
    Question,
    QuestionGenerationJob,
    ReviewTask,
    SearchHit,
    SessionQuestion,
    StoredObject,
    StudySession,
)


class KnowledgeBaseRepository(Protocol):
    async def add(self, knowledge_base: KnowledgeBase) -> KnowledgeBase: ...

    async def get(self, knowledge_base_id: UUID) -> KnowledgeBase | None: ...

    async def list(
        self, *, page: int, page_size: int, status: str | None, keyword: str | None
    ) -> tuple[Sequence[KnowledgeBase], int]: ...

    async def update(self, knowledge_base: KnowledgeBase) -> KnowledgeBase: ...


class MaterialRepository(Protocol):
    async def add(self, material: Material) -> Material: ...

    async def get(self, material_id: UUID) -> Material | None: ...

    async def get_by_hash(self, knowledge_base_id: UUID, sha256: str) -> Material | None: ...

    async def list(
        self, *, knowledge_base_id: UUID, page: int, page_size: int, status: str | None
    ) -> tuple[Sequence[Material], int]: ...

    async def delete(self, material_id: UUID) -> None: ...


class IngestionJobRepository(Protocol):
    async def add(self, job: IngestionJob) -> IngestionJob: ...

    async def get(self, job_id: UUID) -> IngestionJob | None: ...

    async def has_running_for_material(self, material_id: UUID) -> bool: ...

    async def fail_dispatch(self, job_id: UUID) -> None: ...


class DocumentChunkRepository(Protocol):
    async def list_for_material(self, material_id: UUID) -> Sequence[DocumentChunk]: ...


class QuestionGenerationJobRepository(Protocol):
    async def add(self, job: QuestionGenerationJob) -> QuestionGenerationJob: ...

    async def get(self, job_id: UUID) -> QuestionGenerationJob | None: ...

    async def has_running_for_material(self, material_id: UUID) -> bool: ...

    async def fail_dispatch(self, job_id: UUID) -> None: ...


class QuestionRepository(Protocol):
    async def invalidate_sources(self, chunk_ids: Sequence[UUID]) -> Sequence[Question]: ...

    async def get(self, question_id: UUID) -> Question | None: ...

    async def list(
        self,
        *,
        knowledge_base_id: UUID | None,
        material_id: UUID | None,
        question_type: str | None,
        status: str | None,
        page: int,
        page_size: int,
    ) -> tuple[Sequence[Question], int]: ...

    async def update(self, question: Question) -> Question: ...

    async def list_active_candidates(
        self,
        *,
        knowledge_base_id: UUID,
        question_types: Sequence[str],
        difficulty_min: int,
        difficulty_max: int,
        limit: int | None,
    ) -> Sequence[Question]: ...


class StudySessionRepository(Protocol):
    async def add(self, session: StudySession) -> StudySession: ...
    async def get(self, session_id: UUID) -> StudySession | None: ...
    async def get_for_update(self, session_id: UUID) -> StudySession | None: ...
    async def update(self, session: StudySession) -> StudySession: ...
    async def add_questions(self, questions: Sequence[SessionQuestion]) -> None: ...
    async def list_questions(self, session_id: UUID) -> Sequence[SessionQuestion]: ...
    async def list(
        self, *, knowledge_base_id: UUID | None, page: int, page_size: int
    ) -> tuple[Sequence[StudySession], int]: ...


class AnswerRecordRepository(Protocol):
    async def add(self, answer: AnswerRecord) -> AnswerRecord: ...
    async def get_by_submission(self, submission_id: UUID) -> AnswerRecord | None: ...
    async def update_explanation(
        self, answer_id: UUID, explanation_data: dict[str, object]
    ) -> AnswerRecord: ...
    async def list_answered_question_ids(self, knowledge_base_id: UUID) -> set[UUID]: ...
    async def list_for_session(self, session_id: UUID) -> Sequence[AnswerRecord]: ...


class StudyStateStore(Protocol):
    async def get(self, session_id: UUID) -> dict[str, object] | None: ...
    async def save(self, session_id: UUID, state: dict[str, object]) -> None: ...
    async def delete(self, session_id: UUID) -> None: ...


class MasteryRepository(Protocol):
    async def get(self, knowledge_point_id: UUID) -> MasteryRecord | None: ...
    async def upsert(self, record: MasteryRecord) -> MasteryRecord: ...
    async def list(self, knowledge_base_id: UUID | None) -> Sequence[MasteryRecord]: ...


class ReviewTaskRepository(Protocol):
    async def get_by_knowledge_point(self, knowledge_point_id: UUID) -> ReviewTask | None: ...
    async def upsert(self, task: ReviewTask) -> ReviewTask: ...
    async def list_due(
        self, *, knowledge_base_id: UUID | None, due_before: datetime
    ) -> Sequence[ReviewTask]: ...


class UnitOfWork(Protocol):
    knowledge_bases: KnowledgeBaseRepository
    materials: MaterialRepository
    ingestion_jobs: IngestionJobRepository
    document_chunks: DocumentChunkRepository
    question_generation_jobs: QuestionGenerationJobRepository
    questions: QuestionRepository
    study_sessions: StudySessionRepository
    answer_records: AnswerRecordRepository
    mastery: MasteryRepository
    review_tasks: ReviewTaskRepository

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...

    async def lock(self, key: UUID) -> None: ...


class ObjectStorage(Protocol):
    async def put(
        self,
        *,
        object_name: str,
        stream: BinaryIO,
        size: int,
        content_type: str,
    ) -> StoredObject: ...

    async def delete(self, uri: str) -> None: ...

    async def read(self, uri: str) -> bytes: ...


class IngestionDispatcher(Protocol):
    def dispatch(self, *, job_id: UUID, material_id: UUID) -> None: ...


class DocumentIndex(Protocol):
    async def search(
        self,
        *,
        knowledge_base_id: UUID,
        query: str,
        limit: int,
        material_id: UUID | None = None,
    ) -> list[SearchHit]: ...

    async def delete_material(self, material_id: UUID) -> None: ...


class QuestionGenerationDispatcher(Protocol):
    def dispatch(self, *, job_id: UUID, material_id: UUID) -> None: ...


class QuestionIndex(Protocol):
    async def upsert_question(self, question: Question) -> str: ...

    async def delete_questions(self, question_ids: Sequence[UUID]) -> None: ...


class StudyExplanationGenerator(Protocol):
    async def explain(
        self, *, question: Question, user_answer: object, correct: bool
    ) -> dict[str, object]: ...
