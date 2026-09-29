import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from celery import Task
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from study_agent.config import get_settings
from study_agent.domain.models import DocumentChunk
from study_agent.infrastructure.factory import get_storage
from study_agent.infrastructure.models import (
    DocumentChunkModel,
    IngestionJobModel,
    MaterialModel,
)
from study_agent.ingestion.chunking import build_chunks
from study_agent.ingestion.factory import get_document_index
from study_agent.ingestion.parsers import parse_document
from study_agent.worker import celery_app

PARSER_VERSION = "p2-v1"


def _identifiers(args: tuple[Any, ...]) -> tuple[UUID | None, UUID | None]:
    if args and isinstance(args[0], dict):
        payload = args[0]
        return UUID(payload["job_id"]), UUID(payload["material_id"])
    if len(args) >= 2:
        return UUID(str(args[0])), UUID(str(args[1]))
    return None, None


async def _with_session(operation: Any) -> Any:
    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            return await operation(session)
    finally:
        await engine.dispose()


async def _mark_failed(job_id: UUID, material_id: UUID, message: str) -> None:
    async def operation(session: Any) -> None:
        job = await session.get(IngestionJobModel, job_id)
        material = await session.get(MaterialModel, material_id)
        safe_message = message[:2000]
        if job:
            job.status = "failed"
            job.error_code = "INGESTION_FAILED"
            job.error_message = safe_message
            job.finished_at = datetime.now(UTC)
        if material:
            material.parse_status = "failed"
            material.error_message = safe_message
        await session.commit()

    await _with_session(operation)


class IngestionTask(Task):
    autoretry_for = (Exception,)
    retry_backoff = True
    retry_kwargs = {"max_retries": 2}

    def on_failure(
        self,
        exc: BaseException,
        task_id: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        einfo: Any,
    ) -> None:
        job_id, material_id = _identifiers(args)
        if job_id and material_id:
            asyncio.run(_mark_failed(job_id, material_id, str(exc)))
        super().on_failure(exc, task_id, args, kwargs, einfo)


@celery_app.task(base=IngestionTask, name="study_agent.parse_material")
def parse_material(job_id: str, material_id: str) -> dict[str, str]:
    async def operation(session: Any) -> dict[str, str]:
        job_uuid = UUID(job_id)
        material_uuid = UUID(material_id)
        job = await session.get(IngestionJobModel, job_uuid)
        material = await session.get(MaterialModel, material_uuid)
        if job is None or material is None:
            raise ValueError("ingestion job or material does not exist")
        job.status = "running"
        job.stage = "parsing"
        job.progress = 10
        job.started_at = job.started_at or datetime.now(UTC)
        job.error_code = None
        job.error_message = None
        material.parse_status = "parsing"
        material.error_message = None
        await session.commit()

        content = await get_storage().read(material.storage_uri)
        documents = parse_document(content, material.original_filename)
        settings = get_settings()
        chunks = build_chunks(
            documents,
            material_id=material_uuid,
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
        )
        existing_models = {
            model.id: model
            for model in (
                await session.scalars(
                    select(DocumentChunkModel).where(
                        DocumentChunkModel.material_id == material_uuid
                    )
                )
            ).all()
        }
        current_ids: set[UUID] = set()
        for chunk in chunks:
            current_ids.add(chunk.id)
            model = existing_models.get(chunk.id)
            if model is None:
                session.add(
                    DocumentChunkModel(
                        id=chunk.id,
                        material_id=chunk.material_id,
                        chunk_index=chunk.chunk_index,
                        content=chunk.content,
                        token_count=chunk.token_count,
                        page_start=chunk.page_start,
                        page_end=chunk.page_end,
                        heading_path=chunk.heading_path,
                        content_hash=chunk.content_hash,
                    )
                )
                continue
            model.chunk_index = chunk.chunk_index
            model.content = chunk.content
            model.token_count = chunk.token_count
            model.page_start = chunk.page_start
            model.page_end = chunk.page_end
            model.heading_path = chunk.heading_path
            model.content_hash = chunk.content_hash

        stale_ids = set(existing_models) - current_ids
        if stale_ids:
            await session.execute(
                delete(DocumentChunkModel).where(DocumentChunkModel.id.in_(stale_ids))
            )
        job.stage = "chunking"
        job.progress = 60
        await session.commit()
        return {"job_id": job_id, "material_id": material_id}

    return asyncio.run(_with_session(operation))


@celery_app.task(base=IngestionTask, name="study_agent.index_material")
def index_material(payload: dict[str, str]) -> dict[str, str]:
    async def operation(session: Any) -> dict[str, str]:
        job_id = UUID(payload["job_id"])
        material_id = UUID(payload["material_id"])
        job = await session.get(IngestionJobModel, job_id)
        material = await session.get(MaterialModel, material_id)
        if job is None or material is None:
            raise ValueError("ingestion job or material does not exist")
        job.stage = "embedding"
        job.progress = 70
        await session.commit()

        models = list(
            (
                await session.scalars(
                    select(DocumentChunkModel)
                    .where(DocumentChunkModel.material_id == material_id)
                    .order_by(DocumentChunkModel.chunk_index)
                )
            ).all()
        )
        chunks = [
            DocumentChunk(
                id=model.id,
                material_id=model.material_id,
                chunk_index=model.chunk_index,
                content=model.content,
                token_count=model.token_count,
                page_start=model.page_start,
                page_end=model.page_end,
                heading_path=model.heading_path,
                content_hash=model.content_hash,
                vector_id=model.vector_id,
                embedding_model=model.embedding_model,
                created_at=model.created_at,
            )
            for model in models
        ]
        index = get_document_index()
        vector_ids = await index.upsert(
            knowledge_base_id=material.knowledge_base_id,
            chunks=chunks,
        )
        for model, vector_id in zip(models, vector_ids, strict=True):
            model.vector_id = vector_id
            model.embedding_model = index.embedding_model
        job.progress = 90
        await session.commit()
        return payload

    return asyncio.run(_with_session(operation))


@celery_app.task(base=IngestionTask, name="study_agent.finish_ingestion")
def finish_ingestion(payload: dict[str, str]) -> dict[str, str]:
    async def operation(session: Any) -> dict[str, str]:
        job = await session.get(IngestionJobModel, UUID(payload["job_id"]))
        material = await session.get(MaterialModel, UUID(payload["material_id"]))
        if job is None or material is None:
            raise ValueError("ingestion job or material does not exist")
        job.status = "completed"
        job.stage = "completed"
        job.progress = 100
        job.finished_at = datetime.now(UTC)
        material.parse_status = "ready"
        material.parser_version = PARSER_VERSION
        material.error_message = None
        await session.commit()
        return payload

    return asyncio.run(_with_session(operation))
