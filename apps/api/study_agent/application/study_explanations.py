import json
from typing import Any, cast

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from pydantic import BaseModel, Field

from study_agent.config import Settings
from study_agent.domain.models import Question
from study_agent.llm.models import get_chat_model


class ExplanationDraft(BaseModel):
    conclusion: str = Field(min_length=2, max_length=500)
    gap: str = Field(min_length=2, max_length=1000)


def fallback_explanation(
    *, question: Question, correct: bool, status: str = "fallback"
) -> dict[str, object]:
    return {
        "provider": "question_bank",
        "status": status,
        "conclusion": "回答正确。" if correct else "本题回答不正确。",
        "gap": question.explanation,
        "evidence": [
            {
                "chunk_id": str(source.chunk_id),
                "quote": source.quote,
                "rank": source.rank,
            }
            for source in question.sources
        ],
    }


class LangChainStudyExplanationGenerator:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.chain = self._build_chain(settings) if self._enabled(settings) else None

    @staticmethod
    def _enabled(settings: Settings) -> bool:
        return bool(
            settings.study_explanation_enabled and settings.llm_base_url and settings.llm_model
        )

    @staticmethod
    def _build_chain(settings: Settings) -> Runnable[dict[str, Any], ExplanationDraft]:
        parser = PydanticOutputParser(pydantic_object=ExplanationDraft)
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是严谨的个人学习讲解助手。只能依据题目、标准答案、已有解析和真实原文证据解释错误。"
                    "不要虚构资料、页码或引用 ID。"
                    "用简洁中文给出结论和用户答案与正确答案之间的差距。",
                ),
                (
                    "human",
                    "题目：{stem}\n题型：{question_type}\n用户答案：{user_answer}\n"
                    "标准答案：{correct_answer}\n已有解析：{base_explanation}\n"
                    "原文证据：\n{evidence}\n\n输出要求：\n{format_instructions}",
                ),
            ]
        ).partial(format_instructions=parser.get_format_instructions())
        model = get_chat_model(settings, purpose="study_explanation")
        chain = prompt | model | parser
        return cast(Runnable[dict[str, Any], ExplanationDraft], chain)

    async def explain(
        self, *, question: Question, user_answer: object, correct: bool
    ) -> dict[str, object]:
        if correct or self.chain is None:
            return fallback_explanation(
                question=question,
                correct=correct,
                status="question_bank" if correct else "fallback_not_configured",
            )
        evidence = [
            {"chunk_id": str(source.chunk_id), "quote": source.quote, "rank": source.rank}
            for source in question.sources
        ]
        try:
            draft = await self.chain.ainvoke(
                {
                    "stem": question.stem,
                    "question_type": question.question_type,
                    "user_answer": json.dumps(user_answer, ensure_ascii=False),
                    "correct_answer": json.dumps(question.correct_answer, ensure_ascii=False),
                    "base_explanation": question.explanation,
                    "evidence": json.dumps(evidence, ensure_ascii=False),
                }
            )
        except Exception:
            return fallback_explanation(
                question=question, correct=False, status="fallback_model_error"
            )
        return {
            "provider": "langchain",
            "status": "generated",
            "conclusion": draft.conclusion,
            "gap": draft.gap,
            "evidence": evidence,
        }
