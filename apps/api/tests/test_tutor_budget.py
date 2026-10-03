"""Exercise framework calls, budgets and checkpoint branching with deterministic models."""

import asyncio
import json
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from langchain.agents.middleware.model_call_limit import ModelCallLimitExceededError
from langchain.agents.middleware.types import ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command, Overwrite
from pydantic import Field

from study_agent.agents.tutor import middleware as tutor_middleware
from study_agent.agents.tutor.agent import create_tutor_agent
from study_agent.agents.tutor.context import TutorContext
from study_agent.agents.tutor.middleware import RunBudget, TutorBudgetMiddleware, tool_result_chars
from study_agent.agents.tutor.validation import validate_draft
from study_agent.domain.errors import DomainError
from tests.test_tutor_agent import Queries, Retrieval, ScriptedTutorModel


class SequenceModel(ScriptedTutorModel):
    responses: list[AIMessage] = Field(default_factory=list)
    fail_provider: bool = False

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls.append(messages)
        if self.fail_provider:
            raise RuntimeError("private endpoint secret-token")
        message = self.responses[min(len(self.calls) - 1, len(self.responses) - 1)].model_copy(
            deep=True
        )
        message.id = None
        for call in message.tool_calls:
            call["id"] = f"{call['id']}-{len(self.calls)}"
        return ChatResult(generations=[ChatGeneration(message=message)])


def tool_call(name, args=None, call_id="call"):
    return {"name": name, "args": args or {}, "id": call_id, "type": "tool_call"}


async def run_graph(model, budget=None, queries=None, retrieval=None):
    budget = budget or RunBudget(time.monotonic() + 10)
    graph = create_tutor_agent(
        model, queries or Queries(), retrieval or Retrieval(), budget, InMemorySaver()
    )
    context = TutorContext(uuid4(), uuid4(), uuid4())
    state = await graph.ainvoke(
        {
            "messages": [HumanMessage(content="解释资料")],
            "evidence": {},
            "evidence_flags": [],
            "turn_id": str(context.turn_id),
        },
        {"configurable": {"thread_id": str(uuid4())}},
        context=context,
    )
    return state, budget


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name,args,code",
    [
        (
            "search_learning_materials",
            {"query": "x", "knowledge_base_id": "other"},
            "TUTOR_TOOL_ARGUMENT_INVALID",
        ),
        ("get_learning_progress", {"sql": "DROP DATABASE"}, "TUTOR_TOOL_ARGUMENT_INVALID"),
        ("list_recent_mistakes", {"limit": 11}, "TUTOR_TOOL_ARGUMENT_INVALID"),
        ("search_learning_materials", {"query": "x", "top_k": 0}, "TUTOR_TOOL_ARGUMENT_INVALID"),
    ],
)
async def test_model_cannot_add_scope_sql_or_unbounded_tool_arguments(name, args, code):
    model = SequenceModel(responses=[AIMessage(content="", tool_calls=[tool_call(name, args)])])
    with pytest.raises(DomainError) as error:
        await run_graph(model)
    assert error.value.code == code


@pytest.mark.asyncio
async def test_multiple_parallel_provider_calls_share_atomic_budget():
    calls = [
        tool_call(name, call_id=f"p-{i}")
        for i, name in enumerate(
            ["get_learning_progress", "get_answered_question_context", "list_recent_mistakes"]
        )
    ]
    model = SequenceModel(responses=[AIMessage(content="", tool_calls=calls)])
    budget = RunBudget(time.monotonic() + 10, max_tool_calls=2)
    with pytest.raises(DomainError) as error:
        await run_graph(model, budget)
    assert error.value.code == "TUTOR_BUDGET_EXCEEDED"
    assert budget.tool_calls == 2


