"""Exercise framework calls, budgets and checkpoint branching with deterministic models."""

import asyncio
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from langchain.agents.middleware.model_call_limit import ModelCallLimitExceededError
from langchain.agents.middleware.types import ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Overwrite
from pydantic import Field

from study_agent.agents.tutor import middleware as tutor_middleware
from study_agent.agents.tutor.agent import create_tutor_agent
from study_agent.agents.tutor.context import TutorContext
from study_agent.agents.tutor.middleware import RunBudget, TutorBudgetMiddleware
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
