from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

from study_agent.application.knowledge_bases import KnowledgeBaseService
from study_agent.application.learning_queries import LearningQueries
from study_agent.application.study import StudyService
from study_agent.domain.errors import DomainError
from study_agent.infrastructure.models import KnowledgeBaseModel, MaterialModel, QuestionModel
from study_agent.infrastructure.tutoring_models import TutorConversationModel
from study_agent.infrastructure.unit_of_work import SqlAlchemyUnitOfWork
from tests.test_postgres_reliability import seeded_database as seeded_database

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_library_delete_retains_children_and_prevents_new_activity(
    seeded_database: SimpleNamespace,
) -> None:
    data = seeded_database
    thread_id = "tutor:delete-test:" + uuid4().hex
    async with data.factory() as session:
        session.add(TutorConversationModel(
            id=uuid4(), knowledge_base_id=data.kb, scope_key="library", graph_thread_id=thread_id,
        ))
        await session.commit()
    async with data.factory() as session:
        uow = SqlAlchemyUnitOfWork(session)
        await KnowledgeBaseService().delete(uow, data.kb)
        assert await uow.knowledge_bases.get(data.kb) is None
        items, total = await uow.questions.list(
            knowledge_base_id=data.kb, material_id=None, question_type=None, status=None,
            page=1, page_size=100,
        )
        assert total == 0 and items == []
        with pytest.raises(DomainError):
            await StudyService().create_session(
                uow, knowledge_base_id=data.kb,
                mode="practice", question_count=1, question_types=["true_false"],
                difficulty_min=1, difficulty_max=5,
            )
    with pytest.raises(DomainError):
        await LearningQueries(data.factory).check_scope(data.kb)
    async with data.factory() as session:
        assert (await session.get(KnowledgeBaseModel, data.kb)).status == "deleted"
        assert await session.get(MaterialModel, data.material) is not None
        assert len((await session.scalars(select(QuestionModel).where(
            QuestionModel.knowledge_base_id == data.kb))).all()) == 6
        assert await session.scalar(select(TutorConversationModel.id).where(
            TutorConversationModel.graph_thread_id == thread_id)) is not None
        # Remove only this test's tutor reference before the owning fixture's cleanup.
        from sqlalchemy import delete
        await session.execute(delete(TutorConversationModel).where(
            TutorConversationModel.graph_thread_id == thread_id))
        await session.commit()
