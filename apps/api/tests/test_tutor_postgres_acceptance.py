"""Real PostgreSQL + saver + create_agent + ASGI; vector candidates are explicit fixtures."""

import asyncio
import sys
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Overwrite
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import create_async_engine

from study_agent.agents.tutor.context import TutorContext
from study_agent.agents.tutor.middleware import RunBudget
from study_agent.api.tutoring_dependencies import get_tutor_service
from study_agent.api.tutoring_schemas import CreateTutorConversation, SubmitTutorMessage
from study_agent.application.learning_queries import LearningQueries
from study_agent.application.retrieval import LearningMaterialRetrieval
from study_agent.application.tutoring import TutorService, request_digest
from study_agent.config import Settings
from study_agent.domain.errors import DomainError
from study_agent.infrastructure.checkpointer import psycopg_connection_string
from study_agent.infrastructure.models import (
    AnswerRecordModel,
    DocumentChunkModel,
    KnowledgeBaseModel,
    MasteryRecordModel,
    MaterialModel,
    QuestionModel,
    ReviewTaskModel,
)
from study_agent.infrastructure.tutoring import TutorRepository
from study_agent.infrastructure.tutoring_models import (
    TutorConversationModel,
    TutorMessageModel,
    TutorTurnModel,
)
from study_agent.main import create_app
from study_agent.main import settings as app_settings
from tests.test_postgres_reliability import (
    create_session,
    submit,
)
from tests.test_postgres_reliability import (
    seeded_database as seeded_database,
)
from tests.test_tutor_acceptance import SequenceModel, call, final

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def event_loop_policy():
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()


class CandidateIndex:
    def __init__(self, data):
        self.hits = [SimpleNamespace(chunk_id=data.chunk, material_id=data.material)]
        self.calls = []

    async def search(self, *, knowledge_base_id, query, limit):
        self.calls.append((knowledge_base_id, query, limit))
        return self.hits[:limit]


@pytest_asyncio.fixture
async def tutor_database(seeded_database):
    data = seeded_database
    data.index = CandidateIndex(data)
    data.retrieval = LearningMaterialRetrieval(data.factory, data.index)
    data.queries = LearningQueries(data.factory)
    data.repository = TutorRepository(data.factory, data.engine)
    data.settings = Settings(_env_file=None, tutor_enabled=True, tutor_timeout_seconds=15)
    data.citation_id = f"chunk:{data.chunk}:{'a' * 64}"
    try:
        yield data
    finally:
        async with data.factory() as session:
            await session.execute(
                delete(TutorConversationModel).where(
                    TutorConversationModel.knowledge_base_id == data.kb
                )
            )
            await session.commit()


def model_for(data, *, fabricated=False):
    return SequenceModel(
        responses=[
            call("search_learning_materials", {"query": "TCP", "top_k": 1}),
            final(citations=["forged" if fabricated else data.citation_id]),
        ]
    )


def service_for(data, saver, model):
    return TutorService(
        data.repository, data.queries, data.retrieval, data.settings, saver, lambda: model
    )


def payload(text="解释TCP", intent="materials", message_id=None):
    return SubmitTutorMessage(client_message_id=message_id or uuid4(), content=text, intent=intent)


