from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from study_agent.domain.models import (
    AnswerRecord,
    DocumentChunk,
    IngestionJob,
    KnowledgeBase,
    MasteryRecord,
    Material,
    Question,
    QuestionGenerationJob,
    QuestionSource,
    ReviewTask,
    SessionQuestion,
    StudySession,
)
from study_agent.infrastructure.locks import transaction_lock
from study_agent.infrastructure.models import (
    AnswerRecordModel,
    DocumentChunkModel,
    IngestionJobModel,
    KnowledgeBaseModel,
    MasteryRecordModel,
    MaterialModel,
    QuestionGenerationJobModel,
    QuestionModel,
    QuestionSourceModel,
    ReviewTaskModel,
    SessionQuestionModel,
    StudySessionModel,
)


def _knowledge_base_from_model(
    model: KnowledgeBaseModel, *, material_count: int = 0, question_count: int = 0
) -> KnowledgeBase:
    return KnowledgeBase(
        id=model.id,
        name=model.name,
        description=model.description,
        language=model.language,
        status=model.status,
        created_at=model.created_at,
        updated_at=model.updated_at,
        material_count=material_count,
        question_count=question_count,
    )


def _material_from_model(model: MaterialModel) -> Material:
    return Material(
        id=model.id,
        knowledge_base_id=model.knowledge_base_id,
        title=model.title,
        original_filename=model.original_filename,
        media_type=model.media_type,
        storage_uri=model.storage_uri,
        sha256=model.sha256,
        size_bytes=model.size_bytes,
        language=model.language,
        parse_status=model.parse_status,
        parser_version=model.parser_version,
        error_message=model.error_message,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _job_from_model(model: IngestionJobModel) -> IngestionJob:
    return IngestionJob(
        id=model.id,
        material_id=model.material_id,
        status=model.status,
        stage=model.stage,
        progress=model.progress,
        generation_config=model.generation_config,
        error_code=model.error_code,
        error_message=model.error_message,
        started_at=model.started_at,
        finished_at=model.finished_at,
        created_at=model.created_at,
    )


def _question_job_from_model(model: QuestionGenerationJobModel) -> QuestionGenerationJob:
    return QuestionGenerationJob(
        id=model.id,
        material_id=model.material_id,
        status=model.status,
        stage=model.stage,
        progress=model.progress,
        target_question_count=model.target_question_count,
        allowed_types=model.allowed_types,
        difficulty_min=model.difficulty_min,
        difficulty_max=model.difficulty_max,
        language=model.language,
        generated_count=model.generated_count,
        rejected_count=model.rejected_count,
        rejected_candidates=model.rejected_candidates,
        error_code=model.error_code,
        error_message=model.error_message,
        started_at=model.started_at,
        finished_at=model.finished_at,
        created_at=model.created_at,
    )


def _question_from_model(model: QuestionModel, sources: Sequence[QuestionSource] = ()) -> Question:
    return Question(
        id=model.id,
        knowledge_base_id=model.knowledge_base_id,
        knowledge_point_id=model.knowledge_point_id,
        question_type=model.question_type,
        stem=model.stem,
        options=model.options,
        correct_answer=model.correct_answer,
        scoring_points=model.scoring_points,
        explanation=model.explanation,
        difficulty=model.difficulty,
        max_score=float(model.max_score),
        status=model.status,
        content_hash=model.content_hash,
        vector_id=model.vector_id,
        sources=list(sources),
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _study_session_from_model(model: StudySessionModel) -> StudySession:
    return StudySession(
        id=model.id,
        knowledge_base_id=model.knowledge_base_id,
        mode=model.mode,
        status=model.status,
        planned_question_count=model.planned_question_count,
        answered_question_count=model.answered_question_count,
        correct_count=model.correct_count,
        incorrect_count=model.incorrect_count,
        total_score=float(model.total_score),
        max_total_score=float(model.max_total_score),
        question_types=model.question_types,
        difficulty_min=model.difficulty_min,
        difficulty_max=model.difficulty_max,
        started_at=model.started_at,
        finished_at=model.finished_at,
    )


def _answer_from_model(model: AnswerRecordModel) -> AnswerRecord:
    return AnswerRecord(
        id=model.id,
        submission_id=model.submission_id,
        session_id=model.session_id,
        question_id=model.question_id,
        knowledge_point_id=model.knowledge_point_id,
        answer=model.answer,
        score=float(model.score),
        max_score=float(model.max_score),
        verdict=model.verdict,
        feedback=model.feedback,
        elapsed_seconds=model.elapsed_seconds,
        answered_at=model.answered_at,
        explanation_data=model.explanation_data,
    )


def _mastery_from_model(model: MasteryRecordModel) -> MasteryRecord:
    return MasteryRecord(
        knowledge_point_id=model.knowledge_point_id,
        knowledge_base_id=model.knowledge_base_id,
        mastery_score=float(model.mastery_score),
        answered_count=model.answered_count,
        correct_count=model.correct_count,
        recent_accuracy=float(model.recent_accuracy),
        confidence=float(model.confidence),
        updated_at=model.updated_at,
    )


def _review_from_model(model: ReviewTaskModel) -> ReviewTask:
    return ReviewTask(
        id=model.id,
        knowledge_point_id=model.knowledge_point_id,
        knowledge_base_id=model.knowledge_base_id,
        due_at=model.due_at,
        interval_days=model.interval_days,
        repetitions=model.repetitions,
        ease_factor=float(model.ease_factor),
        last_quality=model.last_quality,
        status=model.status,
        updated_at=model.updated_at,
    )


class SqlAlchemyKnowledgeBaseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, knowledge_base: KnowledgeBase) -> KnowledgeBase:
        model = KnowledgeBaseModel(
            id=knowledge_base.id,
            name=knowledge_base.name,
            description=knowledge_base.description,
            language=knowledge_base.language,
            status=knowledge_base.status,
            created_at=knowledge_base.created_at,
            updated_at=knowledge_base.updated_at,
        )
        self.session.add(model)
        await self.session.flush()
        return _knowledge_base_from_model(model)

    async def get(self, knowledge_base_id: UUID) -> KnowledgeBase | None:
        stmt = (
            select(
                KnowledgeBaseModel,
                func.count(func.distinct(MaterialModel.id)).label("material_count"),
                func.count(func.distinct(QuestionModel.id)).label("question_count"),
            )
            .outerjoin(MaterialModel, MaterialModel.knowledge_base_id == KnowledgeBaseModel.id)
            .outerjoin(
                QuestionModel,
                (QuestionModel.knowledge_base_id == KnowledgeBaseModel.id)
                & (QuestionModel.status != "deleted"),
            )
            .where(
                KnowledgeBaseModel.id == knowledge_base_id,
                KnowledgeBaseModel.status != "deleted",
            )
            .group_by(KnowledgeBaseModel.id)
        )
        row = (await self.session.execute(stmt)).one_or_none()
        if row is None:
            return None
        return _knowledge_base_from_model(
            row[0], material_count=int(row.material_count), question_count=int(row.question_count)
        )

    async def list(
        self, *, page: int, page_size: int, status: str | None, keyword: str | None
    ) -> tuple[Sequence[KnowledgeBase], int]:
        filters = [KnowledgeBaseModel.status != "deleted"]
        if status is not None:
            filters.append(KnowledgeBaseModel.status == status)
        if keyword:
            filters.append(KnowledgeBaseModel.name.ilike(f"%{keyword}%"))

        total_stmt = select(func.count()).select_from(KnowledgeBaseModel).where(*filters)
        total = int((await self.session.scalar(total_stmt)) or 0)
        material_count = (
            select(func.count(MaterialModel.id))
            .where(MaterialModel.knowledge_base_id == KnowledgeBaseModel.id)
            .correlate(KnowledgeBaseModel)
            .scalar_subquery()
        )
        question_count = (
            select(func.count(QuestionModel.id))
            .where(
                QuestionModel.knowledge_base_id == KnowledgeBaseModel.id,
                QuestionModel.status != "deleted",
            )
            .correlate(KnowledgeBaseModel)
            .scalar_subquery()
        )
        stmt = (
            select(
                KnowledgeBaseModel,
                material_count.label("material_count"),
                question_count.label("question_count"),
            )
            .where(*filters)
            .order_by(KnowledgeBaseModel.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = (await self.session.execute(stmt)).all()
        return [
            _knowledge_base_from_model(
                row[0],
                material_count=int(row.material_count),
                question_count=int(row.question_count),
            )
            for row in rows
        ], total

    async def update(self, knowledge_base: KnowledgeBase) -> KnowledgeBase:
        model = await self.session.get(KnowledgeBaseModel, knowledge_base.id)
        if model is None:
            raise RuntimeError("knowledge base disappeared during update")
        model.name = knowledge_base.name
        model.description = knowledge_base.description
        model.language = knowledge_base.language
        model.status = knowledge_base.status
        model.updated_at = knowledge_base.updated_at
        await self.session.flush()
        return _knowledge_base_from_model(
            model,
            material_count=knowledge_base.material_count,
            question_count=knowledge_base.question_count,
        )


class SqlAlchemyMaterialRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, material: Material) -> Material:
        model = MaterialModel(
            id=material.id,
            knowledge_base_id=material.knowledge_base_id,
            title=material.title,
            original_filename=material.original_filename,
            media_type=material.media_type,
            storage_uri=material.storage_uri,
            sha256=material.sha256,
            size_bytes=material.size_bytes,
            language=material.language,
            parse_status=material.parse_status,
            parser_version=material.parser_version,
            error_message=material.error_message,
            created_at=material.created_at,
            updated_at=material.updated_at,
        )
        self.session.add(model)
        await self.session.flush()
        return _material_from_model(model)

    async def get(self, material_id: UUID) -> Material | None:
        model = await self.session.get(MaterialModel, material_id)
        return _material_from_model(model) if model else None

    async def get_by_hash(self, knowledge_base_id: UUID, sha256: str) -> Material | None:
        stmt = select(MaterialModel).where(
            MaterialModel.knowledge_base_id == knowledge_base_id,
            MaterialModel.sha256 == sha256,
        )
        model = await self.session.scalar(stmt)
        return _material_from_model(model) if model else None

    async def list(
        self, *, knowledge_base_id: UUID, page: int, page_size: int, status: str | None
    ) -> tuple[Sequence[Material], int]:
        filters = [MaterialModel.knowledge_base_id == knowledge_base_id]
        if status is not None:
            filters.append(MaterialModel.parse_status == status)
        total_stmt = select(func.count()).select_from(MaterialModel).where(*filters)
        total = int((await self.session.scalar(total_stmt)) or 0)
        stmt = (
            select(MaterialModel)
            .where(*filters)
            .order_by(MaterialModel.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        models = (await self.session.scalars(stmt)).all()
        return [_material_from_model(model) for model in models], total

    async def delete(self, material_id: UUID) -> None:
        model = await self.session.get(MaterialModel, material_id)
        if model is not None:
            await self.session.delete(model)
            await self.session.flush()


class SqlAlchemyIngestionJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, job: IngestionJob) -> IngestionJob:
        model = IngestionJobModel(
            id=job.id,
            material_id=job.material_id,
            status=job.status,
            stage=job.stage,
            progress=job.progress,
            generation_config=job.generation_config,
            error_code=job.error_code,
            error_message=job.error_message,
            started_at=job.started_at,
            finished_at=job.finished_at,
            created_at=job.created_at,
        )
        self.session.add(model)
        await self.session.flush()
        return _job_from_model(model)

    async def get(self, job_id: UUID) -> IngestionJob | None:
        model = await self.session.get(IngestionJobModel, job_id)
        return _job_from_model(model) if model else None

    async def has_running_for_material(self, material_id: UUID) -> bool:
        stmt = (
            select(func.count())
            .select_from(IngestionJobModel)
            .where(
                IngestionJobModel.material_id == material_id,
                IngestionJobModel.status.in_(["pending", "running"]),
            )
        )
        return int((await self.session.scalar(stmt)) or 0) > 0

    async def fail_dispatch(self, job_id: UUID) -> None:
        job = await self.session.get(IngestionJobModel, job_id)
        if job is not None:
            job.status = "failed"
            job.stage = "failed"
            job.error_code = "TASK_QUEUE_UNAVAILABLE"
            job.error_message = "任务派发失败，请重新处理资料"
            job.finished_at = datetime.now(UTC)
            material = await self.session.get(MaterialModel, job.material_id)
            if material is not None:
                material.parse_status = "failed"
                material.error_message = job.error_message
            await self.session.flush()


class SqlAlchemyDocumentChunkRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_material(self, material_id: UUID) -> Sequence[DocumentChunk]:
        stmt = (
            select(DocumentChunkModel)
            .where(DocumentChunkModel.material_id == material_id)
            .order_by(DocumentChunkModel.chunk_index)
        )
        models = (await self.session.scalars(stmt)).all()
        return [
            DocumentChunk(
                id=model.id,
                material_id=model.material_id,
                chunk_index=model.chunk_index,
                content=model.content,
                token_count=model.token_count,
                page_start=model.page_start,
                page_end=model.page_end,
                heading_path=model.heading_path,
                content_hash=model.content_hash,
                vector_id=model.vector_id,
                embedding_model=model.embedding_model,
                created_at=model.created_at,
            )
            for model in models
        ]


class SqlAlchemyQuestionGenerationJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, job: QuestionGenerationJob) -> QuestionGenerationJob:
        model = QuestionGenerationJobModel(
            id=job.id,
            material_id=job.material_id,
            status=job.status,
            stage=job.stage,
            progress=job.progress,
            target_question_count=job.target_question_count,
            allowed_types=job.allowed_types,
            difficulty_min=job.difficulty_min,
            difficulty_max=job.difficulty_max,
            language=job.language,
            generated_count=job.generated_count,
            rejected_count=job.rejected_count,
            rejected_candidates=job.rejected_candidates,
            error_code=job.error_code,
            error_message=job.error_message,
            started_at=job.started_at,
            finished_at=job.finished_at,
            created_at=job.created_at,
        )
        self.session.add(model)
        await self.session.flush()
        return _question_job_from_model(model)

    async def get(self, job_id: UUID) -> QuestionGenerationJob | None:
        model = await self.session.get(QuestionGenerationJobModel, job_id)
        return _question_job_from_model(model) if model else None

    async def list_for_material(self, material_id: UUID) -> Sequence[QuestionGenerationJob]:
        models = await self.session.scalars(
            select(QuestionGenerationJobModel)
            .where(QuestionGenerationJobModel.material_id == material_id)
            .order_by(QuestionGenerationJobModel.created_at.desc(), QuestionGenerationJobModel.id)
            .limit(5)
        )
        return [_question_job_from_model(model) for model in models]

    async def has_running_for_material(self, material_id: UUID) -> bool:
        stmt = (
            select(func.count())
            .select_from(QuestionGenerationJobModel)
            .where(
                QuestionGenerationJobModel.material_id == material_id,
                QuestionGenerationJobModel.status.in_(["pending", "running"]),
            )
        )
        return int((await self.session.scalar(stmt)) or 0) > 0

    async def fail_dispatch(self, job_id: UUID) -> None:
        job = await self.session.get(QuestionGenerationJobModel, job_id)
        if job is not None:
            job.status = "failed"
            job.stage = "failed"
            job.error_code = "TASK_QUEUE_UNAVAILABLE"
            job.error_message = "任务派发失败，请重试生成"
            job.finished_at = datetime.now(UTC)
            await self.session.flush()


class SqlAlchemyQuestionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def invalidate_sources(self, chunk_ids: Sequence[UUID]) -> Sequence[Question]:
        affected = select(QuestionSourceModel.question_id).where(
            QuestionSourceModel.chunk_id.in_(chunk_ids)
        )
        has_source = (
            select(QuestionSourceModel.question_id)
            .where(QuestionSourceModel.question_id == QuestionModel.id)
            .exists()
        )
        lock_ids = list(
            (
                await self.session.scalars(
                    select(QuestionModel.id)
                    .where(QuestionModel.id.in_(affected) | ~has_source)
                    .order_by(QuestionModel.id)
                )
            ).all()
        )
        for question_id in lock_ids:
            await transaction_lock(self.session, question_id)
        if chunk_ids:
            await self.session.execute(
                delete(QuestionSourceModel).where(QuestionSourceModel.chunk_id.in_(chunk_ids))
            )
        orphaned = list(
            (
                await self.session.scalars(
                    select(QuestionModel)
                    .where(
                        ~select(QuestionSourceModel.question_id)
                        .where(QuestionSourceModel.question_id == QuestionModel.id)
                        .exists(),
                        (QuestionModel.status == "active") | (QuestionModel.vector_id.is_not(None)),
                    )
                    .with_for_update()
                )
            ).all()
        )
        for model in orphaned:
            if model.status == "active":
                model.status = "disabled"
                model.updated_at = datetime.now(UTC)
        await self.session.flush()
        return [_question_from_model(model, []) for model in orphaned]

    async def _sources(self, question_ids: Sequence[UUID]) -> dict[UUID, list[QuestionSource]]:
        if not question_ids:
            return {}
        stmt = (
            select(QuestionSourceModel)
            .where(QuestionSourceModel.question_id.in_(question_ids))
            .order_by(QuestionSourceModel.question_id, QuestionSourceModel.rank)
        )
        result: dict[UUID, list[QuestionSource]] = {}
        for model in (await self.session.scalars(stmt)).all():
            result.setdefault(model.question_id, []).append(
                QuestionSource(chunk_id=model.chunk_id, quote=model.quote, rank=model.rank)
            )
        return result

    async def get(self, question_id: UUID) -> Question | None:
        model = await self.session.get(QuestionModel, question_id)
        if model is None:
            return None
        sources = await self._sources([question_id])
        return _question_from_model(model, sources.get(question_id, []))

    async def list(
        self,
        *,
        knowledge_base_id: UUID | None,
        material_id: UUID | None,
        question_type: str | None,
        status: str | None,
        page: int,
        page_size: int,
    ) -> tuple[Sequence[Question], int]:
        filters: list[ColumnElement[bool]] = [
            QuestionModel.status != "deleted",
            QuestionModel.knowledge_base_id.in_(
                select(KnowledgeBaseModel.id).where(KnowledgeBaseModel.status != "deleted")
            )
        ]
        if knowledge_base_id:
            filters.append(QuestionModel.knowledge_base_id == knowledge_base_id)
        if question_type:
            filters.append(QuestionModel.question_type == question_type)
        if status:
            filters.append(QuestionModel.status == status)
        id_query = select(QuestionModel.id, QuestionModel.created_at).where(*filters)
        if material_id:
            id_query = (
                id_query.join(QuestionSourceModel)
                .join(DocumentChunkModel)
                .where(DocumentChunkModel.material_id == material_id)
            )
        id_query = id_query.distinct()
        total = int(
            (await self.session.scalar(select(func.count()).select_from(id_query.subquery()))) or 0
        )
        page_ids = list(
            (
                await self.session.scalars(
                    id_query.order_by(QuestionModel.created_at.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        if not page_ids:
            return [], total
        models = list(
            (
                await self.session.scalars(
                    select(QuestionModel)
                    .where(QuestionModel.id.in_(page_ids))
                    .order_by(QuestionModel.created_at.desc())
                )
            ).all()
        )
        sources = await self._sources(page_ids)
        return [_question_from_model(model, sources.get(model.id, [])) for model in models], total

    async def update(self, question: Question) -> Question:
        model = await self.session.get(QuestionModel, question.id)
        if model is None:
            raise RuntimeError("question disappeared during update")
        model.stem = question.stem
        model.options = question.options
        model.correct_answer = question.correct_answer
        model.explanation = question.explanation
        model.difficulty = question.difficulty
        model.status = question.status
        model.content_hash = question.content_hash
        model.vector_id = question.vector_id
        model.updated_at = question.updated_at or model.updated_at
        await self.session.flush()
        await self.session.refresh(model)
        return _question_from_model(model, question.sources)

    async def list_active_candidates(
        self,
        *,
        knowledge_base_id: UUID,
        question_types: Sequence[str],
        difficulty_min: int,
        difficulty_max: int,
        limit: int | None,
    ) -> Sequence[Question]:
        stmt = (
            select(QuestionModel)
            .where(
                QuestionModel.knowledge_base_id == knowledge_base_id,
                QuestionModel.status == "active",
                QuestionModel.question_type.in_(question_types),
                QuestionModel.difficulty.between(difficulty_min, difficulty_max),
                select(QuestionSourceModel.question_id)
                .where(QuestionSourceModel.question_id == QuestionModel.id)
                .exists(),
            )
            .order_by(QuestionModel.difficulty, QuestionModel.created_at, QuestionModel.id)
            .limit(limit)
        )
        models = list((await self.session.scalars(stmt)).all())
        sources = await self._sources([model.id for model in models])
        return [_question_from_model(model, sources.get(model.id, [])) for model in models]


class SqlAlchemyStudySessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, study_session: StudySession) -> StudySession:
        model = StudySessionModel(
            id=study_session.id,
            knowledge_base_id=study_session.knowledge_base_id,
            mode=study_session.mode,
            status=study_session.status,
            planned_question_count=study_session.planned_question_count,
            answered_question_count=study_session.answered_question_count,
            correct_count=study_session.correct_count,
            incorrect_count=study_session.incorrect_count,
            total_score=study_session.total_score,
            max_total_score=study_session.max_total_score,
            question_types=study_session.question_types,
            difficulty_min=study_session.difficulty_min,
            difficulty_max=study_session.difficulty_max,
            started_at=study_session.started_at,
            finished_at=study_session.finished_at,
        )
        self.session.add(model)
        await self.session.flush()
        return _study_session_from_model(model)

    async def get(self, session_id: UUID) -> StudySession | None:
        model = await self.session.get(StudySessionModel, session_id)
        return _study_session_from_model(model) if model else None

    async def get_for_update(self, session_id: UUID) -> StudySession | None:
        model = await self.session.scalar(
            select(StudySessionModel)
            .where(StudySessionModel.id == session_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return _study_session_from_model(model) if model else None

    async def update(self, study_session: StudySession) -> StudySession:
        model = await self.session.get(StudySessionModel, study_session.id)
        if model is None:
            raise RuntimeError("study session disappeared during update")
        model.status = study_session.status
        model.answered_question_count = study_session.answered_question_count
        model.correct_count = study_session.correct_count
        model.incorrect_count = study_session.incorrect_count
        model.total_score = Decimal(str(study_session.total_score))
        model.max_total_score = Decimal(str(study_session.max_total_score))
        model.finished_at = study_session.finished_at
        await self.session.flush()
        return _study_session_from_model(model)

    async def add_questions(self, questions: Sequence[SessionQuestion]) -> None:
        self.session.add_all(
            [
                SessionQuestionModel(
                    session_id=item.session_id,
                    question_id=item.question_id,
                    sequence=item.sequence,
                    selection_reason=item.selection_reason,
                    priority_score=item.priority_score,
                )
                for item in questions
            ]
        )
        await self.session.flush()

    async def list_questions(self, session_id: UUID) -> Sequence[SessionQuestion]:
        stmt = (
            select(SessionQuestionModel)
            .where(SessionQuestionModel.session_id == session_id)
            .order_by(SessionQuestionModel.sequence)
        )
        return [
            SessionQuestion(
                session_id=model.session_id,
                question_id=model.question_id,
                sequence=model.sequence,
                selection_reason=model.selection_reason,
                priority_score=float(model.priority_score),
            )
            for model in (await self.session.scalars(stmt)).all()
        ]

    async def list(
        self, *, knowledge_base_id: UUID | None, page: int, page_size: int
    ) -> tuple[Sequence[StudySession], int]:
        filters = []
        if knowledge_base_id:
            filters.append(StudySessionModel.knowledge_base_id == knowledge_base_id)
        total = int(
            (
                await self.session.scalar(
                    select(func.count()).select_from(StudySessionModel).where(*filters)
                )
            )
            or 0
        )
        stmt = (
            select(StudySessionModel)
            .where(*filters)
            .order_by(StudySessionModel.started_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return [
            _study_session_from_model(model) for model in (await self.session.scalars(stmt)).all()
        ], total


class SqlAlchemyAnswerRecordRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, answer: AnswerRecord) -> AnswerRecord:
        model = AnswerRecordModel(
            id=answer.id,
            submission_id=answer.submission_id,
            session_id=answer.session_id,
            question_id=answer.question_id,
            knowledge_point_id=answer.knowledge_point_id,
            answer=answer.answer,
            score=answer.score,
            max_score=answer.max_score,
            verdict=answer.verdict,
            feedback=answer.feedback,
            elapsed_seconds=answer.elapsed_seconds,
            answered_at=answer.answered_at,
            explanation_data=answer.explanation_data,
        )
        self.session.add(model)
        await self.session.flush()
        return _answer_from_model(model)

    async def get_by_submission(self, submission_id: UUID) -> AnswerRecord | None:
        model = await self.session.scalar(
            select(AnswerRecordModel).where(AnswerRecordModel.submission_id == submission_id)
        )
        return _answer_from_model(model) if model else None

    async def update_explanation(
        self, answer_id: UUID, explanation_data: dict[str, object]
    ) -> AnswerRecord:
        model = await self.session.get(AnswerRecordModel, answer_id)
        if model is None:
            raise RuntimeError("answer record disappeared during explanation update")
        model.explanation_data = explanation_data
        await self.session.flush()
        return _answer_from_model(model)

    async def list_answered_question_ids(self, knowledge_base_id: UUID) -> set[UUID]:
        stmt = (
            select(AnswerRecordModel.question_id)
            .join(StudySessionModel, StudySessionModel.id == AnswerRecordModel.session_id)
            .where(StudySessionModel.knowledge_base_id == knowledge_base_id)
            .distinct()
        )
        return set((await self.session.scalars(stmt)).all())

    async def list_for_session(self, session_id: UUID) -> Sequence[AnswerRecord]:
        stmt = (
            select(AnswerRecordModel)
            .where(AnswerRecordModel.session_id == session_id)
            .order_by(AnswerRecordModel.answered_at)
        )
        return [_answer_from_model(model) for model in (await self.session.scalars(stmt)).all()]


class SqlAlchemyMasteryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, knowledge_point_id: UUID) -> MasteryRecord | None:
        model = await self.session.get(MasteryRecordModel, knowledge_point_id)
        return _mastery_from_model(model) if model else None

    async def upsert(self, record: MasteryRecord) -> MasteryRecord:
        model = await self.session.get(MasteryRecordModel, record.knowledge_point_id)
        if model is None:
            model = MasteryRecordModel(
                knowledge_point_id=record.knowledge_point_id,
                knowledge_base_id=record.knowledge_base_id,
                mastery_score=record.mastery_score,
                answered_count=record.answered_count,
                correct_count=record.correct_count,
                recent_accuracy=record.recent_accuracy,
                confidence=record.confidence,
                updated_at=record.updated_at,
            )
            self.session.add(model)
        else:
            model.mastery_score = Decimal(str(record.mastery_score))
            model.answered_count = record.answered_count
            model.correct_count = record.correct_count
            model.recent_accuracy = Decimal(str(record.recent_accuracy))
            model.confidence = Decimal(str(record.confidence))
            model.updated_at = record.updated_at
        await self.session.flush()
        return _mastery_from_model(model)

    async def list(self, knowledge_base_id: UUID | None) -> Sequence[MasteryRecord]:
        stmt = select(MasteryRecordModel)
        if knowledge_base_id:
            stmt = stmt.where(MasteryRecordModel.knowledge_base_id == knowledge_base_id)
        stmt = stmt.order_by(MasteryRecordModel.mastery_score, MasteryRecordModel.updated_at.desc())
        return [_mastery_from_model(model) for model in (await self.session.scalars(stmt)).all()]


class SqlAlchemyReviewTaskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_knowledge_point(self, knowledge_point_id: UUID) -> ReviewTask | None:
        model = await self.session.scalar(
            select(ReviewTaskModel).where(ReviewTaskModel.knowledge_point_id == knowledge_point_id)
        )
        return _review_from_model(model) if model else None

    async def upsert(self, task: ReviewTask) -> ReviewTask:
        model = await self.session.scalar(
            select(ReviewTaskModel).where(
                ReviewTaskModel.knowledge_point_id == task.knowledge_point_id
            )
        )
        if model is None:
            model = ReviewTaskModel(
                id=task.id,
                knowledge_point_id=task.knowledge_point_id,
                knowledge_base_id=task.knowledge_base_id,
                due_at=task.due_at,
                interval_days=task.interval_days,
                repetitions=task.repetitions,
                ease_factor=task.ease_factor,
                last_quality=task.last_quality,
                status=task.status,
                updated_at=task.updated_at,
            )
            self.session.add(model)
        else:
            model.due_at = task.due_at
            model.interval_days = task.interval_days
            model.repetitions = task.repetitions
            model.ease_factor = Decimal(str(task.ease_factor))
            model.last_quality = task.last_quality
            model.status = task.status
            model.updated_at = task.updated_at
        await self.session.flush()
        return _review_from_model(model)

    async def list_due(
        self, *, knowledge_base_id: UUID | None, due_before: datetime
    ) -> Sequence[ReviewTask]:
        filters = [ReviewTaskModel.status == "pending", ReviewTaskModel.due_at <= due_before]
        if knowledge_base_id:
            filters.append(ReviewTaskModel.knowledge_base_id == knowledge_base_id)
        stmt = select(ReviewTaskModel).where(*filters).order_by(ReviewTaskModel.due_at)
        return [_review_from_model(model) for model in (await self.session.scalars(stmt)).all()]
