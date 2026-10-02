import json
from typing import Any

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool
from langgraph.types import Command
from pydantic import BaseModel, ConfigDict, Field

from study_agent.agents.tutor.context import TutorContext
from study_agent.application.learning_queries import LearningQueries
from study_agent.application.retrieval import LearningMaterialRetrieval


class SearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=5)


class MistakesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit: int = Field(default=5, ge=1, le=10)


class NoInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


def make_tutor_tools(
    queries: LearningQueries, retrieval: LearningMaterialRetrieval
) -> list[BaseTool]:
    cache: dict[tuple[str, int], list[dict[str, Any]]] = {}

    def feedback(
        runtime: ToolRuntime[TutorContext],
        result: dict[str, Any],
        flag: str,
        evidence: list[dict[str, Any]],
    ) -> Command[Any]:
        flags = [flag]
        if result.get("code") == "NO_LEARNING_HISTORY":
            flags.append("no_history")
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=json.dumps(result, ensure_ascii=False),
                        tool_call_id=runtime.tool_call_id,
                    )
                ],
                "evidence_flags": flags,
                "evidence": {e["evidence_id"]: e for e in evidence},
            }
        )

    @tool
    async def search_learning_materials(
        query: str, runtime: ToolRuntime[TutorContext], top_k: int = 5
    ) -> Command[Any]:
        """检索当前知识库有效资料；只引用返回的 evidence_id，无结果可改写一次。"""
        await queries.check_scope(runtime.context.knowledge_base_id)
        key = (" ".join(query.casefold().split()), top_k)
        if key not in cache:
            cache[key] = await retrieval.search(runtime.context.knowledge_base_id, query, top_k)
        evidence = cache[key]
        return feedback(
            runtime,
            {"code": "OK" if evidence else "NO_EVIDENCE", "evidence": evidence},
            "materials",
            evidence,
        )

    @tool
    async def get_answered_question_context(runtime: ToolRuntime[TutorContext]) -> Command[Any]:
        """读取服务器绑定的真实已作答题、用户答案、判分和有效题目来源。不能指定任意题目。"""
        ctx = runtime.context
        result = await queries.answered_question(
            ctx.knowledge_base_id, ctx.study_session_id, ctx.answered_question_id
        )
        return feedback(runtime, result, "answered_question", result.get("evidence", []))

    @tool
    async def get_learning_progress(runtime: ToolRuntime[TutorContext]) -> Command[Any]:
        """读取当前知识库最新答题数量、正确率、掌握度、弱点和到期复习摘要。"""
        result = await queries.progress(runtime.context.knowledge_base_id)
        return feedback(runtime, result, "progress", [])

    @tool
    async def list_recent_mistakes(
        runtime: ToolRuntime[TutorContext], limit: int = 5
    ) -> Command[Any]:
        """读取当前知识库最近30天已答错题，最多10条；返回真实反馈和有效来源。"""
        result = await queries.recent_mistakes(runtime.context.knowledge_base_id, limit)
        evidence = [e for item in result["items"] for e in item.get("evidence", [])]
        return feedback(runtime, result, "mistakes", evidence)

    return [
        search_learning_materials,
        get_answered_question_context,
        get_learning_progress,
        list_recent_mistakes,
    ]
