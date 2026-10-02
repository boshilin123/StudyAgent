from typing import Any, cast

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware, ToolCallLimitMiddleware
from langchain.agents.structured_output import ToolStrategy
from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph

from study_agent.agents.tutor.context import TutorContext
from study_agent.agents.tutor.middleware import RunBudget, TutorBudgetMiddleware
from study_agent.agents.tutor.prompts import SYSTEM_PROMPT
from study_agent.agents.tutor.schemas import TutorAnswerDraft
from study_agent.agents.tutor.state import TutorState
from study_agent.agents.tutor.tools import make_tutor_tools
from study_agent.application.learning_queries import LearningQueries
from study_agent.application.retrieval import LearningMaterialRetrieval
from study_agent.domain.errors import DomainError


def create_tutor_agent(
    model: BaseChatModel,
    queries: LearningQueries,
    retrieval: LearningMaterialRetrieval,
    budget: RunBudget,
    checkpointer: BaseCheckpointSaver[Any],
) -> CompiledStateGraph[Any, Any, Any, Any]:
    repairs = 0

    def repair_once(error: Exception) -> str:
        nonlocal repairs
        repairs += 1
        if repairs > 1:
            raise DomainError("TUTOR_INVALID_OUTPUT", "结构化输出修复失败", status_code=503)
        return "输出格式不符合 TutorAnswerDraft。请修复一次并保留真实证据引用。"

    return create_agent(
        model=model,
        tools=make_tutor_tools(queries, retrieval),
        system_prompt=SYSTEM_PROMPT,
        response_format=ToolStrategy(TutorAnswerDraft, handle_errors=repair_once),
        state_schema=TutorState,
        context_schema=TutorContext,
        checkpointer=checkpointer,
        middleware=cast(
            Any,
            [
                TutorBudgetMiddleware(budget),
                ModelCallLimitMiddleware(run_limit=6, exit_behavior="error"),
                *[
                    ToolCallLimitMiddleware(
                        tool_name=name, run_limit=budget.max_tool_calls, exit_behavior="error"
                    )
                    for name in (
                        "search_learning_materials",
                        "get_answered_question_context",
                        "get_learning_progress",
                        "list_recent_mistakes",
                    )
                ],
            ],
        ),
        name="learning_tutor",
    )
