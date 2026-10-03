from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import BinaryIO
from uuid import UUID

from study_agent.domain.models import (
    DocumentChunk,
    IngestionJob,
    KnowledgeBase,
    Material,
    Question,
    QuestionGenerationJob,
    SearchHit,
    StoredObject,
)


class FakeKnowledgeBaseRepository:
    def __init__(self) -> None:
        self.items: dict[UUID, KnowledgeBase] = {}

    async def add(self, knowledge_base: KnowledgeBase) -> KnowledgeBase:
        self.items[knowledge_base.id] = knowledge_base
        return knowledge_base

    async def get(self, knowledge_base_id: UUID) -> KnowledgeBase | None:
        item = self.items.get(knowledge_base_id)
        return item if item is not None and item.status != "deleted" else None

    async def list(
        self, *, page: int, page_size: int, status: str | None, keyword: str | None
    ) -> tuple[Sequence[KnowledgeBase], int]:
        values = [item for item in self.items.values() if item.status != "deleted"]
        if status:
            values = [item for item in values if item.status == status]
        if keyword:
            values = [item for item in values if keyword.lower() in item.name.lower()]
        total = len(values)
        start = (page - 1) * page_size
        return values[start : start + page_size], total

    async def update(self, knowledge_base: KnowledgeBase) -> KnowledgeBase:
        self.items[knowledge_base.id] = knowledge_base
        return knowledge_base


class FakeMaterialRepository:
    def __init__(self) -> None:
        self.items: dict[UUID, Material] = {}

    async def add(self, material: Material) -> Material:
        self.items[material.id] = material
        return material

    async def get(self, material_id: UUID) -> Material | None:
        return self.items.get(material_id)

    async def get_by_hash(self, knowledge_base_id: UUID, sha256: str) -> Material | None:
        return next(
            (
                item
                for item in self.items.values()
                if item.knowledge_base_id == knowledge_base_id and item.sha256 == sha256
            ),
            None,
        )

    async def list(
        self, *, knowledge_base_id: UUID, page: int, page_size: int, status: str | None
    ) -> tuple[Sequence[Material], int]:
        values = [
            item for item in self.items.values() if item.knowledge_base_id == knowledge_base_id
        ]
        if status:
            values = [item for item in values if item.parse_status == status]
        total = len(values)
        start = (page - 1) * page_size
        return values[start : start + page_size], total

    async def delete(self, material_id: UUID) -> None:
        self.items.pop(material_id, None)


class FakeIngestionJobRepository:
    def __init__(self) -> None:
        self.items: dict[UUID, IngestionJob] = {}

    async def add(self, job: IngestionJob) -> IngestionJob:
        self.items[job.id] = job
        return job

    async def get(self, job_id: UUID) -> IngestionJob | None:
        return self.items.get(job_id)

    async def has_running_for_material(self, material_id: UUID) -> bool:
        return any(
            item.material_id == material_id and item.status in {"pending", "running"}
            for item in self.items.values()
        )

    async def fail_dispatch(self, job_id: UUID) -> None:
        self.items[job_id] = replace(
            self.items[job_id],
            status="failed",
            stage="failed",
            error_code="TASK_QUEUE_UNAVAILABLE",
            finished_at=datetime.now(UTC),
        )


class FakeDocumentChunkRepository:
    def __init__(self) -> None:
        self.items: dict[UUID, list[DocumentChunk]] = {}

    async def list_for_material(self, material_id: UUID) -> Sequence[DocumentChunk]:
        return self.items.get(material_id, [])


class FakeQuestionGenerationJobRepository:
    def __init__(self) -> None:
        self.items: dict[UUID, QuestionGenerationJob] = {}

    async def add(self, job: QuestionGenerationJob) -> QuestionGenerationJob:
        self.items[job.id] = job
        return job

    async def get(self, job_id: UUID) -> QuestionGenerationJob | None:
        return self.items.get(job_id)

    async def list_for_material(self, material_id: UUID) -> Sequence[QuestionGenerationJob]:
        values = [job for job in self.items.values() if job.material_id == material_id]
        return sorted(values, key=lambda job: job.created_at or datetime.min.replace(tzinfo=UTC),
                      reverse=True)[:5]

    async def has_running_for_material(self, material_id: UUID) -> bool:
        return any(
            item.material_id == material_id and item.status in {"pending", "running"}
            for item in self.items.values()
        )

    async def fail_dispatch(self, job_id: UUID) -> None:
        self.items[job_id] = replace(
            self.items[job_id],
            status="failed",
            stage="failed",
            error_code="TASK_QUEUE_UNAVAILABLE",
            finished_at=datetime.now(UTC),
        )


