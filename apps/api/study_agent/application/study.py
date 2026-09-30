import unicodedata
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from study_agent.application.adaptive_selection import AdaptiveQuestionSelector
from study_agent.application.study_explanations import fallback_explanation
from study_agent.domain.errors import DomainError
from study_agent.domain.models import (
    AnswerRecord,
    MasteryRecord,
    Question,
    ReviewTask,
    SessionQuestion,
    StudySession,
)
from study_agent.domain.ports import StudyExplanationGenerator, StudyStateStore, UnitOfWork


@dataclass(frozen=True, slots=True)
class Grade:
    correct: bool
    score: float
    max_score: float
    feedback: str


@dataclass(frozen=True, slots=True)
class SessionView:
    session: StudySession
    current_question: Question | None
    selection_reason: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class AnswerResult:
    answer_record: AnswerRecord
    mastery: MasteryRecord
    review_task: ReviewTask
    session: StudySession
    next_question: Question | None
    explanation: str
    explanation_data: dict[str, object]
    next_selection_reason: dict[str, object] | None = None
    idempotent_replay: bool = False


def _normalize_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value)).casefold().strip()
    # Only sentence punctuation is optional; signs, decimal points, slashes and
    # internal spaces may carry meaning. Equivalent expressions use answer aliases.
    return " ".join(text.split()).rstrip("。！？!?；;").strip()


def _answer_list(correct_answer: object) -> list[object]:
    return correct_answer if isinstance(correct_answer, list) else [correct_answer]


def grade_question(question: Question, answer: object) -> Grade:
    expected = _answer_list(question.correct_answer)
    if question.question_type == "single_choice":
        actual = str(answer).strip().upper()
        accepted = {str(item).strip().upper() for item in expected}
    elif question.question_type == "fill_blank":
        actual = _normalize_text(answer)
        accepted = {_normalize_text(item) for item in expected}
    elif question.question_type == "true_false":
        aliases = {
            "true": "正确",
            "1": "正确",
            "正确": "正确",
            "对": "正确",
            "false": "错误",
            "0": "错误",
            "错误": "错误",
            "错": "错误",
        }
        actual = aliases.get(_normalize_text(answer), _normalize_text(answer))
        accepted = {aliases.get(_normalize_text(item), _normalize_text(item)) for item in expected}
    else:
        raise DomainError("UNSUPPORTED_QUESTION_TYPE", "当前学习闭环不支持该题型", status_code=422)
    correct = bool(actual) and actual in accepted
    return Grade(
        correct=correct,
        score=question.max_score if correct else 0.0,
        max_score=question.max_score,
        feedback="回答正确" if correct else "回答错误，请结合解析复习该知识点",
    )


