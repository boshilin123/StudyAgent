"""Real transactions; only explicitly named test databases may be used."""

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from celery.exceptions import Retry
from sqlalchemy import delete, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from study_agent.application.materials import MaterialService
from study_agent.application.questions import QuestionService
from study_agent.application.study import StudyService
from study_agent.config import Settings
from study_agent.domain.errors import DomainError
from study_agent.infrastructure.models import (
    AnswerRecordModel,
    DocumentChunkModel,
    IngestionJobModel,
    KnowledgeBaseModel,
    KnowledgePointModel,
    MasteryRecordModel,
    MaterialModel,
    QuestionModel,
    QuestionSourceModel,
    ReviewTaskModel,
    StudySessionModel,
)
from study_agent.infrastructure.unit_of_work import SqlAlchemyUnitOfWork
from tests.fakes import (
    FakeDocumentIndex,
    FakeIngestionDispatcher,
    FakeObjectStorage,
    FakeQuestionIndex,
)
from tests.test_reliability import DownQueue

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def seeded_database() -> AsyncIterator[SimpleNamespace]:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL required for PostgreSQL tests")
    assert (make_url(url).database or "").startswith("study_agent_test"), "refuse non-test database"
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    kb, material, chunk = uuid4(), uuid4(), uuid4()
    points = [uuid4() for _ in range(3)]
    questions = [uuid4() for _ in range(6)]
    async with factory() as session:
        session.add(KnowledgeBaseModel(id=kb, name="P10测试", status="active", language="zh-CN"))
        await session.flush()
        session.add(
            MaterialModel(
                id=material,
                knowledge_base_id=kb,
                title="测试资料",
                original_filename="test.md",
                media_type="text/markdown",
                storage_uri="fake://test.md",
                sha256=str(uuid4()).replace("-", "") * 2,
                size_bytes=10,
                language="zh-CN",
                parse_status="ready",
            )
        )
        for point in points:
            session.add(
                KnowledgePointModel(
                    id=point,
                    knowledge_base_id=kb,
                    name="测试知识点",
                    canonical_key=str(point),
                    difficulty=2,
                    source="agent",
                    status="active",
                )
            )
        await session.flush()
        session.add(
            DocumentChunkModel(
                id=chunk,
                material_id=material,
                chunk_index=0,
                content="TCP测试来源",
                token_count=3,
                content_hash="a" * 64,
                heading_path=[],
            )
        )
        await session.flush()
        for index, question in enumerate(questions):
            session.add(
                QuestionModel(
                    id=question,
                    knowledge_base_id=kb,
                    knowledge_point_id=points[index % 3],
                    question_type="true_false",
                    stem=f"测试题{index}",
                    correct_answer=["正确"],
                    scoring_points=[],
                    explanation="测试解释",
                    difficulty=2,
                    max_score=10,
                    status="active",
                    content_hash=str(question),
                    vector_id=str(question),
                )
            )
        await session.flush()
        for question in questions:
            session.add(
                QuestionSourceModel(
                    question_id=question, chunk_id=chunk, quote="TCP测试来源", rank=1
                )
            )
        await session.commit()
    try:
        yield SimpleNamespace(
            engine=engine,
            factory=factory,
            kb=kb,
            material=material,
            chunk=chunk,
            points=points,
            questions=questions,
            url=url,
        )
    finally:
        async with factory() as session:
            await session.execute(
                delete(StudySessionModel).where(StudySessionModel.knowledge_base_id == kb)
            )
            await session.execute(delete(KnowledgeBaseModel).where(KnowledgeBaseModel.id == kb))
            await session.commit()
        await engine.dispose()


async def create_session(data: SimpleNamespace, mode: str = "mock_exam", count: int = 1):
    async with data.factory() as session:
        return await StudyService().create_session(
            SqlAlchemyUnitOfWork(session),
            knowledge_base_id=data.kb,
            mode=mode,
            question_count=count,
            question_types=["true_false"],
            difficulty_min=1,
            difficulty_max=5,
        )


