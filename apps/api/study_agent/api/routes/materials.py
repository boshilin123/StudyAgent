import hashlib
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, File, Form, Query, UploadFile, status
from fastapi.responses import Response

from study_agent.api.dependencies import (
    DocumentIndexDependency,
    IngestionDispatcherDependency,
    QuestionIndexDependency,
    StorageDependency,
    UnitOfWorkDependency,
)
from study_agent.api.schemas import (
    DocumentChunkResponse,
    IngestionJobResponse,
    MaterialPage,
    MaterialResponse,
    MaterialUploadResponse,
    SearchHitResponse,
    SearchResponse,
)
from study_agent.application.materials import MaterialService
from study_agent.config import get_settings
from study_agent.domain.errors import DomainError
from study_agent.domain.models import UploadPayload

knowledge_base_router = APIRouter()
material_router = APIRouter()
job_router = APIRouter()
service = MaterialService()

ALLOWED_SUFFIXES = {".pdf", ".docx", ".pptx", ".txt", ".md", ".markdown", ".xlsx"}
DEFAULT_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
ALLOWED_MEDIA_TYPES = {
    ".pdf": {"application/pdf"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    ".pptx": {"application/vnd.openxmlformats-officedocument.presentationml.presentation"},
    ".txt": {"text/plain"},
    ".md": {"text/markdown", "text/plain"},
    ".markdown": {"text/markdown", "text/plain"},
    ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
}


async def _inspect_upload(file: UploadFile, title: str | None) -> UploadPayload:
    original_filename = Path(file.filename or "").name
    suffix = Path(original_filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise DomainError(
            "UNSUPPORTED_FILE_TYPE",
            "不支持该文件类型",
            status_code=422,
            details={"suffix": suffix},
        )

    digest = hashlib.sha256()
    size = 0
    max_size = get_settings().max_upload_size_mb * 1024 * 1024
    while chunk := await file.read(1024 * 1024):
        size += len(chunk)
        if size > max_size:
            raise DomainError("FILE_TOO_LARGE", "文件超过大小限制", status_code=413)
        digest.update(chunk)
    await file.seek(0)
    if size == 0:
        raise DomainError("EMPTY_FILE", "不能上传空文件", status_code=422)

    clean_title = (title or Path(original_filename).stem).strip()
    if not clean_title or len(clean_title) > 300:
        raise DomainError("INVALID_MATERIAL_TITLE", "资料标题不合法", status_code=422)
    supplied_media_type = (file.content_type or "").lower()
    if (
        supplied_media_type not in {"", "application/octet-stream"}
        and supplied_media_type not in (ALLOWED_MEDIA_TYPES[suffix])
    ):
        raise DomainError(
            "INVALID_MEDIA_TYPE",
            "文件 MIME 类型与扩展名不匹配",
            status_code=422,
            details={"suffix": suffix, "media_type": supplied_media_type},
        )
    media_type = (
        DEFAULT_MEDIA_TYPES[suffix]
        if supplied_media_type in {"", "application/octet-stream"}
        else supplied_media_type
    )
    return UploadPayload(
        stream=file.file,
        original_filename=original_filename,
        title=clean_title,
        media_type=media_type,
        size_bytes=size,
        sha256=digest.hexdigest(),
        suffix=suffix,
    )


@knowledge_base_router.post(
    "/{knowledge_base_id}/materials",
    response_model=MaterialUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_material(
    knowledge_base_id: UUID,
    uow: UnitOfWorkDependency,
    storage: StorageDependency,
    dispatcher: IngestionDispatcherDependency,
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form(max_length=300)] = None,
) -> MaterialUploadResponse:
    payload = await _inspect_upload(file, title)
    material, job = await service.create(
        uow,
        storage,
        knowledge_base_id=knowledge_base_id,
        payload=payload,
    )
    try:
        dispatcher.dispatch(job_id=job.id, material_id=material.id)
    except Exception as exc:
        await uow.ingestion_jobs.fail_dispatch(job.id)
        await uow.commit()
        raise DomainError(
            "TASK_QUEUE_UNAVAILABLE", "资料处理任务派发失败，可重新处理", status_code=503
        ) from exc
    return MaterialUploadResponse(
        material=MaterialResponse.model_validate(material),
        job=IngestionJobResponse.model_validate(job),
    )


@knowledge_base_router.get("/{knowledge_base_id}/materials", response_model=MaterialPage)
async def list_materials(
    knowledge_base_id: UUID,
    uow: UnitOfWorkDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    status_filter: Annotated[
        Literal["pending", "parsing", "ready", "partial", "failed"] | None,
        Query(alias="status"),
    ] = None,
) -> MaterialPage:
    items, total = await service.list(
        uow,
        knowledge_base_id=knowledge_base_id,
        page=page,
        page_size=page_size,
        status=status_filter,
    )
    return MaterialPage(
        items=[MaterialResponse.model_validate(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
    )


@material_router.get("/{material_id}", response_model=MaterialResponse)
async def get_material(
    material_id: UUID,
    uow: UnitOfWorkDependency,
) -> MaterialResponse:
    return MaterialResponse.model_validate(await service.get(uow, material_id))


@material_router.post(
    "/{material_id}/reprocess",
    response_model=IngestionJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def reprocess_material(
    material_id: UUID,
    uow: UnitOfWorkDependency,
    dispatcher: IngestionDispatcherDependency,
) -> IngestionJobResponse:
    job = await service.reprocess(uow, dispatcher, material_id)
    return IngestionJobResponse.model_validate(job)


@material_router.delete("/{material_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_material(
    material_id: UUID,
    uow: UnitOfWorkDependency,
    storage: StorageDependency,
    document_index: DocumentIndexDependency,
    question_index: QuestionIndexDependency,
) -> Response:
    await service.delete(uow, storage, document_index, material_id, question_index)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@material_router.get("/{material_id}/chunks", response_model=list[DocumentChunkResponse])
async def list_material_chunks(
    material_id: UUID,
    uow: UnitOfWorkDependency,
) -> list[DocumentChunkResponse]:
    chunks = await service.list_chunks(uow, material_id)
    return [DocumentChunkResponse.model_validate(chunk) for chunk in chunks]


@knowledge_base_router.get("/{knowledge_base_id}/search", response_model=SearchResponse)
async def search_materials(
    knowledge_base_id: UUID,
    uow: UnitOfWorkDependency,
    document_index: DocumentIndexDependency,
    q: Annotated[str, Query(min_length=1, max_length=1000)],
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
    material_id: UUID | None = None,
) -> SearchResponse:
    if await uow.knowledge_bases.get(knowledge_base_id) is None:
        raise DomainError("KNOWLEDGE_BASE_NOT_FOUND", "知识库不存在", status_code=404)
    hits = await document_index.search(
        knowledge_base_id=knowledge_base_id,
        query=q,
        limit=limit,
        material_id=material_id,
    )
    # Vector writes are not a PostgreSQL transaction. Never expose stale chunks
    # while a material is reprocessing, or after an interrupted index cleanup.
    valid_hits = []
    valid_ids: dict[UUID, set[UUID]] = {}
    for hit in hits:
        if hit.material_id not in valid_ids:
            material = await uow.materials.get(hit.material_id)
            chunks = (
                await uow.document_chunks.list_for_material(hit.material_id)
                if material and material.parse_status == "ready"
                else []
            )
            valid_ids[hit.material_id] = {chunk.id for chunk in chunks}
        if hit.chunk_id in valid_ids[hit.material_id]:
            valid_hits.append(hit)
    return SearchResponse(
        query=q,
        items=[SearchHitResponse.model_validate(hit) for hit in valid_hits],
    )


@job_router.get("/{job_id}", response_model=IngestionJobResponse)
async def get_ingestion_job(
    job_id: UUID,
    uow: UnitOfWorkDependency,
) -> IngestionJobResponse:
    return IngestionJobResponse.model_validate(await service.get_job(uow, job_id))
