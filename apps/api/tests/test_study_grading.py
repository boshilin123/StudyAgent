from datetime import UTC, datetime
from uuid import uuid4

import pytest

from study_agent.application.study import grade_question
from study_agent.domain.models import Question


def make_question(question_type: str, correct_answer: object) -> Question:
    return Question(
        id=uuid4(),
        knowledge_base_id=uuid4(),
        knowledge_point_id=uuid4(),
        question_type=question_type,
        stem="测试题目",
        options=None,
        correct_answer=correct_answer,
        scoring_points=[],
        explanation="测试解析",
        difficulty=1,
        max_score=10.0,
        status="active",
        content_hash="hash",
        vector_id=None,
        created_at=datetime.now(UTC),
    )


@pytest.mark.parametrize("answer", ["A", " a "])
def test_single_choice_grading_is_case_insensitive(answer: str) -> None:
    result = grade_question(make_question("single_choice", ["A"]), answer)
    assert result.correct is True
    assert result.score == 10.0


@pytest.mark.parametrize("answer", ["RAG", " rag ", "ＲＡＧ。"])
def test_fill_blank_grading_normalizes_width_case_and_punctuation(answer: str) -> None:
    result = grade_question(make_question("fill_blank", ["RAG"]), answer)
    assert result.correct is True


@pytest.mark.parametrize("answer", [True, 1, "true", "对", "正确"])
def test_true_false_grading_accepts_common_true_aliases(answer: object) -> None:
    result = grade_question(make_question("true_false", ["正确"]), answer)
    assert result.correct is True


def test_incorrect_answer_scores_zero() -> None:
    result = grade_question(make_question("single_choice", ["A"]), "B")
    assert result.correct is False
    assert result.score == 0.0