@pytest.mark.asyncio
async def test_duplicate_searches_count_and_stop_after_two():
    model = SequenceModel(
        responses=[
            AIMessage(
                content="", tool_calls=[tool_call("search_learning_materials", {"query": "TCP"})]
            )
        ]
    )
    budget = RunBudget(time.monotonic() + 10)
    with pytest.raises(DomainError) as error:
        await run_graph(model, budget)
    assert error.value.code == "TUTOR_BUDGET_EXCEEDED"
    assert budget.searches == 2 and budget.tool_calls == 3


@pytest.mark.asyncio
async def test_structured_output_repairs_once_then_fails_counting_both_calls():
    invalid = AIMessage(
        content="",
        tool_calls=[tool_call("TutorAnswerDraft", {"status": "invented", "answer": "x"})],
    )
    model = SequenceModel(responses=[invalid])
    budget = RunBudget(time.monotonic() + 10)
    with pytest.raises(DomainError) as error:
        await run_graph(model, budget)
    assert error.value.code == "TUTOR_INVALID_OUTPUT"
    assert budget.model_calls == 2 and budget.tool_calls == 0


@pytest.mark.asyncio
async def test_provider_failure_marks_usage_unknown_instead_of_zero_cost():
    model = SequenceModel(fail_provider=True)
    budget = RunBudget(time.monotonic() + 10)
    with pytest.raises(RuntimeError):
        await run_graph(model, budget)
    assert budget.model_calls == 1
    assert budget.usage()["known"] is False and budget.usage()["total_tokens"] is None


class MandatoryReadsModel(ScriptedTutorModel):
    bindings: list = Field(default_factory=list)

    def bind_tools(self, tools, **kwargs):
        names = [getattr(t, "name", None) or t.get("function", t).get("name") for t in tools]
        self.bindings.append({"names": names, "choice": kwargs.get("tool_choice")})
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls.append(messages)
        names = self.bindings[-1]["names"]
        # Prefer to finalize immediately unless the framework restricts available tools.
        # This reproduces the real model's premature answer without scripted correct reads.
        if "TutorAnswerDraft" not in names:
            message = AIMessage(content="", tool_calls=[tool_call(names[0])])
        else:
            has_context = any(isinstance(m, ToolMessage) for m in messages)
            message = AIMessage(
                content="",
                tool_calls=[
                    tool_call(
                        "TutorAnswerDraft",
                        {
                            "status": "answered" if has_context else "needs_clarification",
                            "answer": "根据当前资料与学习记录给出解释。",
                            "citation_ids": ["bound-evidence"]
                            if any(
                                isinstance(m, ToolMessage) and '"bound-evidence"' in str(m.content)
                                for m in messages
                            )
                            else [],
                            "suggested_questions": [],
                            "study_suggestions": [],
                        },
                    )
                ],
            )
        return ChatResult(generations=[ChatGeneration(message=message)])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "intent,anchored,expected",
    [
        ("answered_question", True, ["get_answered_question_context"]),
        ("progress", False, ["get_learning_progress"]),
        ("mistakes", False, ["get_learning_progress", "list_recent_mistakes"]),
        (
            "mistakes",
            True,
            ["get_answered_question_context", "get_learning_progress", "list_recent_mistakes"],
        ),
        ("general", False, []),
    ],
)
async def test_server_required_reads_precede_finalization_and_restore_normal_tools(
    intent, anchored, expected
):
    class BoundQueries(Queries):
        async def answered_question(self, kb, session, question):
            return {
                "code": "OK",
                "evidence": [{"evidence_id": "bound-evidence", "quote": "真实已答题依据"}],
            }

    model = MandatoryReadsModel()
    budget = RunBudget(time.monotonic() + 10)
    graph = create_tutor_agent(model, BoundQueries(), Retrieval(), budget, InMemorySaver())
    context = TutorContext(
        uuid4(),
        uuid4(),
        uuid4(),
        study_session_id=uuid4() if anchored else None,
        answered_question_id=uuid4() if anchored else None,
        intent=intent,
    )
    state = await graph.ainvoke(
        {
            "messages": [HumanMessage(content="聚时的主要作用是什么")],
            "evidence": {},
            "evidence_flags": [],
            "turn_id": str(context.turn_id),
        },
        {"configurable": {"thread_id": str(uuid4())}},
        context=context,
    )
    assert [entry["names"] for entry in model.bindings[: len(expected)]] == [
        [name] for name in expected
    ]
    assert all(entry["choice"] == "any" for entry in model.bindings[: len(expected)])
    assert "TutorAnswerDraft" in model.bindings[-1]["names"]
    assert "search_learning_materials" in model.bindings[-1]["names"]
    assert budget.tool_calls == len(expected)
    assert budget.model_calls == len(expected) + 1
    validate_draft(state["structured_response"], state, intent, anchored)