async def test_r01_r02_r07_http_vertical_persistent_restart_and_archive(tutor_database):
    data = tutor_database
    first_model = model_for(data)
    async with AsyncPostgresSaver.from_conn_string(psycopg_connection_string(data.url)) as saver:
        service = service_for(data, saver, first_model)
        app = create_app()
        app.dependency_overrides[get_tutor_service] = lambda: service
        headers = (
            {"Authorization": "Bearer " + app_settings.api_access_token}
            if app_settings.api_access_token
            else {}
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://acceptance", headers=headers
        ) as client:
            created = await client.post(
                "/api/tutor/conversations", json={"knowledge_base_id": str(data.kb)}
            )
            assert created.status_code == 201, created.text
            conversation_id = created.json()["id"]
            request = payload()
            endpoint = f"/api/tutor/conversations/{conversation_id}"
            answer = await client.post(endpoint + "/messages", json=request.model_dump(mode="json"))
            assert answer.status_code == 200, answer.text
            assert answer.json()["status"] == "completed"
            assert answer.json()["citations"][0]["quote"] == "TCP测试来源"
            duplicate = await client.post(
                endpoint + "/messages", json=request.model_dump(mode="json")
            )
            assert duplicate.json()["idempotent_replay"] is True
            assert duplicate.json()["turn_id"] == answer.json()["turn_id"]
            assert len(first_model.calls) == 2
            detail = await client.get(endpoint)
            assert [item["role"] for item in detail.json()["messages"]] == ["user", "assistant"]
            assert detail.json()["messages"][1]["citations"][0]["valid"] is True
    # Close the PostgreSQL saver connection and rebuild model/service/app completely.
    second_model = model_for(data)
    async with AsyncPostgresSaver.from_conn_string(psycopg_connection_string(data.url)) as saver:
        service = service_for(data, saver, second_model)
        app = create_app()
        app.dependency_overrides[get_tutor_service] = lambda: service
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://acceptance", headers=headers
        ) as client:
            followup = await client.post(
                endpoint + "/messages", json=payload("再解释第二个").model_dump(mode="json")
            )
            assert followup.json()["status"] == "completed", followup.text
            input_contents = [message.content for message in second_model.calls[0]]
            assert request.content in input_contents and "这是解释性回答。" in input_contents
            detail = await client.get(endpoint)
            assert detail.json()["total"] == 4
            archived = await client.post(endpoint + "/archive")
            assert archived.json()["status"] == "archived"
            assert (await client.post(endpoint + "/archive")).json()["status"] == "archived"
            rejected = await client.post(
                endpoint + "/messages", json=payload("归档后").model_dump(mode="json")
            )
            assert rejected.status_code == 409
            assert rejected.json()["error"]["code"] == "TUTOR_CONVERSATION_ARCHIVED"


async def test_r03_eight_concurrent_same_id_one_graph_execution(tutor_database):
    data = tutor_database
    model = model_for(data)
    async with AsyncPostgresSaver.from_conn_string(psycopg_connection_string(data.url)) as saver:
        service = service_for(data, saver, model)
        conversation = await service.create(CreateTutorConversation(knowledge_base_id=data.kb))
        request = payload()
        results = await asyncio.gather(
            *[service.submit(conversation.id, request) for _ in range(8)]
        )
        assert len(model.calls) == 2
        assert len({item["turn_id"] for item in results}) == 1
        assert sum(not item["idempotent_replay"] for item in results) == 1
        async with data.factory() as session:
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(TutorTurnModel)
                    .where(TutorTurnModel.conversation_id == conversation.id)
                )
                == 1
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(TutorMessageModel)
                    .where(TutorMessageModel.conversation_id == conversation.id)
                )
                == 2
            )


async def test_r04_payload_conflict_and_busy_same_conversation(tutor_database):
    data = tutor_database
    model = model_for(data)
    async with AsyncPostgresSaver.from_conn_string(psycopg_connection_string(data.url)) as saver:
        service = service_for(data, saver, model)
        conversation = await service.create(CreateTutorConversation(knowledge_base_id=data.kb))
        request = payload()
        await service.submit(conversation.id, request)
        for changed in [
            payload("另一文本", message_id=request.client_message_id),
            payload(request.content, "general", request.client_message_id),
        ]:
            with pytest.raises(DomainError) as caught:
                await service.submit(conversation.id, changed)
            assert caught.value.code == "TUTOR_MESSAGE_CONFLICT"
        async with data.repository.execution_lock(conversation.id) as acquired:
            assert acquired
            with pytest.raises(DomainError) as caught:
                await service.submit(conversation.id, payload("第二问题"))
            assert caught.value.code == "TUTOR_THREAD_BUSY"
            with pytest.raises(DomainError) as caught:
                await service.archive(conversation.id)
            assert caught.value.code == "TUTOR_THREAD_BUSY"


