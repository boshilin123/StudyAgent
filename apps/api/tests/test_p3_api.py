from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from study_agent.api.dependencies import (
    get_question_generation_dispatcher,
    get_question_index,
    get_uow,
)
from study_agent.config import Settings
from study_agent.domain.models import Material, Question, QuestionSource
from study_agent.main import app
from tests.fakes import FakeQuestionGenerationDispatcher, FakeQuestionIndex, FakeUnitOfWork


@pytest.fixture
def p3_context(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, FakeUnitOfWork]]:
    uow = FakeUnitOfWork()
    dispatcher = FakeQuestionGenerationDispatcher()
    question_index = FakeQuestionIndex()

    async def override_uow():  # type: ignore[no-untyped-def]
        yield uow

    monkeypatch.setattr(
        "study_agent.application.questions.get_settings",
        lambda: Settings(
            _env_file=None,
            llm_base_url="http://fake-llm/v1",
            llm_model="fake-model",
        ),
    )
    app.dependency_overrides[get_uow] = override_uow
    app.dependency_overrides[get_question_generation_dispatcher] = lambda: dispatcher
    app.dependency_overrides[get_question_index] = lambda: question_index
    with TestClient(app) as client:
        yield client, uow
    app.dependency_overrides.clear()


def _ready_material() -> Material:
    now = datetime.now(UTC)
    return Material(
        id=uuid4(),
        knowledge_base_id=uuid4(),
        title="网络",
        original_filename="网络.md",
        media_type="text/markdown",
        storage_uri="fake://network.md",
        sha256="a" * 64,
        size_bytes=10,
        language="zh-CN",
        parse_status="ready",
        parser_version="p2-v1",
        error_message=None,
        created_at=now,
        updated_at=now,
    )