class FakeQuestionRepository:
    def __init__(self) -> None:
        self.items: dict[UUID, Question] = {}

    async def invalidate_sources(self, chunk_ids: Sequence[UUID]) -> Sequence[Question]:
        orphaned = []
        for question in list(self.items.values()):
            sources = [source for source in question.sources if source.chunk_id not in chunk_ids]
            updated = replace(question, sources=sources)
            if not sources and (question.status == "active" or question.vector_id):
                updated = replace(
                    updated, status="disabled" if question.status == "active" else question.status
                )
                orphaned.append(updated)
            self.items[question.id] = updated
        return orphaned

    async def get(self, question_id: UUID) -> Question | None:
        return self.items.get(question_id)

    async def list(
        self,
        *,
        knowledge_base_id: UUID | None,
        material_id: UUID | None,
        question_type: str | None,
        status: str | None,
        page: int,
        page_size: int,
    ) -> tuple[Sequence[Question], int]:
        del material_id
        values = [item for item in self.items.values() if item.status != "deleted"]
        if knowledge_base_id:
            values = [item for item in values if item.knowledge_base_id == knowledge_base_id]
        if question_type:
            values = [item for item in values if item.question_type == question_type]
        if status:
            values = [item for item in values if item.status == status]
        total = len(values)
        start = (page - 1) * page_size
        return values[start : start + page_size], total

    async def update(self, question: Question) -> Question:
        self.items[question.id] = question
        return question


class FakeUnitOfWork:
    def __init__(self) -> None:
        self.knowledge_bases = FakeKnowledgeBaseRepository()
        self.materials = FakeMaterialRepository()
        self.ingestion_jobs = FakeIngestionJobRepository()
        self.document_chunks = FakeDocumentChunkRepository()
        self.question_generation_jobs = FakeQuestionGenerationJobRepository()
        self.questions = FakeQuestionRepository()
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def lock(self, key: UUID) -> None:
        pass


class FakeObjectStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put(
        self,
        *,
        object_name: str,
        stream: BinaryIO,
        size: int,
        content_type: str,
    ) -> StoredObject:
        del content_type
        stream.seek(0)
        content = stream.read()
        assert len(content) == size
        self.objects[object_name] = content
        return StoredObject(uri=f"fake://{object_name}", object_name=object_name)

    async def delete(self, uri: str) -> None:
        self.objects.pop(uri.removeprefix("fake://"), None)

    async def read(self, uri: str) -> bytes:
        return self.objects[uri.removeprefix("fake://")]


class FakeIngestionDispatcher:
    def __init__(self) -> None:
        self.dispatched: list[tuple[UUID, UUID]] = []

    def dispatch(self, *, job_id: UUID, material_id: UUID) -> None:
        self.dispatched.append((job_id, material_id))


class FakeQuestionGenerationDispatcher(FakeIngestionDispatcher):
    pass


class FakeQuestionIndex:
    def __init__(self) -> None:
        self.upserted: list[Question] = []
        self.deleted: list[UUID] = []

    async def delete_questions(self, question_ids: Sequence[UUID]) -> None:
        self.deleted.extend(question_ids)

    async def upsert_question(self, question: Question) -> str:
        self.upserted.append(question)
        return str(question.id)


class FakeDocumentIndex:
    def __init__(self) -> None:
        self.deleted_material_ids: list[UUID] = []
        self.hits: list[SearchHit] = []

    async def search(
        self,
        *,
        knowledge_base_id: UUID,
        query: str,
        limit: int,
        material_id: UUID | None = None,
    ) -> list[SearchHit]:
        del knowledge_base_id, query, material_id
        return self.hits[:limit]

    async def delete_material(self, material_id: UUID) -> None:
        self.deleted_material_ids.append(material_id)