@pytest.mark.parametrize("window", ["during_model", "after_tool", "final_checkpoint"])
async def test_r06_orphan_fault_windows_recover_without_provider_repeat(tutor_database, window):
    data = tutor_database
    model = model_for(data)
    async with AsyncPostgresSaver.from_conn_string(psycopg_connection_string(data.url)) as saver:
        service = service_for(data, saver, model)
        conversation = await service.create(CreateTutorConversation(knowledge_base_id=data.kb))
        request = payload("中断问题")
        turn = await data.repository.reserve(
            conversation.id,
            request.client_message_id,
            request.content,
            request.intent,
            request_digest(request.content, request.intent),
            15,
            "scripted",
        )
        graph = service.new_agent(RunBudget(time.monotonic() + 10))
        config = {
            "configurable": {
                "thread_id": conversation.graph_thread_id,
                "checkpoint_id": conversation.last_committed_checkpoint_id,
            }
        }
        if window == "after_tool":
            await graph.aupdate_state(
                config,
                {
                    "messages": [
                        HumanMessage(content="unaccepted secret"),
                        AIMessage(
                            content="",
                            tool_calls=[
                                {
                                    "name": "get_learning_progress",
                                    "args": {},
                                    "id": "interrupted",
                                    "type": "tool_call",
                                }
                            ],
                        ),
                    ],
                    "turn_id": str(turn.id),
                },
                as_node="model",
            )
        elif window == "final_checkpoint":
            await graph.ainvoke(
                {
                    "messages": Overwrite([HumanMessage(content=request.content)]),
                    "evidence": Overwrite({}),
                    "evidence_flags": Overwrite([]),
                    "turn_id": str(turn.id),
                },
                config,
                context=TutorContext(conversation.id, turn.id, data.kb),
            )
        calls_before_recovery = len(model.calls)
    # Simulated process loss at persisted fault boundary: no application complete/fail was called.
    restarted_model = model_for(data)
    async with AsyncPostgresSaver.from_conn_string(psycopg_connection_string(data.url)) as saver:
        service = service_for(data, saver, restarted_model)
        recovered = await service.turn_status(conversation.id, turn.id)
        assert len(restarted_model.calls) == 0
        if window == "final_checkpoint":
            assert recovered["status"] == "completed"
            assert recovered["response"]["usage"]["recovered"] is True
            assert calls_before_recovery == 2
        else:
            assert recovered["status"] == "failed"
            assert recovered["error_code"] == "TUTOR_INTERRUPTED"
            assert await data.repository.committed_history(conversation.id, 20) == []
        next_result = await service.submit(conversation.id, payload("显式新问题"))
        assert next_result["status"] == "completed"
        assert "unaccepted secret" not in [m.content for m in restarted_model.calls[0]]


async def test_r08_failed_draft_not_in_future_history(tutor_database):
    data = tutor_database
    bad_model = model_for(data, fabricated=True)
    async with AsyncPostgresSaver.from_conn_string(psycopg_connection_string(data.url)) as saver:
        service = service_for(data, saver, bad_model)
        conversation = await service.create(CreateTutorConversation(knowledge_base_id=data.kb))
        failed = await service.submit(conversation.id, payload("failed-user-secret"))
        assert failed["status"] == "failed" and failed["error_code"] == "TUTOR_INVALID_CITATION"
        assert await data.repository.committed_history(conversation.id, 20) == []
        good_model = model_for(data)
        result = await service_for(data, saver, good_model).submit(
            conversation.id, payload("new-turn")
        )
        assert result["status"] == "completed"
        assert "failed-user-secret" not in [m.content for m in good_model.calls[0]]


async def test_t05_r10_material_changes_invalidate_current_and_historical_evidence(tutor_database):
    data = tutor_database
    async with AsyncPostgresSaver.from_conn_string(psycopg_connection_string(data.url)) as saver:
        service = service_for(data, saver, model_for(data))
        conversation = await service.create(CreateTutorConversation(knowledge_base_id=data.kb))
        answer = await service.submit(conversation.id, payload())
        assert answer["status"] == "completed"
        async with data.factory() as session:
            await session.execute(
                update(MaterialModel)
                .where(MaterialModel.id == data.material)
                .values(parse_status="parsing")
            )
            await session.commit()
        _, messages, _ = await service.detail(conversation.id, 1, 50)
        assert messages[-1].citations[0]["valid"] is False
        assert await data.retrieval.search(data.kb, "TCP", 5) == []
        async with data.factory() as session:
            await session.execute(
                update(MaterialModel)
                .where(MaterialModel.id == data.material)
                .values(parse_status="ready")
            )
            await session.execute(
                update(DocumentChunkModel)
                .where(DocumentChunkModel.id == data.chunk)
                .values(content_hash="b" * 64)
            )
            await session.commit()
        assert not await data.retrieval.revalidate(data.kb, answer["citations"][0])


