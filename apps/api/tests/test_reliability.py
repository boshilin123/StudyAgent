import asyncio
from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from study_agent.application.materials import MaterialService
from study_agent.application.questions import QuestionService
from study_agent.application.study import grade_question
from study_agent.config import Settings
from study_agent.domain.errors import DomainError
from study_agent.domain.models import DocumentChunk, QuestionSource
from study_agent.infrastructure.readiness import get_readiness_probes
from study_agent.infrastructure.study_state import RedisLearningSessionSnapshotStore
from study_agent.main import app, create_app
from tests.fakes import (
    FakeDocumentIndex,
    FakeIngestionDispatcher,
    FakeObjectStorage,
    FakeQuestionIndex,
    FakeUnitOfWork,
)
from tests.test_p3_api import _ready_material
from tests.test_study_grading import make_question


@pytest.mark.parametrize(
    "expected,answer",
    [
        ("-1", "1"),
        ("1.5", "15"),
        ("TCP/IP", "TCPIP"),
        ("C++", "C"),
        ("a b", "ab"),
        (".NET", "NET"),
    ],
)
def test_fill_blank_preserves_semantic_symbols(expected: str, answer: str) -> None:
    assert not grade_question(make_question("fill_blank", [expected]), answer).correct


def test_fill_blank_allows_explicit_aliases() -> None:
    assert grade_question(make_question("fill_blank", ["TCP/IP", "TCPIP"]), "TCPIP").correct


class DownQueue:
    def dispatch(self, **_: object) -> None:
        raise ConnectionError("simulated broker outage")


@pytest.mark.asyncio
async def test_generation_dispatch_failure_is_retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "study_agent.application.questions.get_settings",
        lambda: Settings(_env_file=None, llm_base_url="http://mock/v1", llm_model="mock"),
    )
    uow = FakeUnitOfWork()
    material = _ready_material()
    uow.materials.items[material.id] = material
    service = QuestionService()
    kwargs = dict(
        material_id=material.id,
        target_question_count=3,
        allowed_types=["true_false"],
        difficulty_min=1,
        difficulty_max=3,
        language="zh-CN",
    )
    with pytest.raises(DomainError, match="提交失败"):
        await service.create_generation_job(uow, DownQueue(), **kwargs)
    assert next(iter(uow.question_generation_jobs.items.values())).status == "failed"
    job = await service.create_generation_job(uow, FakeIngestionDispatcher(), **kwargs)
    assert job.status == "pending"


@pytest.mark.asyncio
async def test_reprocess_dispatch_failure_can_be_retried() -> None:
    uow = FakeUnitOfWork()
    material = _ready_material()
    uow.materials.items[material.id] = material
    with pytest.raises(DomainError):
        await MaterialService().reprocess(uow, DownQueue(), material.id)
    assert next(iter(uow.ingestion_jobs.items.values())).status == "failed"
    job = await MaterialService().reprocess(uow, FakeIngestionDispatcher(), material.id)
    assert job.status == "pending"


@pytest.mark.asyncio
async def test_delete_only_disables_questions_losing_every_source() -> None:
    uow = FakeUnitOfWork()
    material = _ready_material()
    uow.materials.items[material.id] = material
    chunk_id, surviving_id = uuid4(), uuid4()
    uow.document_chunks.items[material.id] = [
        DocumentChunk(
            id=chunk_id,
            material_id=material.id,
            chunk_index=0,
            content="TCP",
            token_count=1,
            page_start=None,
            page_end=None,
            heading_path=[],
            content_hash="hash",
            vector_id=None,
            embedding_model=None,
        )
    ]
    first = replace(
        make_question("true_false", ["正确"]),
        vector_id="first",
        sources=[QuestionSource(chunk_id, "TCP", 1)],
    )
    shared = replace(
        make_question("true_false", ["正确"]),
        vector_id="shared",
        sources=[QuestionSource(chunk_id, "TCP", 1), QuestionSource(surviving_id, "TCP", 2)],
    )
    uow.questions.items = {first.id: first, shared.id: shared}
    index = FakeQuestionIndex()
    await MaterialService().delete(
        uow, FakeObjectStorage(), FakeDocumentIndex(), material.id, index
    )
    assert uow.questions.items[first.id].status == "disabled"
    assert uow.questions.items[first.id].vector_id is None
    assert uow.questions.items[shared.id].status == "active"
    assert len(uow.questions.items[shared.id].sources) == 1
    assert index.deleted == [first.id]


@pytest.mark.asyncio
async def test_corrupt_learning_snapshot_is_cache_miss() -> None:
    class RedisStub:
        async def get(self, _: str) -> str:
            return "{invalid json"

    store = RedisLearningSessionSnapshotStore(redis_url="redis://localhost", ttl_seconds=10)
    store.redis = RedisStub()  # type: ignore[assignment]
    assert await store.get(uuid4()) is None


def test_readiness_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    async def slow() -> None:
        await asyncio.sleep(1)

    monkeypatch.setattr(
        "study_agent.api.routes.health.get_settings",
        lambda: Settings(_env_file=None, readiness_timeout_seconds=0.01),
    )
    app.dependency_overrides[get_readiness_probes] = lambda: {"postgresql": slow}
    try:
        with TestClient(app) as client:
            response = client.get("/api/health/ready")
        assert response.status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_production_requires_token() -> None:
    with pytest.raises(ValueError, match="API_ACCESS_TOKEN"):
        Settings(_env_file=None, app_env="production", api_access_token=None)


def test_access_token_authentication_and_public_liveness(monkeypatch: pytest.MonkeyPatch) -> None:
    token = "test_only_1234567890_1234567890_1234567890"
    monkeypatch.setattr(
        "study_agent.main.settings", Settings(_env_file=None, api_access_token=token)
    )
    protected_app = create_app()

    @protected_app.get("/api/protected")
    def protected() -> dict[str, str]:
        return {"result": "ok"}

    with TestClient(protected_app) as client:
        assert client.get("/api/protected").status_code == 401
        assert (
            client.get("/api/protected", headers={"Authorization": "Bearer wrong"}).status_code
            == 401
        )
        assert (
            client.get("/api/protected", headers={"Authorization": f"Bearer {token}"}).status_code
            == 200
        )
        assert client.get("/api/health/live").status_code == 200
