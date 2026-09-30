from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from study_agent.domain.errors import DomainError
from study_agent.domain.models import DocumentChunk, IngestionJob, Material, UploadPayload
from study_agent.domain.ports import (
    DocumentIndex,
    IngestionDispatcher,
    ObjectStorage,
    QuestionIndex,
    UnitOfWork,
)


class MaterialService:
    async def create(
        self,
        uow: UnitOfWork,
        storage: ObjectStorage,
        *,
        knowledge_base_id: UUID,
        payload: UploadPayload,
    ) -> tuple[Material, IngestionJob]:
        knowledge_base = await uow.knowledge_bases.get(knowledge_base_id)
        if knowledge_base is None:
            raise DomainError("KNOWLEDGE_BASE_NOT_FOUND", "知识库不存在", status_code=404)
        if knowledge_base.status != "active":
            raise DomainError("KNOWLEDGE_BASE_ARCHIVED", "归档知识库不能上传资料", status_code=409)
        duplicate = await uow.materials.get_by_hash(knowledge_base_id, payload.sha256)
        if duplicate is not None:
            raise DomainError(
                "DUPLICATE_MATERIAL",
                "相同内容的资料已经存在",
                status_code=409,
                details={"material_id": str(duplicate.id)},
            )

        material_id = uuid4()
        object_name = f"knowledge-bases/{knowledge_base_id}/materials/{material_id}{payload.suffix}"
        try:
            stored = await storage.put(
                object_name=object_name,
                stream=payload.stream,
                size=payload.size_bytes,
                content_type=payload.media_type,
            )
        except Exception as exc:
            raise DomainError("STORAGE_UNAVAILABLE", "资料保存失败", status_code=503) from exc

        now = datetime.now(UTC)
        material = Material(
            id=material_id,
            knowledge_base_id=knowledge_base_id,
            title=payload.title,
            original_filename=payload.original_filename,
            media_type=payload.media_type,
            storage_uri=stored.uri,
            sha256=payload.sha256,
            size_bytes=payload.size_bytes,
            language=knowledge_base.language,
            parse_status="pending",
            parser_version=None,
            error_message=None,
            created_at=now,
            updated_at=now,
        )
        job = IngestionJob(
            id=uuid4(),
            material_id=material.id,
            status="pending",
            stage="uploaded",
            progress=0,
            created_at=now,
        )
        try:
            material = await uow.materials.add(material)
            job = await uow.ingestion_jobs.add(job)
            await uow.commit()
        except Exception:
            await uow.rollback()
            await storage.delete(stored.uri)
            raise
        return material, job

    async def get(self, uow: UnitOfWork, material_id: UUID) -> Material:
        material = await uow.materials.get(material_id)
        if material is None:
            raise DomainError("MATERIAL_NOT_FOUND", "资料不存在", status_code=404)
        return material

    async def reprocess(
        self,
        uow: UnitOfWork,
        dispatcher: IngestionDispatcher,
        material_id: UUID,
    ) -> IngestionJob:
        await uow.lock(material_id)
        material = await self.get(uow, material_id)
        if await uow.ingestion_jobs.has_running_for_material(material_id):
            raise DomainError("MATERIAL_JOB_RUNNING", "资料仍有运行中的任务", status_code=409)
        if await uow.question_generation_jobs.has_running_for_material(material_id):
            raise DomainError("QUESTION_GENERATION_RUNNING", "资料仍在生成题目", status_code=409)

        now = datetime.now(UTC)
        job = IngestionJob(
            id=uuid4(),
            material_id=material.id,
            status="pending",
            stage="reprocessing",
            progress=0,
            generation_config={"reason": "manual_reprocess"},
            created_at=now,
        )
        job = await uow.ingestion_jobs.add(job)
        await uow.commit()
        try:
            dispatcher.dispatch(job_id=job.id, material_id=material.id)
        except Exception as exc:
            await uow.ingestion_jobs.fail_dispatch(job.id)
            await uow.commit()
            raise DomainError(
                "TASK_QUEUE_UNAVAILABLE", "资料重新处理任务提交失败", status_code=503
            ) from exc
        return job

    async def list(
        self,
        uow: UnitOfWork,
        *,
        knowledge_base_id: UUID,
        page: int,
        page_size: int,
        status: str | None,
    ) -> tuple[list[Material], int]:
        if await uow.knowledge_bases.get(knowledge_base_id) is None:
            raise DomainError("KNOWLEDGE_BASE_NOT_FOUND", "知识库不存在", status_code=404)
        items, total = await uow.materials.list(
            knowledge_base_id=knowledge_base_id,
            page=page,
            page_size=page_size,
            status=status,
        )
        return list(items), total

    async def delete(
        self,
        uow: UnitOfWork,
        storage: ObjectStorage,
        document_index: DocumentIndex,
        material_id: UUID,
        question_index: QuestionIndex,
    ) -> None:
        await uow.lock(material_id)
        material = await self.get(uow, material_id)
        if await uow.ingestion_jobs.has_running_for_material(material_id):
            raise DomainError("MATERIAL_JOB_RUNNING", "资料仍有运行中的任务", status_code=409)
        if await uow.question_generation_jobs.has_running_for_material(material_id):
            raise DomainError("QUESTION_GENERATION_RUNNING", "资料仍在生成题目", status_code=409)
        chunks = await uow.document_chunks.list_for_material(material_id)
        orphaned = await uow.questions.invalidate_sources([chunk.id for chunk in chunks])
        await question_index.delete_questions([question.id for question in orphaned])
        for question in orphaned:
            await uow.questions.update(replace(question, vector_id=None))
        await document_index.delete_material(material_id)
        await storage.delete(material.storage_uri)
        await uow.materials.delete(material_id)
        await uow.commit()

    async def list_chunks(self, uow: UnitOfWork, material_id: UUID) -> Sequence[DocumentChunk]:
        await self.get(uow, material_id)
        return await uow.document_chunks.list_for_material(material_id)

    async def get_job(self, uow: UnitOfWork, job_id: UUID) -> IngestionJob:
        job = await uow.ingestion_jobs.get(job_id)
        if job is None:
            raise DomainError("INGESTION_JOB_NOT_FOUND", "处理任务不存在", status_code=404)
        return job