async def submit(
    data: SimpleNamespace,
    session_id: UUID,
    question_id: UUID,
    submission: UUID,
    answer: object = True,
):
    async with data.factory() as session:
        return await StudyService().submit_answer(
            SqlAlchemyUnitOfWork(session),
            session_id=session_id,
            submission_id=submission,
            question_id=question_id,
            answer=answer,
            elapsed_seconds=1,
        )


@pytest.mark.asyncio
async def test_concurrent_duplicate_is_one_answer_with_replay(
    seeded_database: SimpleNamespace,
) -> None:
    data = seeded_database
    view = await create_session(data)
    submission = uuid4()
    results = await asyncio.gather(
        *[submit(data, view.session.id, view.current_question.id, submission) for _ in range(8)]
    )
    assert sum(not result.idempotent_replay for result in results) == 1
    assert len({result.answer_record.id for result in results}) == 1
    async with data.factory() as session:
        records = list(
            (
                await session.scalars(
                    select(AnswerRecordModel).where(AnswerRecordModel.session_id == view.session.id)
                )
            ).all()
        )
        assert len(records) == 1
        mastery = await session.get(MasteryRecordModel, view.current_question.knowledge_point_id)
        assert mastery.answered_count == 1
    with pytest.raises(DomainError, match="不同请求"):
        await submit(data, view.session.id, view.current_question.id, submission, False)


@pytest.mark.asyncio
async def test_concurrent_sessions_do_not_lose_mastery_updates(
    seeded_database: SimpleNamespace,
) -> None:
    data = seeded_database
    views = [await create_session(data) for _ in range(8)]
    assert len({view.current_question.knowledge_point_id for view in views}) == 1
    results = await asyncio.gather(
        *[submit(data, view.session.id, view.current_question.id, uuid4()) for view in views]
    )
    assert all(result.session.answered_question_count == 1 for result in results)
    async with data.factory() as session:
        mastery = await session.get(
            MasteryRecordModel, views[0].current_question.knowledge_point_id
        )
        assert mastery.answered_count == mastery.correct_count == 8
        review = await session.scalar(
            select(ReviewTaskModel).where(
                ReviewTaskModel.knowledge_point_id == mastery.knowledge_point_id
            )
        )
        assert review.repetitions == 8


@pytest.mark.parametrize("mode", ["practice", "diagnostic", "review", "mock_exam"])
@pytest.mark.asyncio
async def test_every_mode_finishes_and_restores(
    seeded_database: SimpleNamespace, mode: str
) -> None:
    data = seeded_database
    if mode == "review":
        async with data.factory() as session:
            for point in data.points:
                session.add(
                    ReviewTaskModel(
                        id=uuid4(),
                        knowledge_point_id=point,
                        knowledge_base_id=data.kb,
                        due_at=datetime.now(UTC) - timedelta(days=1),
                        interval_days=1,
                        repetitions=0,
                        ease_factor=2.5,
                        last_quality=2,
                        status="pending",
                        updated_at=datetime.now(UTC),
                    )
                )
            await session.commit()
    view = await create_session(data, mode, 3)
    points = set()
    while view.current_question:
        points.add(view.current_question.knowledge_point_id)
        result = await submit(data, view.session.id, view.current_question.id, uuid4())
        async with data.factory() as session:
            view = await StudyService().get_session(SqlAlchemyUnitOfWork(session), view.session.id)
        assert view.session.answered_question_count == result.session.answered_question_count
    assert view.session.status == "completed"
    assert view.session.answered_question_count == 3
    if mode == "diagnostic":
        assert len(points) == 3


