"""Exercise v1 model configuration and existing chains without provider requests."""

import json
from typing import Any
from uuid import uuid4

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_openai import ChatOpenAI
from pydantic import ValidationError

from study_agent.application.study_explanations import (
    ExplanationDraft,
    LangChainStudyExplanationGenerator,
)
from study_agent.config import Settings
from study_agent.llm.models import get_chat_model
from study_agent.question_generation import chains
from study_agent.question_generation.schemas import KnowledgePointBatch, QuestionBatch


def configured_settings(**changes: Any) -> Settings:
    return Settings(
        _env_file=None,
        llm_base_url="http://model.invalid/v1",
        llm_api_key="test-key",
        llm_model="base-model",
        **changes,
    )


@pytest.mark.parametrize("purpose", ["question_generation", "study_explanation", "tutoring"])
def test_factory_uses_openai_adapter_and_preserves_config(purpose: Any) -> None:
    model = get_chat_model(configured_settings(), purpose=purpose)
    assert isinstance(model, ChatOpenAI)
    assert model.model_name == "base-model"
    assert str(model.openai_api_base) == "http://model.invalid/v1"
    assert model.temperature == 0.1
    assert model.request_timeout == 60.0
    assert model.extra_body == {"enable_thinking": False}
    assert model.openai_api_key is not None
    assert model.openai_api_key.get_secret_value() == "test-key"


def test_tutor_overrides_zero_false_and_inherits_missing_fields() -> None:
    model = get_chat_model(
        configured_settings(
            tutor_llm_model="tutor-model",
            tutor_llm_temperature=0,
            tutor_llm_timeout_seconds=15,
            tutor_llm_enable_thinking=False,
        ),
        purpose="tutoring",
    )
    assert isinstance(model, ChatOpenAI)
    assert model.model_name == "tutor-model"
    assert str(model.openai_api_base) == "http://model.invalid/v1"
    assert model.temperature == 0
    assert model.request_timeout == 15
    assert model.extra_body == {"enable_thinking": False}


def test_tutor_credentials_and_endpoint_override_independently() -> None:
    model = get_chat_model(
        configured_settings(
            tutor_llm_base_url="http://tutor.invalid/v1",
            tutor_llm_api_key="tutor-test-key",
        ),
        purpose="tutoring",
    )
    assert isinstance(model, ChatOpenAI)
    assert str(model.openai_api_base) == "http://tutor.invalid/v1"
    assert model.openai_api_key is not None
    assert model.openai_api_key.get_secret_value() == "tutor-test-key"
    assert model.model_name == "base-model"


def test_tutor_config_cannot_change_generation_model() -> None:
    model = get_chat_model(
        configured_settings(tutor_llm_model="tutor-model", tutor_llm_temperature=1),
        purpose="question_generation",
    )
    assert isinstance(model, ChatOpenAI)
    assert model.model_name == "base-model"
    assert model.temperature == 0.1


@pytest.mark.parametrize("purpose", ["question_generation", "tutoring"])
def test_provider_extension_can_be_disabled(purpose: Any) -> None:
    model = get_chat_model(
        configured_settings(llm_send_enable_thinking=False), purpose=purpose
    )
    assert isinstance(model, ChatOpenAI)
    assert model.extra_body is None


def test_tutor_provider_extension_override() -> None:
    model = get_chat_model(
        configured_settings(tutor_llm_send_enable_thinking=False), purpose="tutoring"
    )
    assert isinstance(model, ChatOpenAI)
    assert model.extra_body is None


def test_tutor_disables_sdk_retries_and_caps_output() -> None:
    model = get_chat_model(
        configured_settings(tutor_llm_max_output_tokens=900), purpose="tutoring"
    )
    assert isinstance(model, ChatOpenAI)
    assert model.max_retries == 0
    assert model.max_tokens == 900
    chain_model = get_chat_model(configured_settings(), purpose="question_generation")
    assert isinstance(chain_model, ChatOpenAI)
    assert chain_model.max_retries is None  # Adapter delegates to the SDK default.
    assert chain_model.max_tokens is None


