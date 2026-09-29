from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from study_agent.application.adaptive_selection import AdaptiveQuestionSelector
from study_agent.application.study_explanations import LangChainStudyExplanationGenerator
from study_agent.config import Settings
from study_agent.domain.models import MasteryRecord, Question, QuestionSource, ReviewTask


def make_question(
    *, point_id: UUID, difficulty: int, question_type: str = "single_choice"
) -> Question:
    return Question(
        id=uuid4(),
        knowledge_base_id=uuid4(),
        knowledge_point_id=point_id,
        question_type=question_type,
        stem="哪一个选项正确？",
        options=[
            {"key": "A", "text": "正确项"},
            {"key": "B", "text": "干扰项"},
            {"key": "C", "text": "干扰项二"},
            {"key": "D", "text": "干扰项三"},
        ],
        correct_answer=["A"],
        scoring_points=[],
        explanation="基础解析",
        difficulty=difficulty,
        max_score=10,
        status="active",
        content_hash=str(uuid4()),
        vector_id=None,
        sources=[QuestionSource(chunk_id=uuid4(), quote="真实原文", rank=1)],
        created_at=datetime.now(UTC),
    )


class QuestionRepositoryStub:
    def __init__(self, questions: list[Question]) -> None:
        self.questions = questions

    async def list_active_candidates(self, **_: object) -> list[Question]:
        return self.questions


class MasteryRepositoryStub:
    def __init__(self, records: list[MasteryRecord]) -> None:
        self.records = records

    async def list(self, _: UUID) -> list[MasteryRecord]:
        return self.records


class ReviewRepositoryStub:
    def __init__(self, tasks: list[ReviewTask]) -> None:
        self.tasks = tasks

    async def list_due(self, **_: object) -> list[ReviewTask]:
        return self.tasks


class AnswerRepositoryStub:
    def __init__(self, answered: set[UUID] | None = None) -> None:
        self.answered = answered or set()

    async def list_answered_question_ids(self, _: UUID) -> set[UUID]:
        return self.answered


def mastery(question: Question, score: float) -> MasteryRecord:
    return MasteryRecord(
        knowledge_point_id=question.knowledge_point_id,
        knowledge_base_id=question.knowledge_base_id,
        mastery_score=score,
        answered_count=3,
        correct_count=2,
        recent_accuracy=0.67,
        confidence=0.3,
        updated_at=datetime.now(UTC),
    )


def selector_uow(
    questions: list[Question],
    mastery_records: list[MasteryRecord],
    review_tasks: list[ReviewTask] | None = None,
) -> object:
    return SimpleNamespace(
        questions=QuestionRepositoryStub(questions),
        mastery=MasteryRepositoryStub(mastery_records),
        review_tasks=ReviewRepositoryStub(review_tasks or []),
        answer_records=AnswerRepositoryStub(),
    )


@pytest.mark.asyncio
async def test_practice_prioritizes_weak_knowledge_point() -> None:
    strong = make_question(point_id=uuid4(), difficulty=4)
    weak = make_question(point_id=uuid4(), difficulty=2)
    result = await AdaptiveQuestionSelector().select(
        selector_uow([strong, weak], [mastery(strong, 0.9), mastery(weak, 0.2)]),  # type: ignore[arg-type]
        knowledge_base_id=strong.knowledge_base_id,
        mode="practice",
        question_types=["single_choice"],
        difficulty_min=1,
        difficulty_max=5,
        selected_questions=[],
    )
    assert result is not None
    assert result.question.id == weak.id
    assert result.reason["code"] == "WEAK_KNOWLEDGE_POINT"


@pytest.mark.asyncio
async def test_review_only_selects_due_knowledge_point() -> None:
    not_due = make_question(point_id=uuid4(), difficulty=2)
    due = make_question(point_id=uuid4(), difficulty=3)
    task = ReviewTask(
        id=uuid4(),
        knowledge_point_id=due.knowledge_point_id,
        knowledge_base_id=due.knowledge_base_id,
        due_at=datetime.now(UTC) - timedelta(minutes=1),
        interval_days=1,
        repetitions=1,
        ease_factor=2.5,
        last_quality=5,
        status="pending",
        updated_at=datetime.now(UTC),
    )
    result = await AdaptiveQuestionSelector().select(
        selector_uow([not_due, due], [], [task]),  # type: ignore[arg-type]
        knowledge_base_id=due.knowledge_base_id,
        mode="review",
        question_types=["single_choice"],
        difficulty_min=1,
        difficulty_max=5,
        selected_questions=[],
    )
    assert result is not None
    assert result.question.id == due.id
    assert result.reason["code"] == "REVIEW_DUE"


@pytest.mark.asyncio
async def test_explanation_falls_back_to_bound_question_evidence_without_llm() -> None:
    question = make_question(point_id=uuid4(), difficulty=2)
    generator = LangChainStudyExplanationGenerator(
        Settings(_env_file=None, study_explanation_enabled=True, llm_base_url=None)
    )
    result = await generator.explain(question=question, user_answer="B", correct=False)
    assert result["status"] == "fallback_not_configured"
    assert result["evidence"] == [
        {
            "chunk_id": str(question.sources[0].chunk_id),
            "quote": "真实原文",
            "rank": 1,
        }
    ]