@pytest.mark.asyncio
async def test_delete_keeps_history_but_disables_orphans(seeded_database: SimpleNamespace) -> None:
    data = seeded_database
    view = await create_session(data)
    await submit(data, view.session.id, view.current_question.id, uuid4())
    async with data.factory() as session:
        await MaterialService().delete(
            SqlAlchemyUnitOfWork(session),
            FakeObjectStorage(),
            FakeDocumentIndex(),
            data.material,
            FakeQuestionIndex(),
        )
    async with data.factory() as session:
        questions = list(
            (
                await session.scalars(
                    select(QuestionModel).where(QuestionModel.knowledge_base_id == data.kb)
                )
            ).all()
        )
        assert all(
            question.status == "disabled" and question.vector_id is None for question in questions
        )
        assert await session.get(MaterialModel, data.material) is None
        assert (
            await session.scalar(
                select(AnswerRecordModel).where(AnswerRecordModel.session_id == view.session.id)
            )
            is not None
        )
        with pytest.raises(DomainError, match="已启用题目"):
            await StudyService().create_session(
                SqlAlchemyUnitOfWork(session),
                knowledge_base_id=data.kb,
                mode="practice",
                question_count=3,
                question_types=["true_false"],
                difficulty_min=1,
                difficulty_max=5,
            )


@pytest.mark.asyncio
async def test_candidate_beyond_500_can_be_selected(seeded_database: SimpleNamespace) -> None:
    data = seeded_database
    best = uuid4()
    async with data.factory() as session:
        for point in data.points:
            session.add(
                MasteryRecordModel(
                    knowledge_point_id=point,
                    knowledge_base_id=data.kb,
                    mastery_score=1,
                    answered_count=10,
                    correct_count=10,
                    recent_accuracy=1,
                    confidence=1,
                    updated_at=datetime.now(UTC),
                )
            )
        ids = [uuid4() for _ in range(501)] + [best]
        for question in ids:
            session.add(
                QuestionModel(
                    id=question,
                    knowledge_base_id=data.kb,
                    knowledge_point_id=data.points[0],
                    question_type="true_false",
                    stem=str(question),
                    correct_answer=["正确"],
                    scoring_points=[],
                    explanation="测试解释",
                    difficulty=5 if question == best else 1,
                    max_score=10,
                    status="active",
                    content_hash=str(question),
                )
            )
        await session.flush()
        for question in ids:
            session.add(
                QuestionSourceModel(
                    question_id=question, chunk_id=data.chunk, quote="TCP测试来源", rank=1
                )
            )
        await session.commit()
    view = await create_session(data, "practice", 1)
    assert view.current_question.id == best


