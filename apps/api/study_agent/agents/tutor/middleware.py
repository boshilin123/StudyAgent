import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse, ToolCallRequest
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.types import Command
from pydantic import BaseModel

from study_agent.domain.errors import DomainError


def required_tool_request(request: ModelRequest[Any]) -> ModelRequest[Any]:
    """Expose mandatory server-bound reads before allowing optional tools or final output."""
    context = getattr(getattr(request, "runtime", None), "context", None)
    if context is None:
        return request
    read_flags = request.state.get("evidence_flags", [])
    if not isinstance(read_flags, list) or not all(isinstance(flag, str) for flag in read_flags):
        raise DomainError("TUTOR_CONTEXT_UNAVAILABLE", "本轮工具读取状态不正确", status_code=503)
    flags = set(read_flags)
    required = []
    if context.answered_question_id:
        required.append(("answered_question", "get_answered_question_context"))
    if context.intent in {"progress", "mistakes"}:
        required.append(("progress", "get_learning_progress"))
    if context.intent == "mistakes":
        required.append(("mistakes", "list_recent_mistakes"))
    for flag, name in required:
        if flag not in flags:
            tools = [tool for tool in request.tools if getattr(tool, "name", None) == name]
            if not tools:
                raise DomainError(
                    "TUTOR_REQUIRED_TOOL_MISSING", "本轮必需的学习记录工具不可用", status_code=503
                )
            # ToolStrategy otherwise permits the model to finalize before mandatory reads.
            # Restore the original tools/format next time, once this tool records its flag.
            return request.override(tools=tools, response_format=None, tool_choice="any")
    return request


def tool_result_chars(result: ToolMessage | Command[Any]) -> int:
    """Count model-visible content, excluding the duplicate evidence ledger and repr overhead."""
    messages: object
    if isinstance(result, ToolMessage):
        messages = [result]
    elif isinstance(result.update, dict):
        messages = result.update.get("messages")
    else:
        raise DomainError("TUTOR_TOOL_RESULT_INVALID", "工具结果格式不正确", status_code=503)
    if not isinstance(messages, list) or not all(isinstance(m, ToolMessage) for m in messages):
        raise DomainError("TUTOR_TOOL_RESULT_INVALID", "工具消息格式不正确", status_code=503)
    return sum(
        len(message.content)
        if isinstance(message.content, str)
        else len(json.dumps(message.content, ensure_ascii=False))
        for message in messages
    )


@dataclass
class RunBudget:
    deadline: float
    max_tool_calls: int = 6
    max_result_chars: int = 16000
    model_calls: int = 0
    tool_calls: int = 0
    searches: int = 0
    result_chars: int = 0
    total_tokens: int = 0
    usage_known: bool = True
    trace: list[dict[str, Any]] = field(
        default_factory=lambda: [
            {
                "kind": "metadata",
                "execution_kind": "agent",
                "graph_version": "tutor-v1",
                "prompt_version": "tutor-v1",
            }
        ]
    )
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def check(self) -> None:
        if time.monotonic() >= self.deadline:
            raise DomainError("TUTOR_TIMEOUT", "辅导执行超时", status_code=504)
        if self.total_tokens >= 12000:
            raise DomainError("TUTOR_BUDGET_EXCEEDED", "辅导用量预算耗尽", status_code=503)

    def usage(self) -> dict[str, Any]:
        return {
            "model_calls": self.model_calls,
            "tool_calls": self.tool_calls,
            "total_tokens": self.total_tokens if self.usage_known else None,
            "known": self.usage_known,
        }


class TutorBudgetMiddleware(AgentMiddleware):
    def __init__(self, budget: RunBudget):
        self.budget = budget

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        self.budget.check()
        request = required_tool_request(request)
        if self.budget.model_calls >= 6:
            raise DomainError("TUTOR_BUDGET_EXCEEDED", "模型调用次数达到上限", status_code=503)
        # Cap estimated input independently of provider usage and completion limits.
        if sum(len(str(m.content)) for m in request.messages) > 24000:
            raise DomainError("TUTOR_BUDGET_EXCEEDED", "辅导上下文超过输入预算", status_code=503)
        self.budget.model_calls += 1
        try:
            result = await asyncio.wait_for(
                handler(request),
                timeout=min(30, max(0.01, self.budget.deadline - time.monotonic())),
            )
        except BaseException:
            self.budget.usage_known = False
            raise
        # ToolStrategy adds a synthetic ToolMessage acknowledgement to the same
        # ModelResponse. It is not another provider completion or billed call.
        model_messages = [message for message in result.result if isinstance(message, AIMessage)]
        if not model_messages:
            self.budget.usage_known = False
        for message in model_messages:
            usage = getattr(message, "usage_metadata", None)
            if usage:
                self.budget.total_tokens += usage.get("total_tokens", 0)
            else:
                self.budget.usage_known = False
        self.budget.trace.append(
            {
                "kind": "model",
                "sequence": self.budget.model_calls,
                "usage_known": self.budget.usage_known,
            }
        )
        return result

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        # Providers may emit several calls at once; serialize both budget reservation and execution.
        async with self.budget.lock:
            self.budget.check()
            if self.budget.tool_calls >= self.budget.max_tool_calls:
                raise DomainError("TUTOR_BUDGET_EXCEEDED", "工具调用次数达到上限", status_code=503)
            self.budget.tool_calls += 1
            name = request.tool_call["name"]
            from study_agent.agents.tutor.tools import MistakesInput, NoInput, SearchInput

            schemas: dict[str, type[BaseModel]] = {
                "search_learning_materials": SearchInput,
                "list_recent_mistakes": MistakesInput,
                "get_learning_progress": NoInput,
                "get_answered_question_context": NoInput,
            }
            if name not in schemas:
                raise DomainError("TUTOR_TOOL_NOT_ALLOWED", "工具未注册", status_code=503)
            try:
                schemas[name].model_validate(request.tool_call.get("args", {}))
            except ValueError as exc:
                raise DomainError(
                    "TUTOR_TOOL_ARGUMENT_INVALID", "工具参数越界或包含未允许的字段", status_code=503
                ) from exc
            if name == "search_learning_materials":
                if self.budget.searches >= 2:
                    raise DomainError(
                        "TUTOR_BUDGET_EXCEEDED", "最多允许两次资料检索", status_code=503
                    )
                self.budget.searches += 1
            result = await asyncio.wait_for(
                handler(request),
                timeout=min(10, max(0.01, self.budget.deadline - time.monotonic())),
            )
            if isinstance(result, ToolMessage) and result.status == "error":
                result = ToolMessage(
                    content='{"code":"TOOL_UNAVAILABLE","message":"工具无法完成，请说明资料或当前状态不足。"}',
                    tool_call_id=result.tool_call_id,
                    name=result.name,
                    status="error",
                )
            content_chars = tool_result_chars(result)
            self.budget.result_chars += content_chars
            if self.budget.result_chars > self.budget.max_result_chars:
                raise DomainError(
                    "TUTOR_BUDGET_EXCEEDED", "工具结果超过上下文预算", status_code=503
                )
            self.budget.trace.append(
                {
                    "kind": "tool",
                    "name": name,
                    "sequence": self.budget.tool_calls,
                    "content_chars": content_chars,
                    "total_result_chars": self.budget.result_chars,
                }
            )
            return result
