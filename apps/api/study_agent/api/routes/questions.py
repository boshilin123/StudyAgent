from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query, status

from study_agent.api.dependencies import (
    QuestionGenerationDispatcherDependency,
    QuestionIndexDependency,
    UnitOfWorkDependency,
)
from study_agent.api.schemas import (
    QuestionGenerationCreate,
    QuestionGenerationJobResponse,
    QuestionPage,
    QuestionResponse,
    QuestionUpdate,
)
from study_agent.application.questions import QuestionService
from study_agent.domain.errors import DomainError

router = APIRouter()
material_router = APIRouter()
job_router = APIRouter()
service = QuestionService()


@material_router.post(
    "/{material_id}/question-generation-jobs",
    response_model=QuestionGenerationJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_question_generation_job(
    material_id: UUID,
    payload: QuestionGenerationCreate,
    uow: UnitOfWorkDependency,
    dispatcher: QuestionGenerationDispatcherDependency,
) -> QuestionGenerationJobResponse:
    if payload.difficulty_min > payload.difficulty_max:
        raise DomainError(
            "INVALID_DIFFICULTY_RANGE", "最低难度不能高于最高难度", status_code=422
        )
    job = await service.create_generation_job(
        uow,
        dispatcher,
        material_id=material_id,
        target_question_count=payload.target_question_count,
        allowed_types=list(dict.fromkeys(payload.allowed_types)),
        difficulty_min=payload.difficulty_min,
        difficulty_max=payload.difficulty_max,
        language=payload.language,
    )
    return QuestionGenerationJobResponse.model_validate(job)


@job_router.get("/{job_id}", response_model=QuestionGenerationJobResponse)
async def get_question_generation_job(
    job_id: UUID, uow: UnitOfWorkDependency
) -> QuestionGenerationJobResponse:
    return QuestionGenerationJobResponse.model_validate(
        await service.get_generation_job(uow, job_id)
    )


@router.get("", response_model=QuestionPage)
async def list_questions(
    uow: UnitOfWorkDependency,
    knowledge_base_id: UUID | None = None,
    material_id: UUID | None = None,
    question_type: Literal["single_choice", "fill_blank", "true_false"] | None = None,
    status_filter: Annotated[
        Literal["draft", "active", "disabled", "rejected"] | None, Query(alias="status")
    ] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> QuestionPage:
    items, total = await service.list(
        uow,
        knowledge_base_id=knowledge_base_id,
        material_id=material_id,
        question_type=question_type,
        status=status_filter,
        page=page,
        page_size=page_size,
    )
    return QuestionPage(
        items=[QuestionResponse.model_validate(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/{question_id}", response_model=QuestionResponse)
async def get_question(question_id: UUID, uow: UnitOfWorkDependency) -> QuestionResponse:
    return QuestionResponse.model_validate(await service.get(uow, question_id))


@router.patch("/{question_id}", response_model=QuestionResponse)
async def update_question(
    question_id: UUID,
    payload: QuestionUpdate,
    uow: UnitOfWorkDependency,
    question_index: QuestionIndexDependency,
) -> QuestionResponse:
    question = await service.update(
        uow,
        question_index,
        question_id,
        stem=payload.stem,
        options=payload.options,
        correct_answers=payload.correct_answers,
        explanation=payload.explanation,
        difficulty=payload.difficulty,
        options_is_set="options" in payload.model_fields_set,
    )
    return QuestionResponse.model_validate(question)


@router.post("/{question_id}/activate", response_model=QuestionResponse)
async def activate_question(
    question_id: UUID,
    uow: UnitOfWorkDependency,
    question_index: QuestionIndexDependency,
) -> QuestionResponse:
    return QuestionResponse.model_validate(
        await service.set_status(uow, question_index, question_id, "active")
    )


@router.post("/{question_id}/disable", response_model=QuestionResponse)
async def disable_question(
    question_id: UUID,
    uow: UnitOfWorkDependency,
    question_index: QuestionIndexDependency,
) -> QuestionResponse:
    return QuestionResponse.model_validate(
        await service.set_status(uow, question_index, question_id, "disabled")
    )
