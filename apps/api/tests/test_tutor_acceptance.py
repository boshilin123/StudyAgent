"""Independent deterministic acceptance: real create_agent, scripted model, no provider claim."""

import json
import time
from typing import Any
from uuid import uuid4

import pytest
from langchain.agents.middleware.model_call_limit import ModelCallLimitExceededError
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import Field

from study_agent.agents.tutor.agent import create_tutor_agent
from study_agent.agents.tutor.context import TutorContext
from study_agent.agents.tutor.middleware import RunBudget
from study_agent.agents.tutor.schemas import TutorAnswerDraft
from study_agent.agents.tutor.tools import MistakesInput, NoInput, SearchInput
from study_agent.agents.tutor.validation import validate_draft
from study_agent.application.tutoring import TutorService
from study_agent.config import Settings
from study_agent.domain.errors import DomainError


def call(name: str, args: dict[str, Any], index: int = 0) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": name,
                "args": args,
                "id": f"call-{index}",
                "type": "tool_call",
            }
        ],
    )


def final(status: str = "answered", citations: list[str] | None = None) -> AIMessage:
    return call(
        "TutorAnswerDraft",
        {
            "status": status,
            "answer": "这是解释性回答。",
            "citation_ids": citations or [],
            "suggested_questions": [],
            "study_suggestions": [],
        },
        100,
    )


class SequenceModel(BaseChatModel):
    responses: list[AIMessage] = Field(default_factory=list)
    calls: list[Any] = Field(default_factory=list)

    @property
    def _llm_type(self):
        return "acceptance-scripted-model"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls.append(list(messages))
        message = self.responses[min(len(self.calls) - 1, len(self.responses) - 1)].model_copy(
            deep=True
        )
        message.id = None
        for item in message.tool_calls:
            item["id"] = f"call-{len(self.calls) - 1}"
        return ChatResult(generations=[ChatGeneration(message=message)])


class ReadQueries:
    def __init__(self, no_history=False):
        self.scopes = []
        self.reads = []
        self.no_history = no_history

    async def check_scope(self, kb):
        self.scopes.append(kb)

    async def progress(self, kb):
        self.reads.append(("progress", kb))
        return {
            "code": "NO_LEARNING_HISTORY" if self.no_history else "OK",
            "answered_count": 0 if self.no_history else 4,
        }

    async def answered_question(self, kb, session, question):
        self.reads.append(("answered_question", kb))
        return {"code": "OK", "user_answer": ["B"], "verdict": "incorrect", "evidence": []}

    async def recent_mistakes(self, kb, limit):
        self.reads.append(("mistakes", kb, limit))
        return {"code": "OK", "items": []}


class ReadRetrieval:
    def __init__(self, empty=False):
        self.calls = []
        self.empty = empty

    async def search(self, kb, query, top_k):
        self.calls.append((kb, query, top_k))
        return (
            []
            if self.empty
            else [
                {
                    "evidence_id": "E1",
                    "material_id": str(uuid4()),
                    "chunk_id": str(uuid4()),
                    "content_hash": "hash",
                    "title": "TCP资料",
                    "quote": "三次握手",
                    "valid": True,
                }
            ]
        )


async def run_graph(responses, *, no_history=False, empty=False, max_tool_calls=6):
    model = SequenceModel(responses=responses)
    queries = ReadQueries(no_history)
    retrieval = ReadRetrieval(empty)
    budget = RunBudget(time.monotonic() + 15, max_tool_calls=max_tool_calls)
    graph = create_tutor_agent(model, queries, retrieval, budget, InMemorySaver())
    context = TutorContext(uuid4(), uuid4(), uuid4())
    state = await graph.ainvoke(
        {
            "messages": [HumanMessage(content="验收问题")],
            "evidence": {},
            "evidence_flags": [],
            "turn_id": str(context.turn_id),
        },
        {"configurable": {"thread_id": str(uuid4())}},
        context=context,
    )
    return state, model, queries, retrieval, budget, context


@pytest.mark.parametrize(
    "schema,args",
    [
        (SearchInput, {"query": "x", "knowledge_base_id": "B"}),
        (SearchInput, {"query": "x", "sql": "DELETE FROM materials"}),
        (SearchInput, {"query": "x", "url": "https://example.com"}),
        (SearchInput, {"query": ""}),
        (SearchInput, {"query": "x", "top_k": 6}),
        (SearchInput, {"query": "x" * 1001}),
        (MistakesInput, {"limit": 0}),
        (MistakesInput, {"limit": 11}),
        (NoInput, {"question_id": str(uuid4())}),
    ],
)
def test_t03_parameter_schemas_fail_closed(schema, args):
    with pytest.raises(ValueError):
        schema.model_validate(args)


async def test_a01_actual_tool_loop_and_server_scope():
    state, model, queries, retrieval, budget, context = await run_graph(
        [
            call("search_learning_materials", {"query": "TCP", "top_k": 1}),
            final(citations=["E1"]),
        ]
    )
    assert retrieval.calls == [(context.knowledge_base_id, "TCP", 1)]
    assert queries.scopes == [context.knowledge_base_id]
    assert isinstance(model.calls[1][-1], ToolMessage)
    assert model.calls[1][-1].tool_call_id == "call-0"
    assert json.loads(model.calls[1][-1].content)["evidence"][0]["evidence_id"] == "E1"
    assert (
        validate_draft(state["structured_response"], state, "materials", False)[0]["title"]
        == "TCP资料"
    )
    assert (budget.model_calls, budget.tool_calls, budget.searches) == (2, 1, 1)
    assert budget.usage()["total_tokens"] is None