async def test_t06_t07_t08_u04_real_answer_context_zero_history_and_exam(tutor_database):
    data = tutor_database
    assert (await data.queries.progress(data.kb))["code"] == "NO_LEARNING_HISTORY"
    view = await create_session(data, mode="practice")
    with pytest.raises(DomainError) as caught:
        await data.queries.answered_question(data.kb, view.session.id, view.current_question.id)
    assert caught.value.code == "TUTOR_CONTEXT_UNAVAILABLE"
    result = await submit(data, view.session.id, view.current_question.id, uuid4(), answer=False)
    context = await data.queries.answered_question(
        data.kb, view.session.id, result.answer_record.question_id
    )
    assert context["user_answer"] is False and context["verdict"] == "incorrect"
    assert len(context["evidence"]) == 1
    assert (await data.queries.progress(data.kb))["answered_count"] == 1
    assert len((await data.queries.recent_mistakes(data.kb, 5))["items"]) == 1
    with pytest.raises(DomainError):
        await data.queries.answered_question(
            uuid4(), view.session.id, result.answer_record.question_id
        )
    await create_session(data, mode="mock_exam")
    with pytest.raises(DomainError) as caught:
        await data.queries.progress(data.kb)
    assert caught.value.code == "TUTOR_EXAM_IN_PROGRESS"


async def test_r12_graph_version_rejected_and_archive_idempotent(tutor_database):
    data = tutor_database
    async with AsyncPostgresSaver.from_conn_string(psycopg_connection_string(data.url)) as saver:
        service = service_for(data, saver, model_for(data))
        conversation = await service.create(CreateTutorConversation(knowledge_base_id=data.kb))
        async with data.factory() as session:
            await session.execute(
                update(TutorConversationModel)
                .where(TutorConversationModel.id == conversation.id)
                .values(graph_version="incompatible-future")
            )
            await session.commit()
        with pytest.raises(DomainError) as caught:
            await service.submit(conversation.id, payload())
        assert caught.value.code == "TUTOR_CONTEXT_UNAVAILABLE"
        assert (await service.archive(conversation.id)).status == "archived"
        assert (await service.archive(conversation.id)).status == "archived"


async def test_r13_prior_structured_draft_cannot_complete_plain_text_next_turn(tutor_database):
    data = tutor_database
    view = await create_session(data, mode="practice")
    await submit(data, view.session.id, view.current_question.id, uuid4())
    first_model = SequenceModel(responses=[call("get_learning_progress", {}), final()])
    async with AsyncPostgresSaver.from_conn_string(psycopg_connection_string(data.url)) as saver:
        service = service_for(data, saver, first_model)
        conversation = await service.create(CreateTutorConversation(knowledge_base_id=data.kb))
        first = await service.submit(conversation.id, payload("给我复习建议", "progress"))
        assert first["status"] == "completed"
        second_model = SequenceModel(responses=[AIMessage(content="这是未结构化回复")])
        second = await service_for(data, saver, second_model).submit(
            conversation.id, payload("你好", "general")
        )
        assert second["status"] == "failed"
        history = await data.repository.committed_history(conversation.id, 20)
        assert len(history) == 2
        assert second["message"] is None


async def test_u01_http_auth_input_validation_and_safe_envelope(tutor_database, monkeypatch):
    data = tutor_database
    monkeypatch.setattr(app_settings, "api_access_token", "acceptance-token")
    async with AsyncPostgresSaver.from_conn_string(psycopg_connection_string(data.url)) as saver:
        service = service_for(data, saver, model_for(data))
        app = create_app()
        app.dependency_overrides[get_tutor_service] = lambda: service
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://acceptance"
        ) as client:
            rejected = await client.get("/api/tutor/conversations")
            assert rejected.status_code == 401
            assert rejected.json()["error"]["code"] == "UNAUTHORIZED"
            assert rejected.headers["X-Request-ID"]
            client.headers["Authorization"] = "Bearer acceptance-token"
            invalid = [
                {"knowledge_base_id": "invalid"},
                {"knowledge_base_id": str(data.kb), "thread_id": "injected"},
                {"knowledge_base_id": str(data.kb), "answered_question_id": str(uuid4())},
            ]
            for request in invalid:
                response = await client.post("/api/tutor/conversations", json=request)
                assert response.status_code == 422
                assert response.json()["error"]["code"]
            created = await client.post(
                "/api/tutor/conversations", json={"knowledge_base_id": str(data.kb)}
            )
            endpoint = f"/api/tutor/conversations/{created.json()['id']}/messages"
            for text in ["", "   ", "x" * 2001]:
                response = await client.post(
                    endpoint, json={"content": text, "client_message_id": str(uuid4())}
                )
                assert response.status_code == 422
            response = await client.get("/api/tutor/conversations?page_size=51")
            assert response.status_code == 422