@pytest.mark.asyncio
async def test_rechunk_cleans_sources_and_retryable_stale_vectors(
    seeded_database: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from study_agent.ingestion import tasks

    data = seeded_database
    storage = FakeObjectStorage()
    storage.objects["test.md"] = ("# TCP\n" + "测试重新切块与来源失效。" * 40).encode()
    question_index = FakeQuestionIndex()

    class IndexStub:
        embedding_model = "test"

        def __init__(self):
            self.ids = {data.chunk}
            self.fail_once = True

        async def upsert(self, *, knowledge_base_id, chunks):
            self.ids.update(chunk.id for chunk in chunks)
            return [str(chunk.id) for chunk in chunks]

        async def delete_stale_chunks(self, material_id, keep_ids):
            if self.fail_once:
                self.fail_once = False
                raise ConnectionError("simulated index cleanup outage")
            self.ids.intersection_update(keep_ids)

    index = IndexStub()
    monkeypatch.setattr(
        tasks,
        "get_settings",
        lambda: Settings(_env_file=None, database_url=data.url, chunk_size=80, chunk_overlap=10),
    )
    monkeypatch.setattr(tasks, "get_storage", lambda: storage)
    monkeypatch.setattr(tasks, "get_document_index", lambda: index)
    monkeypatch.setattr(tasks, "get_question_index", lambda: question_index)
    job_id = uuid4()
    async with data.factory() as session:
        session.add(
            IngestionJobModel(
                id=job_id,
                material_id=data.material,
                status="pending",
                stage="uploaded",
                progress=0,
                generation_config={},
            )
        )
        await session.commit()
    payload = await asyncio.to_thread(tasks.parse_material.run, str(job_id), str(data.material))
    with pytest.raises((ConnectionError, Retry)):
        await asyncio.to_thread(tasks.index_material.run, payload)
    await asyncio.to_thread(tasks.index_material.run, payload)
    await asyncio.to_thread(tasks.finish_ingestion.run, payload)
    async with data.factory() as session:
        chunk_ids = set(
            (
                await session.scalars(
                    select(DocumentChunkModel.id).where(
                        DocumentChunkModel.material_id == data.material
                    )
                )
            ).all()
        )
        assert chunk_ids == index.ids
        assert data.chunk not in chunk_ids
        assert set(question_index.deleted) == set(data.questions)
        questions = list(
            (
                await session.scalars(
                    select(QuestionModel).where(QuestionModel.knowledge_base_id == data.kb)
                )
            ).all()
        )
        assert all(question.status == "disabled" for question in questions)
        assert (await session.get(MaterialModel, data.material)).parse_status == "ready"


@pytest.mark.asyncio
async def test_generation_retry_deduplicates_and_completed_redelivery_is_noop(
    seeded_database: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from study_agent.infrastructure.models import QuestionGenerationJobModel, WorkflowRunModel
    from study_agent.question_generation import tasks
    from study_agent.question_generation.schemas import (
        GeneratedQuestionDraft,
        KnowledgePointBatch,
        KnowledgePointDraft,
        QuestionBatch,
    )

    data = seeded_database
    point = KnowledgePointDraft(
        canonical_key="p10-tcp",
        name="TCP测试来源",
        description="用于验证任务重试的测试知识点",
        importance=0.5,
        difficulty=2,
        source_chunk_ids=[data.chunk],
    )
    question = GeneratedQuestionDraft(
        knowledge_point_key=point.canonical_key,
        question_type="true_false",
        stem="资料中包含TCP测试来源。",
        correct_answers=["正确"],
        explanation="资料确实包含该测试来源。",
        difficulty=2,
        source_chunk_ids=[data.chunk],
        source_quotes=["TCP测试来源"],
    )
    point_chain = SimpleNamespace(invoke=lambda _: KnowledgePointBatch(items=[point]))
    question_chain = SimpleNamespace(invoke=lambda _: QuestionBatch(items=[question]))

    class IndexStub:
        fail_once = True

        async def upsert(self, records):
            if self.fail_once:
                self.fail_once = False
                raise ConnectionError("simulated question vector outage")
            return [record["id"] for record in records]

    index = IndexStub()
    monkeypatch.setattr(
        tasks,
        "get_settings",
        lambda: Settings(
            _env_file=None, database_url=data.url, llm_model="mock", llm_base_url="http://mock/v1"
        ),
    )
    monkeypatch.setattr(tasks, "create_knowledge_point_chain", lambda _: point_chain)
    monkeypatch.setattr(tasks, "create_question_generation_chain", lambda _: question_chain)
    monkeypatch.setattr(tasks, "get_question_index", lambda: index)
    job_id = uuid4()
    async with data.factory() as session:
        session.add(
            QuestionGenerationJobModel(
                id=job_id,
                material_id=data.material,
                status="pending",
                stage="queued",
                progress=0,
                target_question_count=1,
                allowed_types=["true_false"],
                difficulty_min=1,
                difficulty_max=5,
                language="zh-CN",
                generated_count=0,
                rejected_count=0,
            )
        )
        await session.commit()
    with pytest.raises((ConnectionError, Retry)):
        await asyncio.to_thread(tasks.generate_questions.run, str(job_id), str(data.material))
    result = await asyncio.to_thread(tasks.generate_questions.run, str(job_id), str(data.material))
    assert result["generated_count"] == 1
    # A repeated completed delivery must not invoke either model chain again.
    monkeypatch.setattr(
        tasks, "create_question_generation_chain", lambda _: pytest.fail("repeated LLM call")
    )
    assert (
        await asyncio.to_thread(tasks.generate_questions.run, str(job_id), str(data.material))
        == result
    )
    async with data.factory() as session:
        questions = list(
            (
                await session.scalars(
                    select(QuestionModel).where(QuestionModel.knowledge_base_id == data.kb)
                )
            ).all()
        )
        assert len(questions) == 7
        runs = list(
            (
                await session.scalars(
                    select(WorkflowRunModel).where(WorkflowRunModel.subject_id == data.material)
                )
            ).all()
        )
        assert sorted(run.status for run in runs) == ["completed", "failed"]


@pytest.mark.asyncio
async def test_real_dispatch_compensation_allows_retry(
    seeded_database: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = seeded_database
    monkeypatch.setattr(
        "study_agent.application.questions.get_settings",
        lambda: Settings(_env_file=None, llm_base_url="http://mock/v1", llm_model="mock"),
    )
    kwargs = dict(
        material_id=data.material,
        target_question_count=1,
        allowed_types=["true_false"],
        difficulty_min=1,
        difficulty_max=5,
        language="zh-CN",
    )
    async with data.factory() as session:
        with pytest.raises(DomainError, match="提交失败"):
            await QuestionService().create_generation_job(
                SqlAlchemyUnitOfWork(session), DownQueue(), **kwargs
            )
    async with data.factory() as session:
        result = await QuestionService().create_generation_job(
            SqlAlchemyUnitOfWork(session), FakeIngestionDispatcher(), **kwargs
        )
        assert result.status == "pending"


@pytest.mark.asyncio
async def test_delete_serializes_with_question_activation(seeded_database: SimpleNamespace) -> None:
    data = seeded_database
    entered, release = asyncio.Event(), asyncio.Event()

    class BlockingIndex(FakeDocumentIndex):
        async def delete_material(self, material_id: UUID) -> None:
            entered.set()
            await release.wait()

    async def delete_material() -> None:
        async with data.factory() as session:
            await MaterialService().delete(
                SqlAlchemyUnitOfWork(session),
                FakeObjectStorage(),
                BlockingIndex(),
                data.material,
                FakeQuestionIndex(),
            )

    async def activate() -> None:
        async with data.factory() as session:
            await QuestionService().set_status(
                SqlAlchemyUnitOfWork(session), FakeQuestionIndex(), data.questions[0], "active"
            )

    deletion = asyncio.create_task(delete_material())
    await asyncio.wait_for(entered.wait(), timeout=5)
    activation = asyncio.create_task(activate())
    release.set()
    await deletion
    with pytest.raises(DomainError, match="无真实来源"):
        await activation


@pytest.mark.asyncio
async def test_missing_checkpoint_rebuilds_and_explanation_failure_does_not_undo_grade(
    seeded_database: SimpleNamespace,
) -> None:
    data = seeded_database

    class Store:
        def __init__(self):
            self.state = {}

        async def get(self, key):
            return self.state.get(key)

        async def save(self, key, state):
            self.state[key] = state

    class BrokenExplanation:
        async def explain(self, **kwargs):
            raise ConnectionError("simulated LLM outage")

    view = await create_session(data, "practice", 3)
    store = Store()
    async with data.factory() as session:
        result = await StudyService().submit_answer(
            SqlAlchemyUnitOfWork(session),
            session_id=view.session.id,
            submission_id=uuid4(),
            question_id=view.current_question.id,
            answer=False,
            elapsed_seconds=1,
            explanation_generator=BrokenExplanation(),
            state_store=store,
        )
    assert result.answer_record.verdict == "incorrect"
    expected = store.state.pop(view.session.id)
    async with data.factory() as session:
        restored = await StudyService().get_session(
            SqlAlchemyUnitOfWork(session), view.session.id, store
        )
    assert restored.session.answered_question_count == 1
    assert store.state[view.session.id]["current_question_id"] == expected["current_question_id"]
