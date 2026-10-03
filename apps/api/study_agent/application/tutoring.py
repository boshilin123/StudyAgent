import asyncio
import hashlib
import json
import re
import time
from collections.abc import Callable, Sequence
from typing import Any
from uuid import UUID, uuid4

from langchain.agents.middleware.model_call_limit import ModelCallLimitExceededError
from langchain.agents.middleware.tool_call_limit import ToolCallLimitExceededError
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.errors import GraphRecursionError
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Overwrite
from openai import BadRequestError

from study_agent.agents.tutor.agent import create_tutor_agent
from study_agent.agents.tutor.context import TutorContext
from study_agent.agents.tutor.middleware import RunBudget
from study_agent.agents.tutor.prompts import TUTOR_GRAPH_VERSION
from study_agent.agents.tutor.schemas import TutorAnswerDraft
from study_agent.agents.tutor.validation import validate_draft
from study_agent.api.tutoring_schemas import CreateTutorConversation, SubmitTutorMessage
from study_agent.application.learning_queries import LearningQueries
from study_agent.application.retrieval import LearningMaterialRetrieval
from study_agent.config import Settings
from study_agent.domain.errors import DomainError
from study_agent.infrastructure.tutoring import TutorRepository
from study_agent.infrastructure.tutoring_models import (
    TutorConversationModel,
    TutorMessageModel,
    TutorTurnModel,
)
from study_agent.llm.provider_errors import tutoring_request_rejection


