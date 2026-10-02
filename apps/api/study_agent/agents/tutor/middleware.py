import asyncio
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
            self.budget.result_chars += len(str(result))
            if self.budget.result_chars > self.budget.max_result_chars:
                raise DomainError(
                    "TUTOR_BUDGET_EXCEEDED", "工具结果超过上下文预算", status_code=503
                )
            self.budget.trace.append(
                {"kind": "tool", "name": name, "sequence": self.budget.tool_calls}
            )
            return result
