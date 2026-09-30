from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from study_agent.domain.models import Question
from study_agent.domain.ports import UnitOfWork


@dataclass(frozen=True, slots=True)
class QuestionSelection:
    question: Question
    priority_score: float
    reason: dict[str, object]


class AdaptiveQuestionSelector:
    async def select(
        self,
        uow: UnitOfWork,
        *,
        knowledge_base_id: UUID,
        mode: str,
        question_types: list[str],
        difficulty_min: int,
        difficulty_max: int,
        selected_questions: list[Question],
        last_question: Question | None = None,
        last_correct: bool | None = None,
    ) -> QuestionSelection | None:
        candidates = list(
            await uow.questions.list_active_candidates(
                knowledge_base_id=knowledge_base_id,
                question_types=question_types,
                difficulty_min=difficulty_min,
                difficulty_max=difficulty_max,
                limit=None,
            )
        )
        excluded_ids = {question.id for question in selected_questions}
        candidates = [question for question in candidates if question.id not in excluded_ids]
        candidates = [question for question in candidates if question.sources]
        if not candidates:
            return None

        mastery_items = await uow.mastery.list(knowledge_base_id)
        mastery = {item.knowledge_point_id: item for item in mastery_items}
        due_items = await uow.review_tasks.list_due(
            knowledge_base_id=knowledge_base_id, due_before=datetime.now(UTC)
        )
        due_points = {item.knowledge_point_id for item in due_items}
        if mode == "review":
            candidates = [
                question for question in candidates if question.knowledge_point_id in due_points
            ]
            if not candidates:
                return None

        answered_ids = await uow.answer_records.list_answered_question_ids(knowledge_base_id)
        selected_point_counts: dict[UUID, int] = {}
        for question in selected_questions:
            selected_point_counts[question.knowledge_point_id] = (
                selected_point_counts.get(question.knowledge_point_id, 0) + 1
            )

        if mode == "diagnostic":
            # Cover unseen points before spending a second question on one point.
            minimum = min(
                selected_point_counts.get(question.knowledge_point_id, 0) for question in candidates
            )
            candidates = [
                question
                for question in candidates
                if selected_point_counts.get(question.knowledge_point_id, 0) == minimum
            ]

        ranked: list[tuple[float, Question, dict[str, object]]] = []
        for question in candidates:
            record = mastery.get(question.knowledge_point_id)
            mastery_score = record.mastery_score if record else 0.3
            due_score = 1.0 if question.knowledge_point_id in due_points else 0.0
            recent_error = float(
                last_question is not None
                and last_correct is False
                and last_question.knowledge_point_id == question.knowledge_point_id
            )
            if mode == "diagnostic":
                knowledge_priority = 0.20 * (1 - mastery_score) + 0.10 * due_score + 0.70
            else:
                knowledge_priority = (
                    0.45 * (1 - mastery_score) + 0.25 * due_score + 0.10 + 0.20 * recent_error
                )

            target_difficulty = round(1 + mastery_score * 4)
            if recent_error and last_question is not None:
                target_difficulty = max(difficulty_min, last_question.difficulty - 1)
            target_difficulty = max(difficulty_min, min(difficulty_max, target_difficulty))
            difficulty_match = max(0.0, 1 - abs(question.difficulty - target_difficulty) / 4)
            freshness = 0.0 if question.id in answered_ids else 1.0
            source_quality = min(1.0, len(question.sources) / 2)
            type_diversity = float(
                last_question is None or question.question_type != last_question.question_type
            )
            question_priority = (
                0.45 * difficulty_match
                + 0.25 * freshness
                + 0.20 * source_quality
                + 0.10 * type_diversity
            )
            priority = 0.55 * knowledge_priority + 0.45 * question_priority

            same_point_count = selected_point_counts.get(question.knowledge_point_id, 0)
            if recent_error and same_point_count >= 3:
                priority -= 1.0

            if recent_error:
                code = "REMEDIAL_DIFFICULTY_STEP_DOWN"
                message = "同一知识点刚刚答错，优先选择较低难度的补弱题"
            elif due_score:
                code = "REVIEW_DUE"
                message = "该知识点已经到达复习时间"
            elif mastery_score < 0.5:
                code = "WEAK_KNOWLEDGE_POINT"
                message = "该知识点当前掌握度较低"
            elif freshness:
                code = "FRESH_QUESTION"
                message = "优先选择尚未作答且难度匹配的题目"
            else:
                code = "BEST_AVAILABLE"
                message = "当前约束下综合优先级最高的可用题目"
            reason: dict[str, object] = {
                "code": code,
                "message": message,
                "target_difficulty": target_difficulty,
                "factors": {
                    "mastery_score": round(mastery_score, 4),
                    "review_due": bool(due_score),
                    "recent_error": bool(recent_error),
                    "difficulty_match": round(difficulty_match, 4),
                    "freshness": round(freshness, 4),
                    "source_quality": round(source_quality, 4),
                    "type_diversity": round(type_diversity, 4),
                },
            }
            ranked.append((round(priority, 6), question, reason))

        ranked.sort(
            key=lambda item: (
                -item[0],
                item[1].difficulty,
                item[1].created_at.isoformat() if item[1].created_at else "",
                str(item[1].id),
            )
        )
        priority, question, reason = ranked[0]
        return QuestionSelection(question=question, priority_score=priority, reason=reason)
