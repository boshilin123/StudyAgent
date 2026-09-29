from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from study_agent.application.study_explanations import LangChainStudyExplanationGenerator
from study_agent.config import get_settings
from study_agent.domain.ports import (
    DocumentIndex,
    IngestionDispatcher,
    ObjectStorage,
    QuestionGenerationDispatcher,
    QuestionIndex,
    StudyExplanationGenerator,
    StudyStateStore,
)
from study_agent.infrastructure.database import get_session
from study_agent.infrastructure.factory import get_storage
from study_agent.infrastructure.study_state import RedisStudyStateStore
from study_agent.infrastructure.unit_of_work import SqlAlchemyUnitOfWork
from study_agent.ingestion.dispatcher import CeleryIngestionDispatcher
from study_agent.ingestion.factory import get_document_index
from study_agent.question_generation.dispatcher import CeleryQuestionGenerationDispatcher
from study_agent.question_generation.factory import get_question_index


async def get_uow(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AsyncIterator[SqlAlchemyUnitOfWork]:
    yield SqlAlchemyUnitOfWork(session)


@lru_cache
def get_object_storage() -> ObjectStorage:
    return get_storage()


@lru_cache
def get_ingestion_dispatcher() -> IngestionDispatcher:
    return CeleryIngestionDispatcher()


def get_vector_index() -> DocumentIndex:
    return get_document_index()


@lru_cache
def get_question_generation_dispatcher() -> QuestionGenerationDispatcher:
    return CeleryQuestionGenerationDispatcher()


def get_question_vector_index() -> QuestionIndex:
    return get_question_index()


@lru_cache
def get_study_explanation_generator() -> StudyExplanationGenerator:
    return LangChainStudyExplanationGenerator(get_settings())


@lru_cache
def get_study_state_store() -> StudyStateStore:
    settings = get_settings()
    return RedisStudyStateStore(
        redis_url=settings.redis_url, ttl_seconds=settings.session_ttl_seconds
    )


UnitOfWorkDependency = Annotated[SqlAlchemyUnitOfWork, Depends(get_uow)]
StorageDependency = Annotated[ObjectStorage, Depends(get_object_storage)]
IngestionDispatcherDependency = Annotated[IngestionDispatcher, Depends(get_ingestion_dispatcher)]
DocumentIndexDependency = Annotated[DocumentIndex, Depends(get_vector_index)]
QuestionGenerationDispatcherDependency = Annotated[
    QuestionGenerationDispatcher, Depends(get_question_generation_dispatcher)
]
QuestionIndexDependency = Annotated[QuestionIndex, Depends(get_question_vector_index)]
StudyExplanationDependency = Annotated[
    StudyExplanationGenerator, Depends(get_study_explanation_generator)
]
StudyStateDependency = Annotated[StudyStateStore, Depends(get_study_state_store)]
