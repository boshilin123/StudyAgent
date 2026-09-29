from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query, status

from study_agent.api.dependencies import UnitOfWorkDependency
from study_agent.api.schemas import (
    KnowledgeBaseCreate,
    KnowledgeBasePage,
    KnowledgeBaseResponse,
    KnowledgeBaseUpdate,
)
from study_agent.application.knowledge_bases import KnowledgeBaseService

router = APIRouter()
service = KnowledgeBaseService()


@router.post("", response_model=KnowledgeBaseResponse, status_code=status.HTTP_201_CREATED)
async def create_knowledge_base(
    payload: KnowledgeBaseCreate,
    uow: UnitOfWorkDependency,
) -> KnowledgeBaseResponse:
    result = await service.create(
        uow,
        name=payload.name,
        description=payload.description,
        language=payload.language,
    )
    return KnowledgeBaseResponse.model_validate(result)


@router.get("", response_model=KnowledgeBasePage)
async def list_knowledge_bases(
    uow: UnitOfWorkDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    status_filter: Annotated[Literal["active", "archived"] | None, Query(alias="status")] = None,
    keyword: Annotated[str | None, Query(max_length=200)] = None,
) -> KnowledgeBasePage:
    items, total = await service.list(
        uow,
        page=page,
        page_size=page_size,
        status=status_filter,
        keyword=keyword,
    )
    return KnowledgeBasePage(
        items=[KnowledgeBaseResponse.model_validate(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/{knowledge_base_id}", response_model=KnowledgeBaseResponse)
async def get_knowledge_base(
    knowledge_base_id: UUID,
    uow: UnitOfWorkDependency,
) -> KnowledgeBaseResponse:
    result = await service.get(uow, knowledge_base_id)
    return KnowledgeBaseResponse.model_validate(result)


@router.patch("/{knowledge_base_id}", response_model=KnowledgeBaseResponse)
async def update_knowledge_base(
    knowledge_base_id: UUID,
    payload: KnowledgeBaseUpdate,
    uow: UnitOfWorkDependency,
) -> KnowledgeBaseResponse:
    result = await service.update(
        uow,
        knowledge_base_id,
        name=payload.name,
        description=payload.description,
        language=payload.language,
        status=payload.status,
        description_is_set="description" in payload.model_fields_set,
    )
    return KnowledgeBaseResponse.model_validate(result)