def test_create_and_query_question_generation_job(
    p3_context: tuple[TestClient, FakeUnitOfWork],
) -> None:
    client, uow = p3_context
    material = _ready_material()
    base = client.post("/api/knowledge-bases", json={"name": "生成任务测试"}).json()
    material = replace(material, knowledge_base_id=UUID(base["id"]))
    uow.materials.items[material.id] = material

    response = client.post(
        f"/api/materials/{material.id}/question-generation-jobs",
        json={
            "target_question_count": 3,
            "allowed_types": ["single_choice", "fill_blank", "true_false"],
            "difficulty_min": 1,
            "difficulty_max": 3,
        },
    )
    assert response.status_code == 202
    job = response.json()
    assert job["status"] == "pending"
    assert job["allowed_types"] == ["single_choice", "fill_blank", "true_false"]
    assert client.get(f"/api/question-generation-jobs/{job['id']}").status_code == 200

    conflict = client.post(
        f"/api/materials/{material.id}/question-generation-jobs",
        json={"target_question_count": 3},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "QUESTION_GENERATION_RUNNING"
    history = client.get(f"/api/materials/{material.id}/question-generation-jobs")
    assert history.status_code == 200
    assert [item["id"] for item in history.json()] == [job["id"]]
    assert client.delete(f"/api/knowledge-bases/{base['id']}").status_code == 204
    uow.question_generation_jobs.items[UUID(job["id"])].status = "completed"
    assert (
        client.post(
            f"/api/materials/{material.id}/question-generation-jobs",
            json={"target_question_count": 12},
        ).status_code
        == 409
    )


@pytest.mark.parametrize("count", [1, 12, 100])
def test_custom_generation_count(p3_context: tuple[TestClient, FakeUnitOfWork], count: int) -> None:
    client, uow = p3_context
    base = client.post("/api/knowledge-bases", json={"name": "自定义数量"}).json()
    material = replace(_ready_material(), knowledge_base_id=UUID(base["id"]))
    uow.materials.items[material.id] = material
    response = client.post(
        f"/api/materials/{material.id}/question-generation-jobs",
        json={"target_question_count": count, "allowed_types": ["true_false"]},
    )
    assert response.status_code == 202
    assert response.json()["target_question_count"] == count
    assert (
        client.post(
            f"/api/materials/{material.id}/question-generation-jobs",
            json={"target_question_count": 101},
        ).status_code
        == 422
    )


def test_question_review_edit_activate_and_disable(
    p3_context: tuple[TestClient, FakeUnitOfWork],
) -> None:
    client, uow = p3_context
    question_id = uuid4()
    question = Question(
        id=question_id,
        knowledge_base_id=uuid4(),
        knowledge_point_id=uuid4(),
        question_type="true_false",
        stem="TCP 通过三次握手建立连接。",
        options=None,
        correct_answer=["正确"],
        scoring_points=[],
        explanation="该描述与资料一致。",
        difficulty=1,
        max_score=10,
        status="draft",
        content_hash="before",
        vector_id=None,
        sources=[QuestionSource(chunk_id=uuid4(), quote="TCP 通过三次握手", rank=1)],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    uow.questions.items[question_id] = question

    assert client.get("/api/questions").json()["total"] == 1
    activated = client.post(f"/api/questions/{question_id}/activate")
    assert activated.status_code == 200
    assert activated.json()["status"] == "active"

    edited = client.patch(
        f"/api/questions/{question_id}",
        json={"explanation": "资料明确说明连接建立需要三次握手。"},
    )
    assert edited.status_code == 200
    assert edited.json()["status"] == "draft"
    assert uow.questions.items[question_id] != replace(question, status="active")

    disabled = client.post(f"/api/questions/{question_id}/disable")
    assert disabled.status_code == 200
    assert disabled.json()["status"] == "disabled"


@pytest.mark.parametrize("initial_status", ["draft", "active", "disabled", "rejected"])
@pytest.mark.parametrize("fail_cleanup_once", [False, True])
def test_delete_question_hides_it_and_blocks_edit_or_activation(
    p3_context: tuple[TestClient, FakeUnitOfWork],
    initial_status: str,
    fail_cleanup_once: bool,
) -> None:
    client, uow = p3_context
    question = Question(
        id=uuid4(),
        knowledge_base_id=uuid4(),
        knowledge_point_id=uuid4(),
        question_type="true_false",
        stem="TCP需要建立连接。",
        options=None,
        correct_answer=["正确"],
        scoring_points=[],
        explanation="资料说明TCP建立连接。",
        difficulty=1,
        max_score=10,
        status=initial_status,
        content_hash=uuid4().hex,
        vector_id="test-vector",
        sources=[QuestionSource(uuid4(), "TCP建立连接", 1)],
    )
    uow.questions.items[question.id] = question
    index = app.dependency_overrides[get_question_index]()
    original_cleanup = index.delete_questions
    cleanup_failed = False

    async def cleanup(ids):
        nonlocal cleanup_failed
        if fail_cleanup_once and not cleanup_failed:
            cleanup_failed = True
            raise ConnectionError("index unavailable")
        await original_cleanup(ids)

    index.delete_questions = cleanup
    first = client.delete(f"/api/questions/{question.id}")
    assert first.status_code == (503 if fail_cleanup_once else 204)
    if fail_cleanup_once:
        assert first.json()["error"]["code"] == "QUESTION_DELETE_INDEX_PENDING"
        assert client.get("/api/questions").json()["total"] == 0
    assert client.delete(f"/api/questions/{question.id}").status_code == 204
    assert client.delete(f"/api/questions/{uuid4()}").status_code == 204
    for params in [
        {},
        {"status": initial_status},
        {"knowledge_base_id": str(question.knowledge_base_id)},
    ]:
        assert client.get("/api/questions", params=params).json()["total"] == 0
    assert client.get(f"/api/questions/{question.id}").status_code == 404
    assert (
        client.patch(f"/api/questions/{question.id}", json={"stem": "试图修改已删题目"}).status_code
        == 404
    )
    assert client.post(f"/api/questions/{question.id}/activate").status_code == 404
    assert client.post(f"/api/questions/{question.id}/disable").status_code == 404
    retained = uow.questions.items[question.id]
    assert retained.status == "deleted" and retained.vector_id is None
    assert retained.sources == question.sources and retained.stem == question.stem
    assert index.deleted == [question.id] * (1 if fail_cleanup_once else 2)


def test_generation_history_exposes_rejected_candidates(
    p3_context: tuple[TestClient, FakeUnitOfWork],
) -> None:
    client, uow = p3_context
    base = client.post("/api/knowledge-bases", json={"name": "拒绝详情"}).json()
    material = replace(_ready_material(), knowledge_base_id=UUID(base["id"]))
    uow.materials.items[material.id] = material
    job = client.post(
        f"/api/materials/{material.id}/question-generation-jobs", json={"target_question_count": 10}
    ).json()
    saved = uow.question_generation_jobs.items[UUID(job["id"])]
    saved.status = "partial"
    saved.rejected_count = 1
    saved.rejected_candidates = [
        {"reason": "片段与引文数量不一致", "question": {"stem": "未通过校验的候选题"}}
    ]
    queried = client.get(f"/api/question-generation-jobs/{job['id']}").json()
    assert queried["rejected_candidates"] == saved.rejected_candidates
    assert (
        client.get(f"/api/materials/{material.id}/question-generation-jobs").json()[0][
            "rejected_candidates"
        ]
        == saved.rejected_candidates
    )
    assert client.get("/api/questions").json()["total"] == 0