async def test_t02_t04_real_database_filters_foreign_missing_and_mismatched_candidates(
    tutor_database,
):
    data = tutor_database
    other_kb, other_material, other_chunk = uuid4(), uuid4(), uuid4()
    async with data.factory() as session:
        session.add(
            KnowledgeBaseModel(id=other_kb, name="B私有库", status="active", language="zh-CN")
        )
        await session.flush()
        session.add(
            MaterialModel(
                id=other_material,
                knowledge_base_id=other_kb,
                title="B库私有",
                original_filename="b.md",
                media_type="text/markdown",
                storage_uri="fake://b.md",
                sha256=uuid4().hex * 2,
                size_bytes=10,
                language="zh-CN",
                parse_status="ready",
            )
        )
        await session.flush()
        session.add(
            DocumentChunkModel(
                id=other_chunk,
                material_id=other_material,
                chunk_index=0,
                content="B库私有资料",
                content_hash="b" * 64,
                token_count=4,
                heading_path=[],
            )
        )
        await session.commit()
    try:
        data.index.hits = [
            SimpleNamespace(chunk_id=other_chunk, material_id=other_material),
            SimpleNamespace(chunk_id=uuid4(), material_id=data.material),
            SimpleNamespace(chunk_id=data.chunk, material_id=other_material),
            SimpleNamespace(chunk_id=data.chunk, material_id=data.material),
        ]
        evidence = await data.retrieval.search(data.kb, "TCP", 5)
        assert len(evidence) == 1
        assert evidence[0]["chunk_id"] == str(data.chunk)
        assert evidence[0]["quote"] == "TCP测试来源"
        assert data.index.calls[-1] == (data.kb, "TCP", 5)
    finally:
        async with data.factory() as session:
            await session.execute(
                delete(KnowledgeBaseModel).where(KnowledgeBaseModel.id == other_kb)
            )
            await session.commit()


async def test_r05_independent_locks_and_pool_bound(tutor_database):
    data = tutor_database
    async with AsyncPostgresSaver.from_conn_string(psycopg_connection_string(data.url)) as saver:
        service = service_for(data, saver, model_for(data))
        first = await service.create(CreateTutorConversation(knowledge_base_id=data.kb))
        second = await service.create(CreateTutorConversation(knowledge_base_id=data.kb))
        async with (
            data.repository.execution_lock(first.id) as first_acquired,
            data.repository.execution_lock(second.id) as second_acquired,
        ):
            assert first_acquired and second_acquired
        lock_engine = create_async_engine(data.url, pool_size=1, max_overflow=0, pool_timeout=0.05)
        bounded = TutorRepository(data.factory, lock_engine)
        try:
            async with bounded.execution_lock(first.id) as acquired:
                assert acquired
                with pytest.raises(DomainError) as caught:
                    async with bounded.execution_lock(second.id):
                        pytest.fail("pool limit was bypassed")
                assert caught.value.code == "TUTOR_CONCURRENCY_LIMIT"
        finally:
            await lock_engine.dispose()


