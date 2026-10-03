"""Deletion removes availability while preserving real learning facts and replays."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

from study_agent.application.learning_queries import LearningQueries
from study_agent.application.questions import QuestionService
from study_agent.domain.errors import DomainError
from study_agent.infrastructure.models import AnswerRecordModel, QuestionSourceModel
from study_agent.infrastructure.unit_of_work import SqlAlchemyUnitOfWork
from tests.fakes import FakeQuestionIndex
from tests.test_postgres_reliability import create_session, submit
from tests.test_postgres_reliability import seeded_database as seeded_database

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_delete_answered_question_preserves_replay_and_counts(
    seeded_database: SimpleNamespace,
) -> None:
    data = seeded_database
    view = await create_session(data)
    qid = view.current_question.id
    submission = uuid4()
    answered = await submit(data, view.session.id, qid, submission)
    async with data.factory() as session:
        uow = SqlAlchemyUnitOfWork(session)
        index = FakeQuestionIndex()
        await QuestionService().delete(uow, index, qid)
        assert index.deleted == [qid]
        assert (await uow.questions.get(qid)).status == "deleted"
        assert (await uow.knowledge_bases.get(data.kb)).question_count == 5
        items, total = await uow.questions.list(
            knowledge_base_id=data.kb,
            material_id=data.material,
            question_type=None,
            status=None,
            page=1,
            page_size=100,
        )
        assert total == 5 and qid not in {item.id for item in items}
        candidates = await uow.questions.list_active_candidates(
            knowledge_base_id=data.kb,
            question_types=["true_false"],
            difficulty_min=1,
            difficulty_max=5,
            limit=None,
        )
        assert qid not in {item.id for item in candidates}
        assert (
            await session.scalar(
                select(AnswerRecordModel.id).where(AnswerRecordModel.question_id == qid)
            )
            == answered.answer_record.id
        )
        assert (
            await session.scalar(
                select(QuestionSourceModel.question_id).where(
                    QuestionSourceModel.question_id == qid
                )
            )
            == qid
        )
        with pytest.raises(DomainError):
            await QuestionService().get(uow, qid)
    replay = await submit(data, view.session.id, qid, submission)
    assert replay.idempotent_replay and replay.answer_record.id == answered.answer_record.id
    context = await LearningQueries(data.factory).answered_question(data.kb, view.session.id, qid)
    assert context["stem"] == view.current_question.stem and context["code"] == "OK"


@pytest.mark.asyncio
async def test_delete_current_question_prevents_answer(
    seeded_database: SimpleNamespace,
) -> None:
    data = seeded_database
    view = await create_session(data)
    qid = view.current_question.id
    async with data.factory() as session:
        await QuestionService().delete(SqlAlchemyUnitOfWork(session), FakeQuestionIndex(), qid)
    with pytest.raises(DomainError) as failure:
        await submit(data, view.session.id, qid, uuid4())
    assert failure.value.code == "QUESTION_UNAVAILABLE"
    async with data.factory() as session:
        assert (
            await session.scalar(
                select(AnswerRecordModel.id).where(AnswerRecordModel.question_id == qid)
            )
            is None
        )