class StudyService:
    def __init__(self) -> None:
        self.selector = AdaptiveQuestionSelector()

    async def create_session(
        self,
        uow: UnitOfWork,
        *,
        knowledge_base_id: UUID,
        mode: str,
        question_count: int,
        question_types: list[str],
        difficulty_min: int,
        difficulty_max: int,
        state_store: StudyStateStore | None = None,
    ) -> SessionView:
        knowledge_base = await uow.knowledge_bases.get(knowledge_base_id)
        if knowledge_base is None:
            raise DomainError("KNOWLEDGE_BASE_NOT_FOUND", "知识库不存在", status_code=404)
        if knowledge_base.status != "active":
            raise DomainError("KNOWLEDGE_BASE_ARCHIVED", "归档知识库不能开始学习", status_code=409)
        assignments: list[tuple[Question, dict[str, object], float]] = []
        if mode == "mock_exam":
            candidates = list(
                await uow.questions.list_active_candidates(
                    knowledge_base_id=knowledge_base_id,
                    question_types=question_types,
                    difficulty_min=difficulty_min,
                    difficulty_max=difficulty_max,
                    limit=question_count,
                )
            )
            assignments = [
                (
                    question,
                    {
                        "code": "MOCK_EXAM_FIXED",
                        "message": "模拟考试在会话开始时固定题目和顺序",
                    },
                    0.0,
                )
                for question in candidates
            ]
        else:
            selection = await self.selector.select(
                uow,
                knowledge_base_id=knowledge_base_id,
                mode=mode,
                question_types=question_types,
                difficulty_min=difficulty_min,
                difficulty_max=difficulty_max,
                selected_questions=[],
            )
            if selection:
                assignments = [(selection.question, selection.reason, selection.priority_score)]
        if not assignments:
            code = "NO_DUE_REVIEWS" if mode == "review" else "NO_ACTIVE_QUESTIONS"
            message = "没有到期且可用的复习题" if mode == "review" else "没有符合条件的已启用题目"
            raise DomainError(code, message, status_code=409)
        now = datetime.now(UTC)
        study_session = StudySession(
            id=uuid4(),
            knowledge_base_id=knowledge_base_id,
            mode=mode,
            status="active",
            planned_question_count=(len(assignments) if mode == "mock_exam" else question_count),
            answered_question_count=0,
            correct_count=0,
            incorrect_count=0,
            total_score=0.0,
            max_total_score=0.0,
            question_types=question_types,
            difficulty_min=difficulty_min,
            difficulty_max=difficulty_max,
            started_at=now,
        )
        study_session = await uow.study_sessions.add(study_session)
        await uow.study_sessions.add_questions(
            [
                SessionQuestion(
                    session_id=study_session.id,
                    question_id=question.id,
                    sequence=index,
                    selection_reason=reason,
                    priority_score=priority,
                )
                for index, (question, reason, priority) in enumerate(assignments, start=1)
            ]
        )
        await uow.commit()
        first_question, first_reason, _ = assignments[0]
        await self._sync_runtime_state(uow, study_session, first_question, state_store)
        return SessionView(study_session, first_question, first_reason)

    async def get_session(
        self,
        uow: UnitOfWork,
        session_id: UUID,
        state_store: StudyStateStore | None = None,
    ) -> SessionView:
        study_session = await uow.study_sessions.get(session_id)
        if study_session is None:
            raise DomainError("STUDY_SESSION_NOT_FOUND", "学习会话不存在", status_code=404)
        current, assignment = await self._current_assignment(uow, study_session)
        if state_store and await state_store.get(session_id) is None:
            await self._sync_runtime_state(uow, study_session, current, state_store)
        return SessionView(
            study_session, current, assignment.selection_reason if assignment else None
        )

    async def submit_answer(
        self,
        uow: UnitOfWork,
        *,
        session_id: UUID,
        submission_id: UUID,
        question_id: UUID,
        answer: object,
        elapsed_seconds: int,
        explanation_generator: StudyExplanationGenerator | None = None,
        state_store: StudyStateStore | None = None,
    ) -> AnswerResult:
        # This also serializes the first use of an ID across different sessions.
        await uow.lock(submission_id)
        replay = await uow.answer_records.get_by_submission(submission_id)
        if replay is not None:
            return await self._replay_result(
                uow,
                replay,
                session_id=session_id,
                question_id=question_id,
                answer=answer,
                state_store=state_store,
            )
        study_session = await uow.study_sessions.get_for_update(session_id)
        if study_session is None:
            raise DomainError("STUDY_SESSION_NOT_FOUND", "学习会话不存在", status_code=404)
        if study_session.status != "active":
            raise DomainError("STUDY_SESSION_FINISHED", "学习会话已经结束", status_code=409)
        await uow.lock(question_id)
        question, _ = await self._current_assignment(uow, study_session)
        if question is None or question.id != question_id:
            raise DomainError("QUESTION_OUT_OF_ORDER", "只能提交当前题目的答案", status_code=409)
        if question.status != "active" or not question.sources:
            raise DomainError(
                "QUESTION_UNAVAILABLE", "题目已停用或来源失效，请结束本轮学习", status_code=409
            )
        # A point may not have a mastery/review row yet: a row lock alone cannot
        # protect concurrent inserts. Transaction-scoped advisory locks can.
        await uow.lock(question.knowledge_point_id)

        grade = grade_question(question, answer)
        now = datetime.now(UTC)
        answer_record = await uow.answer_records.add(
            AnswerRecord(
                id=uuid4(),
                submission_id=submission_id,
                session_id=session_id,
                question_id=question.id,
                knowledge_point_id=question.knowledge_point_id,
                answer=answer,
                score=grade.score,
                max_score=grade.max_score,
                verdict="correct" if grade.correct else "incorrect",
                feedback=grade.feedback,
                elapsed_seconds=elapsed_seconds,
                answered_at=now,
            )
        )
        mastery = await self._update_mastery(uow, question, grade.correct, now)
        review = await self._update_review(uow, question, grade.correct, now)
        answered_count = study_session.answered_question_count + 1
        completed = answered_count >= study_session.planned_question_count
        next_question: Question | None = None
        next_reason: dict[str, object] | None = None
        if not completed and study_session.mode != "mock_exam":
            selected_questions = await self._selected_questions(uow, study_session.id)
            selection = await self.selector.select(
                uow,
                knowledge_base_id=study_session.knowledge_base_id,
                mode=study_session.mode,
                question_types=study_session.question_types,
                difficulty_min=study_session.difficulty_min,
                difficulty_max=study_session.difficulty_max,
                selected_questions=selected_questions,
                last_question=question,
                last_correct=grade.correct,
            )
            if selection is None:
                completed = True
            else:
                next_question = selection.question
                next_reason = selection.reason
                await uow.study_sessions.add_questions(
                    [
                        SessionQuestion(
                            session_id=study_session.id,
                            question_id=selection.question.id,
                            sequence=answered_count + 1,
                            selection_reason=selection.reason,
                            priority_score=selection.priority_score,
                        )
                    ]
                )
        study_session = await uow.study_sessions.update(
            replace(
                study_session,
                status="completed" if completed else "active",
                answered_question_count=answered_count,
                correct_count=study_session.correct_count + int(grade.correct),
                incorrect_count=study_session.incorrect_count + int(not grade.correct),
                total_score=study_session.total_score + grade.score,
                max_total_score=study_session.max_total_score + grade.max_score,
                finished_at=now if completed else None,
            )
        )
        await uow.commit()
        try:
            explanation_data = (
                await explanation_generator.explain(
                    question=question, user_answer=answer, correct=grade.correct
                )
                if explanation_generator
                else fallback_explanation(question=question, correct=grade.correct)
            )
        except Exception:
            explanation_data = fallback_explanation(question=question, correct=grade.correct)
        answer_record = await uow.answer_records.update_explanation(
            answer_record.id, explanation_data
        )
        await uow.commit()
        if not completed and study_session.mode == "mock_exam":
            next_question, next_assignment = await self._current_assignment(uow, study_session)
            next_reason = next_assignment.selection_reason if next_assignment else None
        await self._sync_runtime_state(uow, study_session, next_question, state_store)
        return AnswerResult(
            answer_record=answer_record,
            mastery=mastery,
            review_task=review,
            session=study_session,
            next_question=next_question,
            explanation=str(explanation_data["gap"]),
            explanation_data=explanation_data,
            next_selection_reason=next_reason,
        )

    async def finish_session(
        self,
        uow: UnitOfWork,
        session_id: UUID,
        state_store: StudyStateStore | None = None,
    ) -> SessionView:
        study_session = await uow.study_sessions.get_for_update(session_id)
        if study_session is None:
            raise DomainError("STUDY_SESSION_NOT_FOUND", "学习会话不存在", status_code=404)
        if study_session.status == "active":
            study_session = await uow.study_sessions.update(
                replace(study_session, status="completed", finished_at=datetime.now(UTC))
            )
            await uow.commit()
        await self._sync_runtime_state(uow, study_session, None, state_store)
        return SessionView(study_session, None)

    async def list_history(
        self,
        uow: UnitOfWork,
        *,
        knowledge_base_id: UUID | None,
        page: int,
        page_size: int,
    ) -> tuple[list[StudySession], int]:
        items, total = await uow.study_sessions.list(
            knowledge_base_id=knowledge_base_id, page=page, page_size=page_size
        )
        return list(items), total

    async def _current_assignment(
        self, uow: UnitOfWork, study_session: StudySession
    ) -> tuple[Question | None, SessionQuestion | None]:
        if study_session.status != "active":
            return None, None
        sequence = study_session.answered_question_count + 1
        items = await uow.study_sessions.list_questions(study_session.id)
        selected = next((item for item in items if item.sequence == sequence), None)
        if selected is None:
            return None, None
        question = await uow.questions.get(selected.question_id)
        if question is None or question.status != "active" or not question.sources:
            return None, selected
        return question, selected

    async def _current_question(
        self, uow: UnitOfWork, study_session: StudySession
    ) -> Question | None:
        question, _ = await self._current_assignment(uow, study_session)
        return question

    async def _selected_questions(self, uow: UnitOfWork, session_id: UUID) -> list[Question]:
        assignments = await uow.study_sessions.list_questions(session_id)
        questions: list[Question] = []
        for assignment in assignments:
            question = await uow.questions.get(assignment.question_id)
            if question:
                questions.append(question)
        return questions

    async def _update_mastery(
        self, uow: UnitOfWork, question: Question, correct: bool, now: datetime
    ) -> MasteryRecord:
        current = await uow.mastery.get(question.knowledge_point_id)
        previous_score = current.mastery_score if current else 0.3
        answered = (current.answered_count if current else 0) + 1
        correct_count = (current.correct_count if current else 0) + int(correct)
        score = previous_score + 0.15 * (1 - previous_score) if correct else previous_score * 0.8
        return await uow.mastery.upsert(
            MasteryRecord(
                knowledge_point_id=question.knowledge_point_id,
                knowledge_base_id=question.knowledge_base_id,
                mastery_score=round(max(0.0, min(1.0, score)), 4),
                answered_count=answered,
                correct_count=correct_count,
                recent_accuracy=round(correct_count / answered, 4),
                confidence=round(min(1.0, answered / 10), 4),
                updated_at=now,
            )
        )

    async def _update_review(
        self, uow: UnitOfWork, question: Question, correct: bool, now: datetime
    ) -> ReviewTask:
        current = await uow.review_tasks.get_by_knowledge_point(question.knowledge_point_id)
        quality = 5 if correct else 2
        ease = current.ease_factor if current else 2.5
        ease = max(1.3, ease + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)))
        if correct:
            repetitions = (current.repetitions if current else 0) + 1
            if repetitions == 1:
                interval = 1
            elif repetitions == 2:
                interval = 6
            else:
                interval = max(1, round((current.interval_days if current else 1) * ease))
        else:
            repetitions = 0
            interval = 1
        return await uow.review_tasks.upsert(
            ReviewTask(
                id=current.id if current else uuid4(),
                knowledge_point_id=question.knowledge_point_id,
                knowledge_base_id=question.knowledge_base_id,
                due_at=now + timedelta(days=interval),
                interval_days=interval,
                repetitions=repetitions,
                ease_factor=round(ease, 2),
                last_quality=quality,
                status="pending",
                updated_at=now,
            )
        )

    async def _replay_result(
        self,
        uow: UnitOfWork,
        record: AnswerRecord,
        *,
        session_id: UUID,
        question_id: UUID,
        answer: object,
        state_store: StudyStateStore | None = None,
    ) -> AnswerResult:
        if (
            record.session_id != session_id
            or record.question_id != question_id
            or record.answer != answer
        ):
            raise DomainError(
                "SUBMISSION_ID_CONFLICT", "submission_id 已被不同请求使用", status_code=409
            )
        study_session = await uow.study_sessions.get(session_id)
        mastery = await uow.mastery.get(record.knowledge_point_id)
        review = await uow.review_tasks.get_by_knowledge_point(record.knowledge_point_id)
        question = await uow.questions.get(question_id)
        if study_session is None or mastery is None or review is None or question is None:
            raise DomainError("ANSWER_REPLAY_INCOMPLETE", "历史作答数据不完整", status_code=500)
        next_question, next_assignment = await self._current_assignment(uow, study_session)
        await self._sync_runtime_state(uow, study_session, next_question, state_store)
        explanation_data = record.explanation_data or fallback_explanation(
            question=question, correct=record.verdict == "correct"
        )
        return AnswerResult(
            answer_record=record,
            mastery=mastery,
            review_task=review,
            session=study_session,
            next_question=next_question,
            explanation=str(explanation_data["gap"]),
            explanation_data=explanation_data,
            next_selection_reason=(next_assignment.selection_reason if next_assignment else None),
            idempotent_replay=True,
        )

    async def _sync_runtime_state(
        self,
        uow: UnitOfWork,
        study_session: StudySession,
        current_question: Question | None,
        state_store: StudyStateStore | None,
    ) -> None:
        if state_store is None:
            return
        assignments = await uow.study_sessions.list_questions(study_session.id)
        answers = list(await uow.answer_records.list_for_session(study_session.id))
        mastery = await uow.mastery.list(study_session.knowledge_base_id)
        state: dict[str, object] = {
            "session_id": str(study_session.id),
            "mode": study_session.mode,
            "status": study_session.status,
            "current_question_id": str(current_question.id) if current_question else None,
            "selected_question_ids": [str(item.question_id) for item in assignments],
            "answered_question_ids": [str(item.question_id) for item in answers],
            "recent_results": [
                {
                    "question_id": str(item.question_id),
                    "knowledge_point_id": str(item.knowledge_point_id),
                    "verdict": item.verdict,
                    "score": item.score,
                    "max_score": item.max_score,
                }
                for item in answers[-5:]
            ],
            "weak_point_ids": [
                str(item.knowledge_point_id) for item in mastery if item.mastery_score < 0.5
            ],
            "remaining_question_count": max(
                0,
                study_session.planned_question_count - study_session.answered_question_count,
            ),
            "next_action": "await_answer" if current_question else "finish",
            "updated_at": datetime.now(UTC).isoformat(),
        }
        await state_store.save(study_session.id, state)
