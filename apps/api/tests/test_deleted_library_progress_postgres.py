"""Deleted libraries are hidden from progress; archived learning facts remain visible."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

from study_agent.api.routes.study import list_due_reviews, list_mastery
from study_agent.application.knowledge_bases import KnowledgeBaseService
from study_agent.infrastructure.models import (
    AnswerRecordModel,
    KnowledgePointModel,
    MasteryRecordModel,
    ReviewTaskModel,
    StudySessionModel,
)
from study_agent.infrastructure.unit_of_work import SqlAlchemyUnitOfWork
from tests.test_postgres_reliability import (
    create_session,
    submit,
)
from tests.test_postgres_reliability import (
    seeded_database as seeded_database,
)

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["active", "archived", "deleted"])
async def test_progress_visibility_tracks_library_status_without_erasing_facts(
    seeded_database: SimpleNamespace, status: str
) -> None:
    data = seeded_database
    view = await create_session(data)
    assert view.current_question is not None
    answer = await submit(data, view.session.id, view.current_question.id, uuid4(), False)
    deadline = datetime.now(UTC) + timedelta(days=30)

    async with data.factory() as session:
        uow = SqlAlchemyUnitOfWork(session)
        _, before_total = await uow.study_sessions.list(
            knowledge_base_id=None, page=1, page_size=1000
        )
        service = KnowledgeBaseService()
        if status == "deleted":
            await service.delete(uow, data.kb)
            await service.delete(uow, data.kb)
        elif status == "archived":
            await service.update(uow, data.kb, status=status)

    visible = status != "deleted"
    async with data.factory() as session:
        uow = SqlAlchemyUnitOfWork(session)
        for scope in (None, data.kb):
            mastery = await uow.mastery.list(scope)
            reviews = await uow.review_tasks.list_due(
                knowledge_base_id=scope, due_before=deadline
            )
            history, total = await uow.study_sessions.list(
                knowledge_base_id=scope, page=1, page_size=1000
            )
            assert any(item.knowledge_base_id == data.kb for item in mastery) is visible
            assert any(item.knowledge_base_id == data.kb for item in reviews) is visible
            assert any(item.id == view.session.id for item in history) is visible
            assert total == (int(visible) if scope else before_total - int(not visible))
            if visible:
                assert all(
                    item.knowledge_point_name == "测试知识点"
                    for item in mastery if item.knowledge_base_id == data.kb
                )
                assert all(
                    item.knowledge_point_name == "测试知识点"
                    for item in reviews if item.knowledge_base_id == data.kb
                )

        # Visibility filtering must not destroy the original learning facts.
        assert await session.get(StudySessionModel, view.session.id) is not None
        assert await session.get(AnswerRecordModel, answer.answer_record.id) is not None
        assert await session.get(MasteryRecordModel, answer.mastery.knowledge_point_id) is not None
        assert await session.scalar(
            select(ReviewTaskModel.id).where(ReviewTaskModel.id == answer.review_task.id)
        ) is not None


@pytest.mark.asyncio
async def test_progress_responses_use_current_point_names_for_existing_records(
    seeded_database: SimpleNamespace,
) -> None:
    data = seeded_database
    view = await create_session(data)
    assert view.current_question is not None
    result = await submit(data, view.session.id, view.current_question.id, uuid4(), False)
    async with data.factory() as session:
        point = await session.get(KnowledgePointModel, result.mastery.knowledge_point_id)
        assert point is not None
        point.name = "LCEL 固定链与 Agent 工具调用的区别"
        await session.commit()

    async with data.factory() as session:
        uow = SqlAlchemyUnitOfWork(session)
        mastery = await list_mastery(uow, data.kb)
        reviews = await list_due_reviews(uow, data.kb, datetime.now(UTC) + timedelta(days=30))
        assert len(mastery) == len(reviews) == 1
        assert mastery[0].knowledge_point_name == point.name
        assert reviews[0].knowledge_point_name == point.name
        assert mastery[0].knowledge_point_id == result.mastery.knowledge_point_id
        assert mastery[0].answered_count == 1