@pytest.mark.asyncio
async def test_deadline_and_tool_result_budgets():
    budget = RunBudget(time.monotonic() - 1)
    with pytest.raises(DomainError) as error:
        await run_graph(ScriptedTutorModel(), budget)
    assert error.value.code == "TUTOR_TIMEOUT" and budget.model_calls == 0
    small = RunBudget(time.monotonic() + 10, max_result_chars=1)
    with pytest.raises(DomainError) as error:
        await run_graph(ScriptedTutorModel(), small)
    assert error.value.code == "TUTOR_BUDGET_EXCEEDED" and small.tool_calls == 1


@pytest.mark.asyncio
async def test_large_search_and_followup_count_only_model_messages_preserving_evidence():
    evidence = [
        {
            "evidence_id": f"e{i}",
            "material_id": str(uuid4()),
            "chunk_id": str(uuid4()),
            "title": "部署资料",
            "content_hash": "hash",
            "valid": True,
            "quote": "部署接口支持自动部署。\n" * 90,
        }
        for i in range(5)
    ]

    class LongRetrieval(Retrieval):
        async def search(self, kb, query, top_k):
            return evidence[:top_k]

    class AnswerQueries(Queries):
        async def answered_question(self, kb, session, question):
            return {
                "code": "OK",
                "stem": "部署接口的主要作用是什么？",
                "correct_answer": ["自动部署"],
                "evidence": evidence[:1],
            }

    final = AIMessage(
        content="",
        tool_calls=[
            tool_call(
                "TutorAnswerDraft",
                {
                    "status": "answered",
                    "answer": "根据资料，接口用于自动部署。",
                    "citation_ids": ["e0"],
                    "suggested_questions": [],
                    "study_suggestions": [],
                },
            )
        ],
    )
    model = SequenceModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    tool_call(
                        "search_learning_materials",
                        {
                            "query": "部署的主要作用",
                            "top_k": 5,
                        },
                    )
                ],
            ),
            AIMessage(content="", tool_calls=[tool_call("get_answered_question_context")]),
            final,
        ]
    )
    state, budget = await run_graph(model, queries=AnswerQueries(), retrieval=LongRetrieval())
    messages = [m for m in state["messages"] if isinstance(m, ToolMessage)]
    # ToolStrategy's final acknowledgement is not a business tool result.
    tool_messages = messages[:2]
    expected = sum(len(m.content) for m in tool_messages)
    old_size = sum(
        len(
            str(
                Command(
                    update={
                        "messages": [m],
                        "evidence_flags": ["materials"],
                        "evidence": {
                            e["evidence_id"]: e for e in json.loads(m.content)["evidence"]
                        },
                    }
                )
            )
        )
        for m in tool_messages
    )
    assert expected < 16000 < old_size
    assert budget.result_chars == expected
    assert budget.model_calls == 3 and budget.tool_calls == 2
    assert state["evidence"]["e0"]["quote"] == evidence[0]["quote"]
    assert (
        validate_draft(state["structured_response"], state, "answered_question", True)[0]
        == evidence[0]
    )
    tool_trace = [item for item in budget.trace if item["kind"] == "tool"]
    assert tool_trace[-1]["total_result_chars"] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("is_command", [False, True])
