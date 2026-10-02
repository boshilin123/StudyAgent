"""Provider-native thinking configuration; no paid model calls in these tests."""

import httpx
import pytest
from langchain_openai import ChatOpenAI
from openai import BadRequestError

from study_agent.config import Settings
from study_agent.llm.models import get_chat_model
from study_agent.llm.provider_errors import tutoring_request_rejection


def settings(**overrides):
    return Settings(
        _env_file=None,
        llm_base_url="https://api.deepseek.com",
        llm_api_key="test",
        llm_model="deepseek-flash",
        **overrides,
    )


@pytest.mark.parametrize("enabled,native", [(False, "disabled"), (True, "enabled")])
def test_official_deepseek_tutor_uses_native_thinking_parameter(enabled, native):
    model = get_chat_model(settings(tutor_llm_enable_thinking=enabled), purpose="tutoring")
    assert isinstance(model, ChatOpenAI)
    assert model.extra_body == {"thinking": {"type": native}}
    assert model.max_retries == 0 and model.max_tokens == 1500
    bound = model.bind_tools(
        [
            {
                "type": "function",
                "function": {
                    "name": "TutorAnswerDraft",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            }
        ],
        tool_choice="any",
    )
    assert bound.kwargs["tool_choice"] == "required"


def test_provider_mapping_preserves_chain_and_explicit_extension_opt_out():
    chain = get_chat_model(settings(llm_enable_thinking=False), purpose="question_generation")
    assert isinstance(chain, ChatOpenAI)
    assert chain.extra_body == {"enable_thinking": False}
    tutor = get_chat_model(settings(tutor_llm_send_enable_thinking=False), purpose="tutoring")
    assert isinstance(tutor, ChatOpenAI)
    assert tutor.extra_body is None


def test_tutor_endpoint_override_selects_provider_and_hostname_is_exact():
    other = get_chat_model(
        settings(tutor_llm_base_url="https://api.deepseek.com.evil.invalid"), purpose="tutoring"
    )
    assert isinstance(other, ChatOpenAI)
    assert other.extra_body == {"enable_thinking": False}
    via_override = get_chat_model(
        Settings(
            _env_file=None,
            llm_model="base",
            llm_base_url="https://model.invalid",
            tutor_llm_base_url="https://api.deepseek.com/v1",
            tutor_llm_model="deepseek-flash",
        ),
        purpose="tutoring",
    )
    assert isinstance(via_override, ChatOpenAI)
    assert via_override.extra_body == {"thinking": {"type": "disabled"}}


@pytest.mark.parametrize(
    "provider_message,expected",
    [
        ("Thinking mode does not support this tool_choice", "TUTOR_MODEL_CONFIGURATION_INVALID"),
        ("Model does not support tools", "TUTOR_MODEL_UNSUPPORTED"),
        ("Unknown request parameter: extra_body private-secret", "TUTOR_PROVIDER_REQUEST_REJECTED"),
    ],
)
def test_bad_request_is_classified_without_blanket_model_incompatibility(
    provider_message, expected
):
    error = BadRequestError(
        "provider rejected",
        response=httpx.Response(400, request=httpx.Request("POST", "https://model.invalid")),
        body={"message": provider_message},
    )
    code, message = tutoring_request_rejection(error)
    assert code == expected
    assert "private-secret" not in message
