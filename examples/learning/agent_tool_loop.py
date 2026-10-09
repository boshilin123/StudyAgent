"""完整可运行实验：生产 create_tutor_agent + 脚本化模型 + 固定只读工具。

模拟模型仅用于观察 Model → ToolMessage → Model，不证明真实模型质量。
"""

import asyncio
import json
import time
from typing import Any
from uuid import UUID, uuid4

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import Field

from study_agent.agents.tutor.agent import create_tutor_agent
from study_agent.agents.tutor.context import TutorContext
from study_agent.agents.tutor.middleware import RunBudget
from study_agent.agents.tutor.validation import validate_draft


class ScriptedModel(BaseChatModel):
    calls: list[Any] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "learning-scripted-model"

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        return self

    def _generate(
        self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> ChatResult:
        self.calls.append(messages)
        if isinstance(messages[-1], ToolMessage):
            evidence = json.loads(messages[-1].content).get("evidence", [])
            name = "TutorAnswerDraft"
            args = {
                "status": "answered" if evidence else "insufficient_evidence",
                "answer": evidence[0]["quote"] if evidence else "当前资料没有依据。",
                "citation_ids": [e["evidence_id"] for e in evidence],
                "suggested_questions": [],
                "study_suggestions": [],
            }
        else:
            name, args = "search_learning_materials", {"query": "TCP 三次握手", "top_k": 1}
        message = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": name,
                    "args": args,
                    "id": f"call-{len(self.calls)}",
                    "type": "tool_call",
                }
            ],
        )
        return ChatResult(generations=[ChatGeneration(message=message)])


class ScopedQueries:
    def __init__(self, knowledge_base_id: UUID):
        self.knowledge_base_id = knowledge_base_id

    async def check_scope(self, knowledge_base_id: UUID) -> None:
        assert knowledge_base_id == self.knowledge_base_id


class FixedRetrieval:
    def __init__(self, knowledge_base_id: UUID, empty: bool):
        self.knowledge_base_id, self.empty = knowledge_base_id, empty

    async def search(self, knowledge_base_id: UUID, query: str, top_k: int) -> list[dict[str, Any]]:
        assert knowledge_base_id == self.knowledge_base_id
        return (
            []
            if self.empty
            else [
                {
                    "evidence_id": "fixture:tcp:1",
                    "material_id": str(UUID(int=2)),
                    "chunk_id": str(UUID(int=3)),
                    "title": "TCP 固定教学资料",
                    "quote": "TCP 用三次握手建立连接。",
                    "content_hash": "fixture-hash",
                    "valid": True,
                }
            ]
        )


async def run_demo() -> dict[str, object]:
    cases = []
    for empty in [False, True]:
        kb = UUID(int=1)
        model = ScriptedModel()
        budget = RunBudget(time.monotonic() + 15)
        graph = create_tutor_agent(
            model, ScopedQueries(kb), FixedRetrieval(kb, empty), budget, InMemorySaver()
        )
        context = TutorContext(uuid4(), uuid4(), kb)
        result = await graph.ainvoke(
            {
                "messages": [HumanMessage(content="TCP 三次握手是什么？")],
                "turn_id": str(context.turn_id),
                "evidence": {},
                "evidence_flags": [],
            },
            {"configurable": {"thread_id": str(uuid4())}},
            context=context,
        )
        citations = validate_draft(result["structured_response"], result, "materials", False)
        assert budget.model_calls == 2 and budget.tool_calls == 1
        assert isinstance(model.calls[1][-1], ToolMessage)
        assert model.calls[1][-1].tool_call_id == "call-1"
        assert bool(citations) == (not empty)
        draft = result["structured_response"]
        expected = "insufficient_evidence" if empty else "answered"
        assert draft.status == expected
        cases.append(
            {
                "empty_retrieval": empty,
                "status": draft.status,
                "answer": draft.answer,
                "citation_ids": draft.citation_ids,
                "flags": result["evidence_flags"],
                "usage": budget.usage(),
                "tool_message_call_id": "call-1",
            }
        )
    return {
        "evidence_kind": "production Agent graph + scripted model + fixed tool fixtures",
        "cases": cases,
    }


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run_demo()), ensure_ascii=False, indent=2))