async def test_tool_result_budget_boundary_and_cumulative_limit(is_command):
    budget = RunBudget(time.monotonic() + 10, max_result_chars=100)
    wrapper = TutorBudgetMiddleware(budget)
    request = SimpleNamespace(tool_call=tool_call("get_learning_progress"))

    async def handler(request):
        message = ToolMessage(content="中" * 100, tool_call_id="budget-boundary")
        return (
            Command(update={"messages": [message], "evidence": {"internal": "x" * 5000}})
            if is_command
            else message
        )

    result = await wrapper.awrap_tool_call(request, handler)
    assert tool_result_chars(result) == budget.result_chars == 100
    with pytest.raises(DomainError) as error:
        await wrapper.awrap_tool_call(request, handler)
    assert error.value.code == "TUTOR_BUDGET_EXCEEDED"
    assert budget.result_chars == 200 and budget.tool_calls == 2


@pytest.mark.parametrize("update", [None, {"evidence": {}}, {"messages": ["untyped"]}])
def test_invalid_tool_command_fails_closed(update):
    with pytest.raises(DomainError) as error:
        tool_result_chars(Command(update=update))
    assert error.value.code == "TUTOR_TOOL_RESULT_INVALID"


def test_tool_message_content_blocks_exclude_internal_artifact():
    content = [{"type": "text", "text": "部署资料"}]
    result = ToolMessage(content=content, artifact={"ledger": "x" * 20000}, tool_call_id="blocks")
    assert tool_result_chars(result) == len(json.dumps(content, ensure_ascii=False))


@pytest.mark.asyncio
async def test_tool_timeout_is_enforced_before_graph_returns(monkeypatch):
    # Freeze only this middleware's deadline clock, not asyncio's event loop clock.
    # This isolates tool timeout from slower coverage/Windows model scheduling.
    monkeypatch.setattr(tutor_middleware, "time", SimpleNamespace(monotonic=lambda: 0.0))
    budget = RunBudget(0.02)
    wrapper = TutorBudgetMiddleware(budget)
    request = SimpleNamespace(tool_call=tool_call("get_learning_progress"))

    async def slow_handler(request):
        await asyncio.sleep(10)

    with pytest.raises(TimeoutError):
        await wrapper.awrap_tool_call(request, slow_handler)
    assert budget.tool_calls == 1


@pytest.mark.asyncio
async def test_next_turn_resets_evidence_and_budget_from_pinned_checkpoint():
    saver = InMemorySaver()
    first_model = ScriptedTutorModel()
    first_budget = RunBudget(time.monotonic() + 10)
    graph = create_tutor_agent(first_model, Queries(), Retrieval(), first_budget, saver)
    thread = {"configurable": {"thread_id": str(uuid4())}}
    context = TutorContext(uuid4(), uuid4(), uuid4())
    state = await graph.ainvoke(
        {
            "messages": [HumanMessage(content="第一次")],
            "evidence": {},
            "evidence_flags": [],
            "turn_id": str(context.turn_id),
        },
        thread,
        context=context,
    )
    accepted = (await graph.aget_state(thread)).config
    assert state["evidence"]["e1"]

    class EmptyRetrieval(Retrieval):
        async def search(self, kb, query, top_k):
            return []

    second_model = ScriptedTutorModel()
    second_budget = RunBudget(time.monotonic() + 10)
    graph = create_tutor_agent(second_model, Queries(), EmptyRetrieval(), second_budget, saver)
    state = await graph.ainvoke(
        {
            "messages": Overwrite(
                [
                    HumanMessage(content="第一次"),
                    AIMessage(content="已提交回复"),
                    HumanMessage(content="第二次"),
                ]
            ),
            "evidence": Overwrite({}),
            "evidence_flags": Overwrite([]),
            "turn_id": str(uuid4()),
        },
        accepted,
        context=context,
    )
    assert state["evidence"] == {}
    assert state["structured_response"].status == "insufficient_evidence"
    assert second_budget.model_calls == 2 and second_budget.tool_calls == 1
    assert validate_draft(state["structured_response"], state, "materials", False) == []


