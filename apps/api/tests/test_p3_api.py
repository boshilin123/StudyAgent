from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from study_agent.api.dependencies import (
    get_question_generation_dispatcher,
    get_question_vector_index,
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
    app.dependency_overrides[get_question_vector_index] = lambda: question_index
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
