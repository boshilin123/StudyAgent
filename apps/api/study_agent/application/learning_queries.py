"""Bounded, read-only current learning facts; no selection or grading side effects."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from study_agent.application.retrieval import evidence_from_rows
from study_agent.domain.errors import DomainError
from study_agent.infrastructure.models import (
    AnswerRecordModel,
    DocumentChunkModel,
    KnowledgeBaseModel,
    KnowledgePointModel,
    MasteryRecordModel,
    MaterialModel,
    QuestionModel,
    QuestionSourceModel,
    ReviewTaskModel,
    StudySessionModel,
)


class LearningQueries:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = session_factory

    async def check_scope(self, knowledge_base_id: UUID) -> None:
        async with self.sessions() as session:
            kb = await session.get(KnowledgeBaseModel, knowledge_base_id)
            if kb is None or kb.status != "active":
                raise DomainError(
                    "KNOWLEDGE_BASE_NOT_FOUND", "知识库不存在或已归档", status_code=404
                )
            exam = await session.scalar(
                select(StudySessionModel.id)
                .where(
                    StudySessionModel.knowledge_base_id == knowledge_base_id,
                    StudySessionModel.mode == "mock_exam",
                    StudySessionModel.status == "active",
                )
                .limit(1)
            )
            if exam:
                raise DomainError(
                    "TUTOR_EXAM_IN_PROGRESS",
                    "模拟考试进行中，当前知识库暂不开放辅导",
                    status_code=409,
                )

    async def answered_question(
        self, knowledge_base_id: UUID, session_id: UUID | None, question_id: UUID | None
    ) -> dict[str, Any]:
        await self.check_scope(knowledge_base_id)
        if not session_id or not question_id:
            return {"code": "NO_ANSWERED_QUESTION_CONTEXT", "evidence": []}
        async with self.sessions() as session:
            row = (
                await session.execute(
                    select(AnswerRecordModel, QuestionModel)
                    .join(QuestionModel, AnswerRecordModel.question_id == QuestionModel.id)
                    .join(StudySessionModel, AnswerRecordModel.session_id == StudySessionModel.id)
                    .where(
                        AnswerRecordModel.session_id == session_id,
                        AnswerRecordModel.question_id == question_id,
                        QuestionModel.knowledge_base_id == knowledge_base_id,
                        StudySessionModel.knowledge_base_id == knowledge_base_id,
                    )
                )
            ).first()
            if not row:
                raise DomainError(
                    "TUTOR_CONTEXT_UNAVAILABLE", "未找到范围内的真实答题记录", status_code=409
                )
            answer, question = row
            sources = (
                await session.execute(
                    select(DocumentChunkModel, MaterialModel, QuestionSourceModel.quote)
                    .join(MaterialModel, DocumentChunkModel.material_id == MaterialModel.id)
                    .join(
                        QuestionSourceModel, QuestionSourceModel.chunk_id == DocumentChunkModel.id
                    )
                    .where(
                        QuestionSourceModel.question_id == question_id,
                        MaterialModel.knowledge_base_id == knowledge_base_id,
                        MaterialModel.parse_status == "ready",
                    )
                    .order_by(QuestionSourceModel.rank)
                    .limit(5)
                )
            ).all()
            return {
                "code": "OK",
                "question_id": str(question.id),
                "stem": question.stem,
                "options": question.options,
                "user_answer": answer.answer,
                "verdict": answer.verdict,
                "score": float(answer.score),
                "feedback": answer.feedback,
                "correct_answer": question.correct_answer,
                "explanation": question.explanation,
                "evidence": [evidence_from_rows(c, m, quote) for c, m, quote in sources],
            }

    async def progress(self, knowledge_base_id: UUID) -> dict[str, Any]:
        await self.check_scope(knowledge_base_id)
        now = datetime.now(UTC)
        async with self.sessions() as session:
            count, correct = (
                await session.execute(
                    select(
                        func.count(AnswerRecordModel.id),
                        func.count(AnswerRecordModel.id).filter(
                            AnswerRecordModel.verdict == "correct"
                        ),
                    )
                    .join(StudySessionModel, AnswerRecordModel.session_id == StudySessionModel.id)
                    .where(
                        StudySessionModel.knowledge_base_id == knowledge_base_id,
                    )
                )
            ).one()
            weak = (
                await session.execute(
                    select(MasteryRecordModel, KnowledgePointModel.name)
                    .join(
                        KnowledgePointModel,
                        MasteryRecordModel.knowledge_point_id == KnowledgePointModel.id,
                    )
                    .where(MasteryRecordModel.knowledge_base_id == knowledge_base_id)
                    .order_by(
                        MasteryRecordModel.mastery_score,
                        MasteryRecordModel.knowledge_point_id,
                    )
                    .limit(10)
                )
            ).all()
            due = await session.scalar(
                select(func.count())
                .select_from(ReviewTaskModel)
                .where(
                    ReviewTaskModel.knowledge_base_id == knowledge_base_id,
                    ReviewTaskModel.due_at <= now,
                    ReviewTaskModel.status == "pending",
                )
            )
            return {
                "code": "OK" if count else "NO_LEARNING_HISTORY",
                "answered_count": count,
                "correct_count": correct,
                "accuracy": correct / count if count else None,
                "due_review_count": due,
                "statistics_at": now.isoformat(),
                "rules_version": "db-count-v1",
                "weak_knowledge_points": [
                    {
                        "name": name,
                        "mastery": float(m.mastery_score),
                        "sample_count": m.answered_count,
                    }
                    for m, name in weak
                ]
                if count
                else [],
            }

    async def recent_mistakes(self, knowledge_base_id: UUID, limit: int) -> dict[str, Any]:
        await self.check_scope(knowledge_base_id)
        async with self.sessions() as session:
            rows = (
                await session.execute(
                    select(AnswerRecordModel, QuestionModel, KnowledgePointModel.name)
                    .join(QuestionModel, AnswerRecordModel.question_id == QuestionModel.id)
                    .join(StudySessionModel, AnswerRecordModel.session_id == StudySessionModel.id)
                    .join(
                        KnowledgePointModel,
                        AnswerRecordModel.knowledge_point_id == KnowledgePointModel.id,
                    )
                    .where(
                        StudySessionModel.knowledge_base_id == knowledge_base_id,
                        QuestionModel.knowledge_base_id == knowledge_base_id,
                        AnswerRecordModel.verdict == "incorrect",
                        AnswerRecordModel.answered_at >= datetime.now(UTC) - timedelta(days=30),
                    )
                    .order_by(AnswerRecordModel.answered_at.desc(), AnswerRecordModel.id.desc())
                    .limit(limit)
                )
            ).all()
        items = []
        for answer, question, name in rows:
            context = await self.answered_question(
                knowledge_base_id, answer.session_id, question.id
            )
            items.append(
                {**context, "knowledge_point": name, "answered_at": answer.answered_at.isoformat()}
            )
        return {"code": "OK" if items else "NO_RECENT_MISTAKES", "items": items}