async def test_t09_recent_mistakes_real_repository_limit_order_and_age(tutor_database):
    data = tutor_database
    record_ids = []
    for _ in range(12):
        view = await create_session(data, mode="practice")
        result = await submit(
            data, view.session.id, view.current_question.id, uuid4(), answer=False
        )
        record_ids.append(result.answer_record.id)
    now = datetime.now(UTC)
    async with data.factory() as session:
        for offset, record_id in enumerate(record_ids):
            answered_at = (
                now - timedelta(days=31) if offset == 0 else now - timedelta(minutes=offset)
            )
            await session.execute(
                update(AnswerRecordModel)
                .where(AnswerRecordModel.id == record_id)
                .values(answered_at=answered_at)
            )
        await session.commit()
    assert (await data.queries.progress(data.kb))["answered_count"] == 12
    for limit in [1, 5, 10]:
        items = (await data.queries.recent_mistakes(data.kb, limit))["items"]
        assert len(items) == limit
        dates = [datetime.fromisoformat(item["answered_at"]) for item in items]
        assert dates == sorted(dates, reverse=True)
        assert all(date >= now - timedelta(days=30) for date in dates)
    async with data.factory() as session:
        await session.execute(
            update(AnswerRecordModel)
            .where(AnswerRecordModel.id.in_(record_ids[2:]))
            .values(answered_at=now - timedelta(days=31))
        )
        await session.commit()
    assert len((await data.queries.recent_mistakes(data.kb, 10))["items"]) == 1


async def test_r11_success_and_failure_leave_learning_facts_unchanged(tutor_database):
    data = tutor_database
    view = await create_session(data, mode="practice")
    answer = await submit(data, view.session.id, view.current_question.id, uuid4(), answer=False)

    async def snapshot():
        models = [
            AnswerRecordModel,
            MasteryRecordModel,
            ReviewTaskModel,
            QuestionModel,
            MaterialModel,
        ]
        async with data.factory() as session:
            return {
                model.__tablename__: (
                    await session.execute(
                        select(*model.__table__.columns).order_by(
                            *model.__table__.primary_key.columns
                        )
                    )
                ).all()
                for model in models
            }

    before = await snapshot()
    model = SequenceModel(
        responses=[call("get_answered_question_context", {}), final(citations=[data.citation_id])]
    )
    async with AsyncPostgresSaver.from_conn_string(psycopg_connection_string(data.url)) as saver:
        service = service_for(data, saver, model)
        conversation = await service.create(
            CreateTutorConversation(
                knowledge_base_id=data.kb,
                study_session_id=view.session.id,
                answered_question_id=answer.answer_record.question_id,
            )
        )
        result = await service.submit(conversation.id, payload("刚才为什么错", "answered_question"))
        assert result["status"] == "completed"
        result = await service_for(data, saver, model_for(data, fabricated=True)).submit(
            conversation.id, payload("failed explicit")
        )
        assert result["status"] == "failed"
    assert await snapshot() == before


async def test_r12_expired_orphan_has_safe_terminal_state(tutor_database):
    data = tutor_database
    async with AsyncPostgresSaver.from_conn_string(psycopg_connection_string(data.url)) as saver:
        service = service_for(data, saver, model_for(data))
        conversation = await service.create(CreateTutorConversation(knowledge_base_id=data.kb))
        request = payload()
        turn = await data.repository.reserve(
            conversation.id,
            request.client_message_id,
            request.content,
            request.intent,
            request_digest(request.content, request.intent),
            -1,
            "scripted",
        )
        state = await service.turn_status(conversation.id, turn.id)
        assert state["status"] == "failed" and state["error_code"] == "TUTOR_INTERRUPTED"
        assert (await service.submit(conversation.id, payload("明确重试")))["status"] == "completed"