@pytest.mark.asyncio
async def test_failed_graph_branch_is_excluded_when_starting_from_accepted_pointer():
    saver = InMemorySaver()
    graph = create_tutor_agent(
        ScriptedTutorModel(fabricate=True),
        Queries(),
        Retrieval(),
        RunBudget(time.monotonic() + 10),
        saver,
    )
    thread = {"configurable": {"thread_id": str(uuid4())}}
    accepted = await graph.aupdate_state(
        thread,
        {"messages": [], "evidence": {}, "evidence_flags": [], "turn_id": "initial"},
        as_node="model",
    )
    context = TutorContext(uuid4(), uuid4(), uuid4())
    invalid = await graph.ainvoke(
        {"messages": [HumanMessage(content="failed-input")], "turn_id": str(uuid4())},
        accepted,
        context=context,
    )
    with pytest.raises(DomainError):
        validate_draft(invalid["structured_response"], invalid, "materials", False)
    model = ScriptedTutorModel()
    graph = create_tutor_agent(
        model, Queries(), Retrieval(), RunBudget(time.monotonic() + 10), saver
    )
    await graph.ainvoke(
        {
            "messages": Overwrite([HumanMessage(content="new-input")]),
            "evidence": Overwrite({}),
            "evidence_flags": Overwrite([]),
            "turn_id": str(uuid4()),
        },
        accepted,
        context=context,
    )
    assert all(m.content != "failed-input" for m in model.calls[0])


@pytest.mark.asyncio
async def test_previous_structured_draft_cannot_satisfy_next_turn():
    saver = InMemorySaver()
    graph = create_tutor_agent(
        ScriptedTutorModel(), Queries(), Retrieval(), RunBudget(time.monotonic() + 10), saver
    )
    thread = {"configurable": {"thread_id": str(uuid4())}}
    context = TutorContext(uuid4(), uuid4(), uuid4())
    await graph.ainvoke(
        {
            "messages": [HumanMessage(content="第一次")],
            "evidence": {},
            "evidence_flags": [],
            "structured_response": None,
            "turn_id": str(context.turn_id),
        },
        thread,
        context=context,
    )
    accepted = (await graph.aget_state(thread)).config
    second_model = SequenceModel(responses=[AIMessage(content="没有结构化输出")])
    graph = create_tutor_agent(
        second_model, Queries(), Retrieval(), RunBudget(time.monotonic() + 10), saver
    )
    try:
        state = await graph.ainvoke(
            {
                "messages": Overwrite([HumanMessage(content="第二次")]),
                "evidence": Overwrite({}),
                "evidence_flags": Overwrite([]),
                "structured_response": None,
                "turn_id": str(uuid4()),
            },
            accepted,
            context=context,
        )
        assert state.get("structured_response") is None
    except (DomainError, ModelCallLimitExceededError):
        # Some provider/framework combinations ask for structured output again;
        # the only acceptable outcome is absence of this turn's draft or bounded failure.
        state = (await graph.aget_state(thread)).values
        assert state.get("structured_response") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("has_usage", [True, False])
async def test_virtual_structured_tool_acknowledgement_does_not_erase_real_model_usage(has_usage):
    budget = RunBudget(time.monotonic() + 10)
    wrapper = TutorBudgetMiddleware(budget)
    request = SimpleNamespace(messages=[HumanMessage(content="依据资料回答")])
    usage = {"input_tokens": 5, "output_tokens": 3, "total_tokens": 8} if has_usage else None

    async def provider(request):
        return ModelResponse(
            result=[
                AIMessage(content="", usage_metadata=usage),
                ToolMessage(content="Returning structured response", tool_call_id="virtual-final"),
            ]
        )

    await wrapper.awrap_model_call(request, provider)
    assert budget.model_calls == 1
    assert budget.usage()["known"] is has_usage
    assert budget.usage()["total_tokens"] == (8 if has_usage else None)
