import json
import time
from uuid import uuid4

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Overwrite
from pydantic import Field

from study_agent.agents.tutor.agent import create_tutor_agent
from study_agent.agents.tutor.context import TutorContext
from study_agent.agents.tutor.middleware import RunBudget
from study_agent.agents.tutor.schemas import TutorAnswerDraft
from study_agent.agents.tutor.validation import validate_draft
from study_agent.api.tutoring_schemas import CreateTutorConversation, SubmitTutorMessage
from study_agent.application.tutoring import effective_intent, request_digest
from study_agent.domain.errors import DomainError
from study_agent.infrastructure.checkpointer import psycopg_connection_string


class ScriptedTutorModel(BaseChatModel):
    calls: list = Field(default_factory=list)
    business_tool: str = "search_learning_materials"
    business_args: dict = Field(default_factory=lambda: {"query": "三次握手", "top_k": 1})
    fabricate: bool = False

    @property
    def _llm_type(self):
        return "scripted-tutor"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls.append(messages)
        if not isinstance(messages[-1], ToolMessage):
            message = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": self.business_tool,
                        "args": self.business_args,
                        "id": f"tool-{len(self.calls)}",
                        "type": "tool_call",
                    }
                ],
            )
        else:
            result = json.loads(messages[-1].content)
            evidence = result.get("evidence", [])
            citation_ids = [e["evidence_id"] for e in evidence]
            message = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "TutorAnswerDraft",
                        "id": "final",
                        "type": "tool_call",
                        "args": {
                            "status": "answered"
                            if evidence or self.business_tool == "get_learning_progress"
                            else "insufficient_evidence",
                            "answer": "依据资料，TCP 使用三次握手建立连接。",
                            "citation_ids": ["forged"] if self.fabricate else citation_ids,
                            "suggested_questions": [],
                            "study_suggestions": [],
                        },
                    }
                ],
            )
        return ChatResult(generations=[ChatGeneration(message=message)])


class Queries:
    async def check_scope(self, kb):
        pass

    async def progress(self, kb):
        return {"code": "OK", "answered_count": 2}

    async def answered_question(self, kb, session, question):
        return {"code": "OK", "evidence": []}

    async def recent_mistakes(self, kb, limit):
        return {"code": "OK", "items": []}


class Retrieval:
    async def search(self, kb, query, top_k):
        return [
            {
                "evidence_id": "e1",
                "material_id": str(uuid4()),
                "chunk_id": str(uuid4()),
                "title": "TCP",
                "quote": "TCP 使用三次握手建立连接。",
                "content_hash": "hash",
                "valid": True,
            }
        ]


@pytest.mark.asyncio
async def test_real_create_agent_tool_runtime_command_and_structured_output():
    model = ScriptedTutorModel()
    budget = RunBudget(time.monotonic() + 10)
    graph = create_tutor_agent(model, Queries(), Retrieval(), budget, InMemorySaver())
    config = {"configurable": {"thread_id": str(uuid4())}}
    initial = await graph.aupdate_state(
        config,
        {"messages": [], "evidence": {}, "evidence_flags": [], "turn_id": "initial"},
        as_node="model",
    )
    ctx = TutorContext(uuid4(), uuid4(), uuid4())
    state = await graph.ainvoke(
        {
            "messages": Overwrite([HumanMessage(content="三次握手是什么？")]),
            "evidence": Overwrite({}),
            "evidence_flags": Overwrite([]),
            "turn_id": str(ctx.turn_id),
        },
        initial,
        context=ctx,
    )
    assert isinstance(state["structured_response"], TutorAnswerDraft)
    assert state["evidence_flags"] == ["materials"]
    assert (
        validate_draft(state["structured_response"], state, "materials", False)[0]["evidence_id"]
        == "e1"
    )
    assert len(model.calls) == 2
    assert isinstance(model.calls[1][-1], ToolMessage)
    assert model.calls[1][-1].tool_call_id == "tool-1"
    assert budget.model_calls == 2 and budget.tool_calls == 1
    assert budget.usage()["total_tokens"] is None


def test_citation_and_required_tool_validation():
    draft = TutorAnswerDraft(status="answered", answer="分析", citation_ids=["forged"])
    with pytest.raises(DomainError, match="未经取证"):
        validate_draft(draft, {"evidence": {}}, "materials", False)
    with pytest.raises(DomainError, match="必需"):
        validate_draft(TutorAnswerDraft(status="answered", answer="计划"), {}, "progress", False)


def test_server_intent_escalation_and_payload_schema():
    assert effective_intent("我的薄弱点", "general", False) == "progress"
    assert effective_intent("最近错题", "materials", False) == "mistakes"
    assert effective_intent("资料事实", "general", False) == "materials"
    assert effective_intent("你好", "general", False) == "general"
    assert effective_intent("任意问题", "progress", True) == "progress"
    assert effective_intent("任意问题", "materials", True) == "answered_question"
    with pytest.raises(ValueError):
        SubmitTutorMessage(client_message_id=uuid4(), content="x", thread_id="injected")
    with pytest.raises(ValueError):
        CreateTutorConversation(knowledge_base_id=uuid4(), answered_question_id=uuid4())
    assert request_digest("x", "materials") != request_digest("x", "general")
    assert (
        psycopg_connection_string("postgresql+asyncpg://u:p@localhost/db")
        == "postgresql://u:p@localhost/db"
    )
