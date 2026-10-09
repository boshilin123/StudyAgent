"""教学简化实验：节点、条件边、reducer、interrupt 和同线程恢复。

仅使用固定资料和 InMemorySaver；不接入产品路由，不调用模型或写业务库。
"""

import json
import operator
from typing import Annotated, Literal, TypedDict
from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt


class ReviewState(TypedDict, total=False):
    topic: str
    evidence: str
    answer: str
    status: str
    trace: Annotated[list[str], operator.add]


def retrieve(state: ReviewState) -> ReviewState:
    evidence = "TCP 用三次握手建立连接。" if state["topic"] == "TCP" else ""
    return {"evidence": evidence, "trace": ["retrieve"]}


def route(state: ReviewState) -> Literal["draft", "missing"]:
    return "draft" if state["evidence"] else "missing"


def draft(state: ReviewState) -> ReviewState:
    return {"answer": state["evidence"], "trace": ["draft"]}


def review(state: ReviewState) -> ReviewState:
    # 恢复时整个节点会再次执行，因此 interrupt 前不进行写库等副作用。
    approved = interrupt({"answer": state["answer"], "evidence": state["evidence"]})
    if not isinstance(approved, bool):
        raise ValueError("审核结果必须是 bool")
    return {"status": "accepted" if approved else "rejected", "trace": ["review"]}


def missing(state: ReviewState) -> ReviewState:
    return {
        "answer": "当前固定资料没有依据。",
        "status": "insufficient_evidence",
        "trace": ["missing"],
    }


def run_demo() -> dict[str, object]:
    builder = StateGraph(ReviewState)
    for name, node in [
        ("retrieve", retrieve),
        ("draft", draft),
        ("review", review),
        ("missing", missing),
    ]:
        builder.add_node(name, node)
    builder.add_edge(START, "retrieve")
    builder.add_conditional_edges("retrieve", route)
    builder.add_edge("draft", "review")
    builder.add_edge("review", END)
    builder.add_edge("missing", END)
    graph = builder.compile(checkpointer=InMemorySaver())
    results = []
    for approved in [True, False]:
        config = {"configurable": {"thread_id": str(uuid4())}}
        paused = graph.invoke({"topic": "TCP", "trace": []}, config)
        assert paused["__interrupt__"]
        assert graph.get_state(config).next == ("review",)
        # 恢复需同一 thread_id、兼容图结构及可访问原检查点的保存后端。
        resumed = graph.invoke(Command(resume=approved), config)
        expected = "accepted" if approved else "rejected"
        assert resumed["status"] == expected
        assert resumed["trace"] == ["retrieve", "draft", "review"]
        results.append(
            {
                "decision": approved,
                "status": resumed["status"],
                "trace": resumed["trace"],
                "paused_at": "review",
            }
        )
    no_evidence = graph.invoke(
        {"topic": "量子纠缠", "trace": []},
        {"configurable": {"thread_id": str(uuid4())}},
    )
    assert no_evidence["status"] == "insufficient_evidence"
    assert no_evidence["trace"] == ["retrieve", "missing"]
    return {
        "evidence_kind": "real LangGraph + fixed fixture + InMemorySaver",
        "review_cases": results,
        "missing_case": dict(no_evidence),
    }


if __name__ == "__main__":
    print(json.dumps(run_demo(), ensure_ascii=False, indent=2))