def test_empty_tutor_env_overrides_inherit(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "TUTOR_LLM_BASE_URL",
        "TUTOR_LLM_API_KEY",
        "TUTOR_LLM_MODEL",
        "TUTOR_CHECKPOINTER_DB_URL",
    ):
        monkeypatch.setenv(key, "")
    settings = configured_settings()
    assert settings.tutor_checkpointer_db_url is None
    model = get_chat_model(settings, purpose="tutoring")
    assert isinstance(model, ChatOpenAI)
    assert model.model_name == "base-model"
    assert str(model.openai_api_base) == "http://model.invalid/v1"
    assert model.openai_api_key is not None
    assert model.openai_api_key.get_secret_value() == "test-key"


@pytest.mark.parametrize("purpose", ["question_generation", "study_explanation", "tutoring"])
def test_missing_model_configuration_fails_before_provider_request(purpose: Any) -> None:
    with pytest.raises(ValueError, match="LLM_BASE_URL"):
        get_chat_model(
            Settings(
                _env_file=None,
                llm_base_url=None,
                llm_model=None,
                tutor_llm_base_url=None,
                tutor_llm_model=None,
            ),
            purpose=purpose,
        )


def test_invalid_purpose_is_rejected() -> None:
    with pytest.raises(ValueError, match="purpose"):
        get_chat_model(configured_settings(), purpose="untrusted")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "changes",
    [{"tutor_max_tool_calls": 0}, {"tutor_timeout_seconds": 0}, {"tutor_llm_temperature": -1}],
)
def test_tutor_budget_configuration_validated(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        configured_settings(**changes)


@pytest.mark.parametrize("method", ["function_calling", "json_schema"])
def test_existing_provider_structured_output_binding_is_supported(method: Any) -> None:
    settings = configured_settings(llm_structured_output_method=method)
    assert chains.create_knowledge_point_chain(settings) is not None
    assert chains.create_question_generation_chain(settings) is not None


@pytest.mark.asyncio
async def test_generation_lcel_parsers_on_v1(monkeypatch: pytest.MonkeyPatch) -> None:
    chunk_id = str(uuid4())
    point = {
        "canonical_key": "tcp-handshake",
        "name": "TCP 握手",
        "description": "TCP 使用三次握手建立连接",
        "importance": 0.9,
        "difficulty": 2,
        "source_chunk_ids": [chunk_id],
    }
    question = {
        "knowledge_point_key": "tcp-handshake",
        "question_type": "true_false",
        "stem": "TCP 通过三次握手建立连接。",
        "correct_answers": ["正确"],
        "explanation": "原文说明 TCP 使用三次握手建立连接。",
        "difficulty": 2,
        "source_chunk_ids": [chunk_id],
        "source_quotes": ["TCP 通过三次握手建立连接"],
    }
    fake = FakeListChatModel(
        responses=[json.dumps({"items": [point]}), json.dumps({"items": [question]})]
    )
    monkeypatch.setattr(chains, "get_chat_model", lambda *_args, **_kwargs: fake)
    settings = configured_settings()
    points = await chains.create_knowledge_point_chain(settings).ainvoke(
        {"language": "zh", "context": f"chunk_id={chunk_id} TCP 通过三次握手建立连接"}
    )
    questions = await chains.create_question_generation_chain(settings).ainvoke(
        {
            "target_count": 1,
            "allowed_types": ["true_false"],
            "difficulty_min": 1,
            "difficulty_max": 3,
            "language": "zh",
            "knowledge_points": chains.serialize_knowledge_points(points),
            "context": f"chunk_id={chunk_id} TCP 通过三次握手建立连接",
        }
    )
    assert isinstance(points, KnowledgePointBatch)
    assert isinstance(questions, QuestionBatch)
    assert questions.items[0].correct_answers == ["正确"]


@pytest.mark.asyncio
async def test_explanation_lcel_parser_on_v1(monkeypatch: pytest.MonkeyPatch) -> None:
    from study_agent.application import study_explanations

    fake = FakeListChatModel(responses=['{"conclusion":"回答错误", "gap":"应使用三次握手"}'])
    monkeypatch.setattr(study_explanations, "get_chat_model", lambda *_args, **_kwargs: fake)
    generator = LangChainStudyExplanationGenerator(configured_settings())
    assert generator.chain is not None
    result = await generator.chain.ainvoke(
        {
            "stem": "TCP 如何建立连接",
            "question_type": "fill_blank",
            "user_answer": "一次",
            "correct_answer": "三次",
            "base_explanation": "三次握手",
            "evidence": "TCP 通过三次握手建立连接",
        }
    )
    assert isinstance(result, ExplanationDraft)
    assert result.gap == "应使用三次握手"
