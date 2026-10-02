"""Shared model adapter for existing chains and the tutoring agent.

OpenAI-compatible endpoints use LangChain's explicit OpenAI provider adapter.
No settings, credentials, request context or database sessions are cached here.
"""

from typing import Any, Literal, cast
from urllib.parse import urlsplit

from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import SecretStr

from study_agent.config import Settings

ModelPurpose = Literal["question_generation", "study_explanation", "tutoring"]


def get_chat_model(settings: Settings, *, purpose: ModelPurpose) -> BaseChatModel:
    """Create a model using only server configuration, with per-field tutor inheritance."""
    if purpose not in {"question_generation", "study_explanation", "tutoring"}:
        raise ValueError("Unsupported model purpose")

    def configured(name: str) -> object:
        if purpose == "tutoring":
            tutor_value = getattr(settings, f"tutor_{name}")
            if tutor_value is not None:
                return tutor_value
        return getattr(settings, name)

    base_url = configured("llm_base_url")
    model = configured("llm_model")
    if not base_url or not model:
        raise ValueError("未配置 LLM_BASE_URL 或 LLM_MODEL（辅导可通过 TUTOR_LLM_* 覆盖）")
    extra_body = (
        {"enable_thinking": configured("llm_enable_thinking")}
        if configured("llm_send_enable_thinking")
        else None
    )
    # DeepSeek defaults to thinking mode and uses a native `thinking` object;
    # Qwen's `enable_thinking` extension is ignored there. ToolStrategy forces
    # a tool choice, which DeepSeek permits in non-thinking mode only.
    # Keep the configured preference and scope this provider mapping to tutoring.
    if (
        purpose == "tutoring"
        and urlsplit(str(base_url)).hostname == "api.deepseek.com"
        and configured("llm_send_enable_thinking")
    ):
        extra_body = {
            "thinking": {"type": "enabled" if configured("llm_enable_thinking") else "disabled"}
        }
    tutor_limits: dict[str, Any] = (
        {"max_retries": 0, "max_tokens": settings.tutor_llm_max_output_tokens}
        if purpose == "tutoring"
        else {}
    )
    return cast(
        BaseChatModel,
        init_chat_model(
            str(model),
            model_provider="openai",
            base_url=str(base_url),
            api_key=SecretStr(str(configured("llm_api_key") or "not-required")),
            temperature=configured("llm_temperature"),
            timeout=configured("llm_timeout_seconds"),
            extra_body=extra_body,
            **tutor_limits,
        ),
    )