async def test_a03_progress_and_recent_mistakes_are_actual_reads():
    state, model, queries, _, budget, context = await run_graph(
        [
            call("get_learning_progress", {}),
            call("list_recent_mistakes", {"limit": 3}, 1),
            final(),
        ]
    )
    assert queries.reads == [
        ("progress", context.knowledge_base_id),
        ("mistakes", context.knowledge_base_id, 3),
    ]
    assert validate_draft(state["structured_response"], state, "mistakes", False) == []
    assert budget.model_calls == 3 and budget.tool_calls == 2
    assert sum(isinstance(message, ToolMessage) for message in model.calls[-1]) == 2


async def test_a04_general_zero_tool_loop():
    state, _, queries, retrieval, budget, _ = await run_graph([final("needs_clarification")])
    assert validate_draft(state["structured_response"], state, "general", False) == []
    assert queries.reads == [] and retrieval.calls == []
    assert budget.model_calls == 1 and budget.tool_calls == 0


async def test_t08_no_history_cannot_be_personalized_diagnosis():
    state, _, _, _, _, _ = await run_graph(
        [call("get_learning_progress", {}), final()], no_history=True
    )
    with pytest.raises(DomainError) as caught:
        validate_draft(state["structured_response"], state, "progress", False)
    assert caught.value.code == "TUTOR_NO_LEARNING_HISTORY"


@pytest.mark.parametrize(
    "intent,anchored", [("progress", False), ("mistakes", False), ("answered_question", True)]
)
def test_a02_a03_missing_current_fact_reads(intent, anchored):
    with pytest.raises(DomainError) as caught:
        validate_draft(TutorAnswerDraft(status="answered", answer="虚构数据"), {}, intent, anchored)
    assert caught.value.code == "TUTOR_REQUIRED_TOOL_MISSING"


@pytest.mark.parametrize("citation", ["forged", "KB-B", "previous-turn"])
def test_a07_fabricated_citations_are_rejected(citation):
    with pytest.raises(DomainError) as caught:
        validate_draft(
            TutorAnswerDraft(status="answered", answer="错误引用", citation_ids=[citation]),
            {"evidence": {}, "evidence_flags": ["materials"]},
            "materials",
            False,
        )
    assert caught.value.code == "TUTOR_INVALID_CITATION"


async def test_a06_empty_search_rewrite_returns_insufficient():
    state, _, _, retrieval, budget, _ = await run_graph(
        [
            call("search_learning_materials", {"query": "TCP"}),
            call("search_learning_materials", {"query": "握手步骤"}, 1),
            final("insufficient_evidence"),
        ],
        empty=True,
    )
    assert validate_draft(state["structured_response"], state, "materials", False) == []
    assert len(retrieval.calls) == 2 and budget.searches == 2


async def test_a09_repeated_search_counts_but_reuses_current_result():
    state, _, _, retrieval, budget, _ = await run_graph(
        [
            call("search_learning_materials", {"query": " TCP "}),
            call("search_learning_materials", {"query": "tcp"}, 1),
            final(citations=["E1"]),
        ]
    )
    assert len(retrieval.calls) == 1
    assert budget.tool_calls == 2 and budget.searches == 2
    assert state["evidence_flags"] == ["materials"]


@pytest.mark.parametrize(
    "responses",
    [
        [call("delete_material", {"id": "x"})],
        [call("search_learning_materials", {"query": "x", "sql": "SELECT 1"})],
        [call("get_learning_progress", {})] * 7,
        [call("search_learning_materials", {"query": "x"})] * 3,
    ],
)
async def test_a05_a09_unknown_injected_or_unbounded_calls_stop(responses):
    with pytest.raises((DomainError, ModelCallLimitExceededError)) as caught:
        await run_graph(responses)
    if isinstance(caught.value, DomainError):
        assert caught.value.code in {
            "TUTOR_TOOL_NOT_ALLOWED",
            "TUTOR_TOOL_ARGUMENT_INVALID",
            "TUTOR_BUDGET_EXCEEDED",
        }


async def test_r09_disabled_and_missing_checkpoint_fail_before_model():
    factory_calls = []

    def model_factory():
        factory_calls.append(True)
        raise AssertionError("model should not initialize")

    for enabled, expected in [(False, "TUTOR_DISABLED"), (True, "TUTOR_CHECKPOINT_UNAVAILABLE")]:
        service = TutorService(
            None, None, None, Settings(_env_file=None, tutor_enabled=enabled), None, model_factory
        )
        with pytest.raises(DomainError) as caught:
            service.available()
        assert caught.value.code == expected
    assert factory_calls == []


def test_a09_deadline_and_token_limit_are_enforced():
    for budget, code in [
        (RunBudget(time.monotonic() - 1), "TUTOR_TIMEOUT"),
        (RunBudget(time.monotonic() + 10, total_tokens=12000), "TUTOR_BUDGET_EXCEEDED"),
    ]:
        with pytest.raises(DomainError) as caught:
            budget.check()
        assert caught.value.code == code