def request_digest(content: str, intent: str) -> str:
    return hashlib.sha256(
        json.dumps(
            {"content": content, "intent": intent},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def effective_intent(content: str, supplied: str, anchored: bool) -> str:
    # Deterministic escalation only; client labels never grant permissions or release scope.
    if re.search(r"错题|答错|最近.*错", content):
        return "mistakes"
    if re.search(r"薄弱|掌握|正确率|学习进度|复习.*(计划|顺序|建议)|我的.*(学习|弱点)", content):
        return "progress"
    if anchored and supplied not in {"progress", "mistakes"}:
        return "answered_question"
    if supplied == "general" and not re.fullmatch(
        r"[\s!！?？。，]*(你好|您好|嗨|hello|hi|谢谢|你能做什么)[\s!！?？。，]*", content, re.I
    ):
        return "materials"
    return supplied


class TutorService:
    def __init__(
        self,
        repository: TutorRepository,
        queries: LearningQueries,
        retrieval: LearningMaterialRetrieval,
        settings: Settings,
        checkpointer: BaseCheckpointSaver[Any] | None,
        model_factory: Callable[[], BaseChatModel],
    ) -> None:
        self.repository, self.queries, self.retrieval = repository, queries, retrieval
        self.settings, self.checkpointer, self.model_factory = settings, checkpointer, model_factory

    def available(self) -> None:
        if not self.settings.tutor_enabled:
            raise DomainError("TUTOR_DISABLED", "辅导功能已关闭", status_code=503)
        if self.checkpointer is None:
            raise DomainError(
                "TUTOR_CHECKPOINT_UNAVAILABLE",
                "持久化检查点不可用，请初始化辅导存储",
                status_code=503,
            )

    def new_agent(self, budget: RunBudget) -> CompiledStateGraph[Any, Any, Any, Any]:
        self.available()
        try:
            model = self.model_factory()
            # Fail closed for models without bind_tools. Real combination compatibility is
            # exercised by the actual graph; no second agent or text-only fallback is used.
            model.bind_tools([])
            assert self.checkpointer is not None
            return create_tutor_agent(
                model, self.queries, self.retrieval, budget, self.checkpointer
            )
        except DomainError:
            raise
        except Exception as exc:
            raise DomainError(
                "TUTOR_MODEL_UNSUPPORTED", "模型未配置或不支持辅导工具调用", status_code=503
            ) from exc

    def budget(self) -> RunBudget:
        return RunBudget(
            time.monotonic() + self.settings.tutor_timeout_seconds,
            max_tool_calls=self.settings.tutor_max_tool_calls,
            max_result_chars=self.settings.tutor_max_tool_result_chars,
        )

    async def create(self, payload: CreateTutorConversation) -> TutorConversationModel:
        self.available()
        await self.queries.check_scope(payload.knowledge_base_id)
        if payload.answered_question_id:
            await self.queries.answered_question(
                payload.knowledge_base_id, payload.study_session_id, payload.answered_question_id
            )
        agent = self.new_agent(self.budget())
        thread_id = f"tutor:{uuid4()}"
        try:
            config = await agent.aupdate_state(
                {"configurable": {"thread_id": thread_id}},
                {"messages": [], "evidence": {}, "evidence_flags": [], "turn_id": "initial"},
                as_node="model",
            )
            checkpoint_id = config["configurable"]["checkpoint_id"]
        except Exception as exc:
            raise DomainError(
                "TUTOR_CHECKPOINT_UNAVAILABLE", "无法初始化可恢复辅导会话", status_code=503
            ) from exc
        return await self.repository.create(
            payload.knowledge_base_id,
            payload.study_session_id,
            payload.answered_question_id,
            checkpoint_id,
            thread_id,
        )

    def response_for(self, turn: TutorTurnModel | None, replay: bool = False) -> dict[str, Any]:
        if turn is None:
            raise DomainError("TUTOR_TURN_NOT_FOUND", "辅导轮次不存在", status_code=404)
        if turn.response:
            return {**turn.response, "idempotent_replay": replay}
        return {
            "turn_id": str(turn.id),
            "status": turn.status,
            "message": None,
            "mode": None,
            "answer_status": None,
            "citations": [],
            "suggestions": [],
            "suggested_questions": [],
            "usage": turn.usage
            or {"known": False, "total_tokens": None, "model_calls": None, "tool_calls": None},
            "idempotent_replay": replay,
            "error_code": turn.error_code,
            "error_message": turn.error_message,
        }

    def ensure_hash(self, turn: TutorTurnModel, digest: str) -> None:
        if turn.request_hash != digest:
            raise DomainError(
                "TUTOR_MESSAGE_CONFLICT", "同一消息 ID 已用于不同请求", status_code=409
            )

    async def final_response(
        self,
        conversation: TutorConversationModel,
        turn: TutorTurnModel,
        state: dict[str, Any],
        usage: dict[str, Any],
    ) -> dict[str, Any]:
        await self.queries.check_scope(conversation.knowledge_base_id)
        if conversation.answered_question_id:
            await self.queries.answered_question(
                conversation.knowledge_base_id,
                conversation.study_session_id,
                conversation.answered_question_id,
            )
        draft = state.get("structured_response")
        if not isinstance(draft, TutorAnswerDraft):
            draft = TutorAnswerDraft.model_validate(draft)
        intent = effective_intent(
            turn.content, turn.intent, bool(conversation.answered_question_id)
        )
        citations = validate_draft(draft, state, intent, bool(conversation.answered_question_id))
        for evidence in citations:
            if not await self.retrieval.revalidate(conversation.knowledge_base_id, evidence):
                raise DomainError(
                    "TUTOR_STALE_CITATION", "引用资料已删除或重新解析，请重新提问", status_code=409
                )
        return {
            "turn_id": str(turn.id),
            "status": "completed",
            "message": draft.answer,
            "mode": "agent",
            "answer_status": draft.status,
            "citations": citations,
            "suggestions": draft.study_suggestions,
            "suggested_questions": draft.suggested_questions,
            "usage": usage,
            "idempotent_replay": False,
            "error_code": None,
            "error_message": None,
        }

    async def recover_locked(
        self, conversation: TutorConversationModel, turn: TutorTurnModel
    ) -> None:
        """Called only with the exclusive session lock: no executor still owns this turn."""
        budget = self.budget()
        try:
            agent = self.new_agent(budget)
            snapshot = await agent.aget_state(
                {"configurable": {"thread_id": conversation.graph_thread_id}}
            )
            if (
                not snapshot.next
                and snapshot.values.get("turn_id") == str(turn.id)
                and snapshot.values.get("structured_response")
            ):
                response = await self.final_response(
                    conversation,
                    turn,
                    snapshot.values,
                    {
                        "known": False,
                        "total_tokens": None,
                        "model_calls": None,
                        "tool_calls": None,
                        "recovered": True,
                    },
                )
                await self.repository.complete(
                    conversation.id,
                    turn.id,
                    response,
                    snapshot.config["configurable"]["checkpoint_id"],
                    [*budget.trace, {"kind": "recovery", "validated": True}],
                )
                return
        except Exception:
            pass
        await self.repository.fail(
            turn.id,
            "TUTOR_INTERRUPTED",
            "上轮执行已中断，未提交的输出未加入对话；请显式重试",
            {"known": False, "total_tokens": None},
            [*budget.trace, {"kind": "recovery", "validated": False}],
        )

    async def submit(self, conversation_id: UUID, payload: SubmitTutorMessage) -> dict[str, Any]:
        self.available()
        conversation = await self.repository.conversation(conversation_id)
        digest = request_digest(payload.content, payload.intent)
        existing = await self.repository.turn(
            conversation_id, client_message_id=payload.client_message_id
        )
        if existing:
            self.ensure_hash(existing, digest)
            if existing.status not in {"pending", "running"}:
                return self.response_for(existing, replay=True)
        if conversation.status != "active":
            raise DomainError("TUTOR_CONVERSATION_ARCHIVED", "该辅导会话已归档", status_code=409)
        async with self.repository.execution_lock(conversation_id) as acquired:
            if not acquired:
                # The lock owner can be between acquisition and its short reserve
                # transaction. Give its idempotency row time to become visible;
                # these reads never execute a graph or reserve a second turn.
                for delay in (0.0, 0.02, 0.05, 0.1, 0.2, 0.4):
                    if delay:
                        await asyncio.sleep(delay)
                    existing = await self.repository.turn(
                        conversation_id, client_message_id=payload.client_message_id
                    )
                    if existing:
                        self.ensure_hash(existing, digest)
                        return self.response_for(existing, replay=True)
                raise DomainError("TUTOR_THREAD_BUSY", "会话正在处理另一条问题", status_code=409)
            conversation = await self.repository.conversation(conversation_id)
            if conversation.status != "active":
                raise DomainError(
                    "TUTOR_CONVERSATION_ARCHIVED", "该辅导会话已归档", status_code=409
                )
            existing = await self.repository.turn(
                conversation_id, client_message_id=payload.client_message_id
            )
            if existing:
                self.ensure_hash(existing, digest)
                if existing.status in {"pending", "running"}:
                    await self.recover_locked(conversation, existing)
                return self.response_for(
                    await self.repository.turn(conversation_id, turn_id=existing.id), replay=True
                )
            orphan = await self.repository.running_turn(conversation_id)
            if orphan:
                await self.recover_locked(conversation, orphan)
                conversation = await self.repository.conversation(conversation_id)
            if (
                conversation.graph_version != TUTOR_GRAPH_VERSION
                or not conversation.last_committed_checkpoint_id
            ):
                raise DomainError(
                    "TUTOR_CONTEXT_UNAVAILABLE", "辅导图版本不兼容，请新建会话", status_code=409
                )
            await self.queries.check_scope(conversation.knowledge_base_id)
            budget = self.budget()
            agent = self.new_agent(budget)
            turn = await self.repository.reserve(
                conversation_id,
                payload.client_message_id,
                payload.content,
                payload.intent,
                digest,
                self.settings.tutor_timeout_seconds,
                self.settings.tutor_llm_model or self.settings.llm_model,
            )
            try:
                history = await self.repository.committed_history(
                    conversation_id, self.settings.tutor_max_messages
                )
                messages = [
                    (HumanMessage if m.role == "user" else AIMessage)(content=m.content)
                    for m in history
                ]
                messages.append(HumanMessage(content=payload.content))
                intent = effective_intent(
                    payload.content, payload.intent, bool(conversation.answered_question_id)
                )
                context = TutorContext(
                    conversation.id,
                    turn.id,
                    conversation.knowledge_base_id,
                    conversation.study_session_id,
                    conversation.answered_question_id,
                    intent=intent,
                )
                config: RunnableConfig = {
                    "configurable": {
                        "thread_id": conversation.graph_thread_id,
                        "checkpoint_id": conversation.last_committed_checkpoint_id,
                    },
                    "recursion_limit": 32,
                }
                async with asyncio.timeout(self.settings.tutor_timeout_seconds):
                    state = await agent.ainvoke(
                        {
                            "messages": Overwrite(messages),
                            "evidence": Overwrite({}),
                            "evidence_flags": Overwrite([]),
                            "structured_response": None,
                            "turn_id": str(turn.id),
                        },
                        config,
                        context=context,
                    )
                    response = await self.final_response(conversation, turn, state, budget.usage())
                    snapshot = await agent.aget_state(
                        {"configurable": {"thread_id": conversation.graph_thread_id}}
                    )
                    await self.repository.complete(
                        conversation_id,
                        turn.id,
                        response,
                        snapshot.config["configurable"]["checkpoint_id"],
                        budget.trace,
                    )
                return response
            except asyncio.CancelledError:
                await asyncio.shield(
                    self.repository.fail(
                        turn.id,
                        "TUTOR_CANCELLED",
                        "辅导执行已取消，请显式重试",
                        budget.usage(),
                        budget.trace,
                        status="cancelled",
                    )
                )
                raise
            except Exception as exc:
                if isinstance(exc, DomainError):
                    code, message = exc.code, exc.message
                elif isinstance(
                    exc,
                    (ModelCallLimitExceededError, ToolCallLimitExceededError, GraphRecursionError),
                ):
                    code, message = "TUTOR_BUDGET_EXCEEDED", "辅导模型或工具调用预算耗尽"
                elif isinstance(exc, TimeoutError):
                    code, message = "TUTOR_TIMEOUT", "辅导执行超时，请显式重试"
                elif isinstance(exc, BadRequestError):
                    code, message = tutoring_request_rejection(exc)
                elif isinstance(exc, NotImplementedError):
                    code, message = "TUTOR_MODEL_UNSUPPORTED", "模型不支持辅导工具与结构化输出组合"
                else:
                    code, message = "TUTOR_EXECUTION_FAILED", "辅导执行失败，未提交的回复未加入对话"
                await self.repository.fail(turn.id, code, message, budget.usage(), budget.trace)
                return self.response_for(
                    await self.repository.turn(conversation_id, turn_id=turn.id)
                )

    async def detail(
        self, conversation_id: UUID, page: int, page_size: int
    ) -> tuple[TutorConversationModel, Sequence[TutorMessageModel], int]:
        conversation = await self.repository.conversation(conversation_id)
        messages, total = await self.repository.messages(conversation_id, page, page_size)
        for message in messages:
            message.citations = [
                {**e, "valid": await self.retrieval.revalidate(conversation.knowledge_base_id, e)}
                for e in message.citations
            ]
        return conversation, messages, total

    async def turn_status(self, conversation_id: UUID, turn_id: UUID) -> dict[str, Any]:
        conversation = await self.repository.conversation(conversation_id)
        turn = await self.repository.turn(conversation_id, turn_id=turn_id)
        if not turn:
            raise DomainError("TUTOR_TURN_NOT_FOUND", "辅导轮次不存在", status_code=404)
        if turn.status in {"pending", "running"}:
            async with self.repository.execution_lock(conversation_id) as acquired:
                if acquired:
                    await self.recover_locked(conversation, turn)
                    turn = await self.repository.turn(conversation_id, turn_id=turn_id)
        if turn is None:
            raise DomainError("TUTOR_TURN_NOT_FOUND", "辅导轮次不存在", status_code=404)
        return {
            "id": str(turn.id),
            "status": turn.status,
            "client_message_id": str(turn.client_message_id),
            "response": self.response_for(turn),
            "error_code": turn.error_code,
            "error_message": turn.error_message,
        }

    async def archive(self, conversation_id: UUID) -> TutorConversationModel:
        conversation = await self.repository.conversation(conversation_id)
        async with self.repository.execution_lock(conversation_id) as acquired:
            if not acquired:
                raise DomainError("TUTOR_THREAD_BUSY", "会话运行中，暂不能归档", status_code=409)
            conversation = await self.repository.conversation(conversation_id)
            orphan = await self.repository.running_turn(conversation_id)
            if orphan:
                await self.recover_locked(conversation, orphan)
            return await self.repository.archive(conversation_id)

    async def rename(self, conversation_id: UUID, title: str) -> TutorConversationModel:
        async with self.repository.execution_lock(conversation_id) as acquired:
            if not acquired:
                raise DomainError("TUTOR_THREAD_BUSY", "会话运行中，暂不能重命名", status_code=409)
            await self.repository.conversation(conversation_id)
            return await self.repository.rename(conversation_id, title)

    async def delete(self, conversation_id: UUID) -> None:
        async with self.repository.execution_lock(conversation_id) as acquired:
            if not acquired:
                raise DomainError("TUTOR_THREAD_BUSY", "会话运行中，暂不能删除", status_code=409)
            await self.repository.conversation(conversation_id, include_deleted=True)
            orphan = await self.repository.running_turn(conversation_id)
            if orphan:
                # Deletion never resumes an abandoned graph or makes a model request.
                await self.repository.fail(
                    orphan.id,
                    "TUTOR_CONVERSATION_DELETED",
                    "辅导会话已删除",
                    orphan.usage or {"known": False, "total_tokens": None},
                    orphan.trace or [],
                    status="cancelled",
                )
            await self.repository.delete(conversation_id)
