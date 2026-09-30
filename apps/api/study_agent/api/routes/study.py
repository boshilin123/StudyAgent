from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from study_agent.api.dependencies import (
    StudyExplanationDependency,
    StudyStateDependency,
    UnitOfWorkDependency,
)
from study_agent.api.schemas import (
    AnswerResultResponse,
    AnswerSubmit,
    MasteryResponse,
    PublicQuestionResponse,
    ReviewTaskResponse,
    StudyHistoryPage,
    StudySessionCreate,
    StudySessionResponse,
)
from study_agent.application.study import AnswerResult, SessionView, StudyService
from study_agent.domain.errors import DomainError
from study_agent.domain.models import Question, StudySession

router = APIRouter()
mastery_router = APIRouter()
review_router = APIRouter()
service = StudyService()


def _public_question(
    question: Question | None,
    sequence: int,
    selection_reason: dict[str, object] | None = None,
) -> PublicQuestionResponse | None:
    if question is None:
        return None
    return PublicQuestionResponse(
        id=question.id,
        sequence=sequence,
        question_type=question.question_type,
        stem=question.stem,
        options=question.options,
        difficulty=question.difficulty,
        max_score=question.max_score,
        selection_reason=selection_reason,
    )


def _session_response(
    study_session: StudySession,
    question: Question | None = None,
    selection_reason: dict[str, object] | None = None,
) -> StudySessionResponse:
    return StudySessionResponse(
        id=study_session.id,
        knowledge_base_id=study_session.knowledge_base_id,
        mode=study_session.mode,
        status=study_session.status,
        planned_question_count=study_session.planned_question_count,
        answered_question_count=study_session.answered_question_count,
        correct_count=study_session.correct_count,
        incorrect_count=study_session.incorrect_count,
        total_score=study_session.total_score,
        max_total_score=study_session.max_total_score,
        started_at=study_session.started_at,
        finished_at=study_session.finished_at,
        current_question=_public_question(
            question, study_session.answered_question_count + 1, selection_reason
        ),
    )


def _view_response(view: SessionView) -> StudySessionResponse:
    return _session_response(view.session, view.current_question, view.selection_reason)


def _answer_response(result: AnswerResult) -> AnswerResultResponse:
    return AnswerResultResponse(
        submission_id=result.answer_record.submission_id,
        question_id=result.answer_record.question_id,
        verdict=result.answer_record.verdict,
        score=result.answer_record.score,
        max_score=result.answer_record.max_score,
        feedback=result.answer_record.feedback,
        explanation=result.explanation,
        rag_explanation=result.explanation_data,
        idempotent_replay=result.idempotent_replay,
        mastery=MasteryResponse.model_validate(result.mastery),
        review_task=ReviewTaskResponse.model_validate(result.review_task),
        session=_session_response(
            result.session, result.next_question, result.next_selection_reason
        ),
    )


@router.post("/sessions", response_model=StudySessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    payload: StudySessionCreate,
    uow: UnitOfWorkDependency,
    state_store: StudyStateDependency,
) -> StudySessionResponse:
    if payload.difficulty_min > payload.difficulty_max:
        raise DomainError("INVALID_DIFFICULTY_RANGE", "最低难度不能高于最高难度", status_code=422)
    view = await service.create_session(
        uow,
        knowledge_base_id=payload.knowledge_base_id,
        mode=payload.mode,
        question_count=payload.question_count,
        question_types=list(dict.fromkeys(payload.question_types)),
        difficulty_min=payload.difficulty_min,
        difficulty_max=payload.difficulty_max,
        state_store=state_store,
    )
    return _view_response(view)


@router.get("/sessions/{session_id}", response_model=StudySessionResponse)
async def get_session(
    session_id: UUID,
    uow: UnitOfWorkDependency,
    state_store: StudyStateDependency,
) -> StudySessionResponse:
    return _view_response(await service.get_session(uow, session_id, state_store))


@router.post("/sessions/{session_id}/answers", response_model=AnswerResultResponse)
async def submit_answer(
    session_id: UUID,
    payload: AnswerSubmit,
    uow: UnitOfWorkDependency,
    explanation_generator: StudyExplanationDependency,
    state_store: StudyStateDependency,
) -> AnswerResultResponse:
    result = await service.submit_answer(
        uow,
        session_id=session_id,
        submission_id=payload.submission_id,
        question_id=payload.question_id,
        answer=payload.answer,
        elapsed_seconds=payload.elapsed_seconds,
        explanation_generator=explanation_generator,
        state_store=state_store,
    )
    return _answer_response(result)


@router.post("/sessions/{session_id}/finish", response_model=StudySessionResponse)
async def finish_session(
    session_id: UUID,
    uow: UnitOfWorkDependency,
    state_store: StudyStateDependency,
) -> StudySessionResponse:
    return _view_response(await service.finish_session(uow, session_id, state_store))


@router.get("/history", response_model=StudyHistoryPage)
async def list_history(
    uow: UnitOfWorkDependency,
    knowledge_base_id: UUID | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> StudyHistoryPage:
    items, total = await service.list_history(
        uow, knowledge_base_id=knowledge_base_id, page=page, page_size=page_size
    )
    return StudyHistoryPage(
        items=[_session_response(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
    )


@mastery_router.get("", response_model=list[MasteryResponse])
async def list_mastery(
    uow: UnitOfWorkDependency, knowledge_base_id: UUID | None = None
) -> list[MasteryResponse]:
    return [
        MasteryResponse.model_validate(item) for item in await uow.mastery.list(knowledge_base_id)
    ]


@review_router.get("/due", response_model=list[ReviewTaskResponse])
async def list_due_reviews(
    uow: UnitOfWorkDependency,
    knowledge_base_id: UUID | None = None,
    due_before: datetime | None = None,
) -> list[ReviewTaskResponse]:
    deadline = due_before or datetime.now(UTC)
    return [
        ReviewTaskResponse.model_validate(item)
        for item in await uow.review_tasks.list_due(
            knowledge_base_id=knowledge_base_id, due_before=deadline
        )
    ]