async def test_conversation_management_http_validation_history_and_deleted_access(tutor_database):
    data = tutor_database
    model = model_for(data)
    async with AsyncPostgresSaver.from_conn_string(psycopg_connection_string(data.url)) as saver:
        service = service_for(data, saver, model)
        conversation = await service.create(CreateTutorConversation(knowledge_base_id=data.kb))
        request = payload()
        result = await service.submit(conversation.id, request)
        assert result["status"] == "completed"
        app = create_app()
        app.dependency_overrides[get_tutor_service] = lambda: service
        headers = (
            {"Authorization": "Bearer " + app_settings.api_access_token}
            if app_settings.api_access_token
            else {}
        )
        endpoint = f"/api/tutor/conversations/{conversation.id}"
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://acceptance", headers=headers
        ) as client:
            assert (await client.get(endpoint)).json()["conversation"]["title"] is None
            for invalid in (
                {"title": ""},
                {"title": "  "},
                {"title": "名" * 101},
                {"title": 123},
                {"title": "名字", "status": "active"},
                {},
            ):
                assert (await client.patch(endpoint, json=invalid)).status_code == 422
            renamed = await client.patch(endpoint, json={"title": "  聚时接口学习  "})
            assert renamed.status_code == 200
            assert renamed.json()["title"] == "聚时接口学习"
            assert renamed.json()["knowledge_base_id"] == str(data.kb)
            assert (await client.get(endpoint)).json()["total"] == 2
            listed = await client.get(
                "/api/tutor/conversations", params={"knowledge_base_id": str(data.kb)}
            )
            assert listed.json()["items"][0]["title"] == "聚时接口学习"
            assert (await client.post(endpoint + "/archive")).status_code == 200
            archived = await client.patch(endpoint, json={"title": "归档资料"})
            assert archived.json()["status"] == "archived"
            assert archived.json()["title"] == "归档资料"
            assert (await client.delete(endpoint)).status_code == 204
            assert (await client.delete(endpoint)).status_code == 204
            listed = await client.get(
                "/api/tutor/conversations", params={"knowledge_base_id": str(data.kb)}
            )
            assert listed.json()["total"] == 0 and listed.json()["items"] == []
            # Deleted conversations cannot be read, changed, resumed or replayed via old IDs.
            assert (await client.get(endpoint)).status_code == 404
            assert (await client.patch(endpoint, json={"title": "不能恢复"})).status_code == 404
            assert (await client.post(endpoint + "/archive")).status_code == 404
            assert (
                await client.post(endpoint + "/messages", json=request.model_dump(mode="json"))
            ).status_code == 404
            assert (await client.get(endpoint + "/turns/" + result["turn_id"])).status_code == 404
            assert (await client.delete(f"/api/tutor/conversations/{uuid4()}")).status_code == 404
        assert len(model.calls) == 2  # Management makes no further model requests.
        async with data.factory() as session:
            stored = await session.get(TutorConversationModel, conversation.id)
            assert stored.status == "deleted" and stored.title == "归档资料"
            assert stored.graph_thread_id == conversation.graph_thread_id
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(TutorMessageModel)
                    .where(TutorMessageModel.conversation_id == conversation.id)
                )
                == 2
            )
            assert await session.get(KnowledgeBaseModel, data.kb) is not None
            assert await session.get(MaterialModel, data.material) is not None
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(QuestionModel)
                    .where(QuestionModel.knowledge_base_id == data.kb)
                )
                == 6
            )
        assert (
            await saver.aget_tuple(
                {
                    "configurable": {
                        "thread_id": conversation.graph_thread_id,
                        "checkpoint_id": stored.last_committed_checkpoint_id,
                    }
                }
            )
        ) is not None


async def test_conversation_management_busy_orphan_and_scope(tutor_database):
    data = tutor_database
    model = model_for(data)
    async with AsyncPostgresSaver.from_conn_string(psycopg_connection_string(data.url)) as saver:
        service = service_for(data, saver, model)
        conversation = await service.create(CreateTutorConversation(knowledge_base_id=data.kb))
        async with data.repository.execution_lock(conversation.id) as acquired:
            assert acquired
            for operation in (
                service.rename(conversation.id, "新名称"),
                service.delete(conversation.id),
                service.archive(conversation.id),
            ):
                with pytest.raises(DomainError) as error:
                    await operation
                assert error.value.code == "TUTOR_THREAD_BUSY"
        assert (await data.repository.conversation(conversation.id)).status == "active"
        orphan = await data.repository.reserve(
            conversation.id, uuid4(), "未完成的问题", "materials", "a" * 64, -1, "scripted"
        )
        await service.rename(conversation.id, "仍可重命名")
        await service.delete(conversation.id)
        terminal = await data.repository.turn(conversation.id, turn_id=orphan.id)
        assert (
            terminal.status == "cancelled" and terminal.error_code == "TUTOR_CONVERSATION_DELETED"
        )
        assert len(model.calls) == 0
        hidden = await service.create(CreateTutorConversation(knowledge_base_id=data.kb))
        async with data.factory() as session:
            await session.execute(
                update(TutorConversationModel)
                .where(TutorConversationModel.id == hidden.id)
                .values(scope_key="another-user")
            )
            await session.commit()
        for operation in (service.rename(hidden.id, "不应访问"), service.delete(hidden.id)):
            with pytest.raises(DomainError) as error:
                await operation
            assert error.value.code == "TUTOR_CONVERSATION_NOT_FOUND"
        assert (await data.repository.list_conversations(data.kb, 1, 20))[1] == 0
