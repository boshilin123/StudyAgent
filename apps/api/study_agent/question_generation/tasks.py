import asyncio
import json
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from celery import Task
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from study_agent.application.questions import question_content_hash
from study_agent.config import get_settings
from study_agent.domain.models import DocumentChunk
from study_agent.infrastructure.models import (
    DocumentChunkModel,
    KnowledgeBaseModel,
    KnowledgePointModel,
    KnowledgePointSourceModel,
    MaterialModel,
    QuestionGenerationJobModel,
    QuestionModel,
    QuestionSourceModel,
    WorkflowRunModel,
    WorkflowStepModel,
)
from study_agent.question_generation.chains import (
    PROMPT_VERSION,
    create_knowledge_point_chain,
    create_question_generation_chain,
    serialize_knowledge_points,
)
from study_agent.question_generation.context import bind_question_context, plan_generation_groups
from study_agent.question_generation.factory import get_question_index
from study_agent.question_generation.quality import RejectedQuestion, validate_question_drafts
from study_agent.question_generation.schemas import (
    KnowledgePointBatch,
    SourcedKnowledgePointBatch,
    SourcedKnowledgePointDraft,
    SourcedQuestionDraft,
)
from study_agent.worker import celery_app


async def _with_session(operation: Any) -> Any:
    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            return await operation(session)
    finally:
        await engine.dispose()


async def _mark_failed(job_id: UUID, message: str) -> None:
    async def operation(session: Any) -> None:
        job = await session.get(QuestionGenerationJobModel, job_id)
        if job:
            job.status = "failed"
            job.stage = "failed"
            job.error_code = "QUESTION_GENERATION_FAILED"
            job.error_message = message[:2000]
            job.finished_at = datetime.now(UTC)
            runs = list(
                (
                    await session.scalars(
                        select(WorkflowRunModel).where(
                            WorkflowRunModel.agent_type == "question_generation",
                            WorkflowRunModel.subject_id == job.material_id,
                            WorkflowRunModel.status == "running",
                            WorkflowRunModel.input_summary["job_id"].as_string() == str(job_id),
                        )
                    )
                ).all()
            )
            for run in runs:
                run.status = "failed"
                run.error_message = message[:2000]
                run.finished_at = datetime.now(UTC)
        await session.commit()

    await _with_session(operation)


# 后台出题任务发生执行异常时有限重试；基础校验拒绝不等于任务执行异常。
class QuestionGenerationTask(Task):
    autoretry_for = (Exception,)
    retry_backoff = True
    retry_kwargs = {"max_retries": 1}

    def on_failure(
        self,
        exc: BaseException,
        task_id: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        einfo: Any,
    ) -> None:
        if args:
            asyncio.run(_mark_failed(UUID(str(args[0])), str(exc)))
        super().on_failure(exc, task_id, args, kwargs, einfo)


def _to_chunk(model: DocumentChunkModel) -> DocumentChunk:
    return DocumentChunk(
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


# 按原文分组提取知识点和出题，绑定来源后保存草稿，题量不足时最多补充一次。
@celery_app.task(base=QuestionGenerationTask, name="study_agent.generate_questions")
def generate_questions(job_id: str, material_id: str) -> dict[str, object]:
    async def operation(session: Any) -> dict[str, object]:
        job_uuid = UUID(job_id)
        material_uuid = UUID(material_id)
        job = await session.get(QuestionGenerationJobModel, job_uuid)
        material = await session.get(MaterialModel, material_uuid)
        if job is None or material is None:
            raise ValueError("question generation job or material does not exist")
        if job.status in {"completed", "partial"}:
            return {
                "job_id": job_id,
                "generated_count": job.generated_count,
                "rejected_count": job.rejected_count,
            }
        knowledge_base = await session.get(KnowledgeBaseModel, material.knowledge_base_id)
        if knowledge_base is None or knowledge_base.status != "active":
            raise ValueError("知识库已归档或删除，不能生成题目")
        # Close an interrupted attempt's trace without declaring the whole job
        # failed (which would unblock another job while this one is retrying).
        previous_runs = (
            await session.scalars(
                select(WorkflowRunModel).where(
                    WorkflowRunModel.status == "running",
                    WorkflowRunModel.input_summary["job_id"].as_string() == job_id,
                )
            )
        ).all()
        for previous in previous_runs:
            previous.status = "failed"
            previous.error_message = "此前尝试中断，任务正在重试"
            previous.finished_at = datetime.now(UTC)
        settings = get_settings()
        job.status = "running"
        job.stage = "extracting_knowledge_points"
        job.progress = 10
        job.started_at = job.started_at or datetime.now(UTC)
        job.error_code = None
        job.error_message = None
        run = WorkflowRunModel(
            id=uuid4(),
            agent_type="question_generation",
            subject_type="material",
            subject_id=material_uuid,
            status="running",
            model=settings.llm_model,
            prompt_version=PROMPT_VERSION,
            input_summary={
                "job_id": job_id,
                "target_count": job.target_question_count,
                "execution_kind": "chain",
            },
            output_summary={},
            prompt_tokens=0,
            completion_tokens=0,
            started_at=datetime.now(UTC),
        )
        session.add(run)
        await session.commit()

        chunk_models = list(
            (
                await session.scalars(
                    select(DocumentChunkModel)
                    .where(DocumentChunkModel.material_id == material_uuid)
                    .order_by(DocumentChunkModel.chunk_index)
                )
            ).all()
        )
        chunks = [_to_chunk(model) for model in chunk_models]
        if not chunks:
            raise ValueError("material does not contain document chunks")
        groups = plan_generation_groups(
            chunks,
            target_count=job.target_question_count,
            max_chars=settings.question_generation_max_context_chars,
        )

        started = datetime.now(UTC)
        group_points: list[KnowledgePointBatch] = []
        sourced_points: list[SourcedKnowledgePointDraft] = []
        for group in groups:
            points = await asyncio.to_thread(
                create_knowledge_point_chain(settings).invoke,
                {"language": job.language, "context": group.context},
            )
            group_points.append(points)
            sourced_points.extend(
                SourcedKnowledgePointDraft(
                    **point.model_dump(), source_chunk_ids=[chunk.id for chunk in group.chunks]
                )
                for point in points.items
            )
        point_batch = SourcedKnowledgePointBatch(items=sourced_points)
        session.add(
            WorkflowStepModel(
                id=uuid4(),
                run_id=run.id,
                sequence=1,
                node_name="extract_knowledge_points",
                tool_name=None,
                input_summary={
                    "chunk_count": len(chunks),
                    "context_group_count": len(groups),
                    "context_chars": sum(len(group.context) for group in groups),
                    "source_kind": "reference_context",
                    "execution_kind": "chain",
                },
                output_summary={"knowledge_point_count": len(point_batch.items)},
                status="completed",
                duration_ms=int((datetime.now(UTC) - started).total_seconds() * 1000),
            )
        )
        job.stage = "generating_questions"
        job.progress = 45
        await session.commit()

        started = datetime.now(UTC)
        accepted: list[SourcedQuestionDraft] = []
        rejected: list[RejectedQuestion] = []
        seen_stems: set[str] = set()
        generation_calls = 0

        async def generate_group(index: int, count: int) -> None:
            nonlocal generation_calls
            group = groups[index]
            points = group_points[index]
            generation_calls += 1
            batch = await asyncio.to_thread(
                create_question_generation_chain(settings).invoke,
                {
                    "target_count": count,
                    "allowed_types": ", ".join(job.allowed_types),
                    "difficulty_min": job.difficulty_min,
                    "difficulty_max": job.difficulty_max,
                    "language": job.language,
                    "knowledge_points": serialize_knowledge_points(points),
                    "context": group.context,
                    "existing_stems": json.dumps(
                        [item.stem for item in accepted], ensure_ascii=False
                    ),
                },
            )
            valid, invalid = validate_question_drafts(
                knowledge_points=points.items,
                questions=[bind_question_context(item, group) for item in batch.items],
                chunks=group.chunks,
                allowed_types=set(job.allowed_types),
                difficulty_min=job.difficulty_min,
                difficulty_max=job.difficulty_max,
                seen_stems=seen_stems,
            )
            accepted.extend(valid[:count])
            rejected.extend(invalid)

        for index, group in enumerate(groups):
            await generate_group(index, group.target_count)
        supplemental_count = max(0, job.target_question_count - len(accepted))
        supplement_error: str | None = None
        if supplemental_count:
            # 补充请求失败也保留首轮有效题，避免额外调用拖垮已经完成的出题。
            try:
                await generate_group(0, supplemental_count)
            except Exception as exc:
                supplement_error = type(exc).__name__
        # Validation failures remain outside the question bank, but are retained for review.
        job.rejected_candidates = [
            {"reason": item.reason, "question": item.question.model_dump(mode="json")}
            for item in rejected
        ]
        session.add(
            WorkflowStepModel(
                id=uuid4(),
                run_id=run.id,
                sequence=2,
                node_name="generate_and_validate_questions",
                tool_name=None,
                input_summary={
                    "target_count": job.target_question_count,
                    "execution_kind": "chain",
                    "generation_calls": generation_calls,
                    "supplemental_count": supplemental_count,
                },
                output_summary={
                    "accepted": len(accepted),
                    "rejected": len(rejected),
                    "rejected_reasons": dict(Counter(item.reason for item in rejected)),
                    "supplement_error": supplement_error,
                },
                status="completed",
                duration_ms=int((datetime.now(UTC) - started).total_seconds() * 1000),
            )
        )
        job.stage = "persisting"
        job.progress = 75
        await session.commit()

        current_base = await session.scalar(
            select(KnowledgeBaseModel)
            .where(KnowledgeBaseModel.id == material.knowledge_base_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if current_base is None or current_base.status != "active":
            raise ValueError("知识库已归档或删除，不能保存新题目")

        chunk_ids = {chunk.id for chunk in chunks}
        point_ids: dict[str, UUID] = {}
        for point in point_batch.items:
            canonical = " ".join(point.canonical_key.lower().split())
            existing = await session.scalar(
                select(KnowledgePointModel).where(
                    KnowledgePointModel.knowledge_base_id == material.knowledge_base_id,
                    KnowledgePointModel.canonical_key == canonical,
                )
            )
            if existing is None:
                existing = KnowledgePointModel(
                    id=uuid4(),
                    knowledge_base_id=material.knowledge_base_id,
                    name=point.name,
                    description=point.description,
                    canonical_key=canonical,
                    importance=Decimal(str(point.importance)),
                    difficulty=point.difficulty,
                    source="agent",
                    status="active",
                )
                session.add(existing)
                await session.flush()
            point_ids[point.canonical_key] = existing.id
            for chunk_id in dict.fromkeys(point.source_chunk_ids):
                if chunk_id not in chunk_ids:
                    continue
                source = await session.get(
                    KnowledgePointSourceModel,
                    {"knowledge_point_id": existing.id, "chunk_id": chunk_id},
                )
                if source is None:
                    session.add(
                        KnowledgePointSourceModel(
                            knowledge_point_id=existing.id,
                            chunk_id=chunk_id,
                            relevance=Decimal("1"),
                        )
                    )

        saved_models: list[QuestionModel] = []
        for question in accepted[: job.target_question_count]:
            content_hash = question_content_hash(
                question.question_type, question.stem, question.correct_answers
            )
            duplicate = await session.scalar(
                select(QuestionModel)
                .where(
                    QuestionModel.knowledge_base_id == material.knowledge_base_id,
                    QuestionModel.content_hash == content_hash,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if duplicate is not None:
                if duplicate.status == "deleted":
                    job.rejected_candidates = [
                        *job.rejected_candidates,
                        {
                            "reason": "相同题目已被删除，本次不重新入库",
                            "question": question.model_dump(mode="json"),
                        },
                    ]
                    continue
                for rank, (chunk_id, quote) in enumerate(
                    zip(question.source_chunk_ids, question.source_quotes, strict=True), start=1
                ):
                    source = await session.get(
                        QuestionSourceModel,
                        {"question_id": duplicate.id, "chunk_id": chunk_id},
                    )
                    if source is None:
                        session.add(
                            QuestionSourceModel(
                                question_id=duplicate.id,
                                chunk_id=chunk_id,
                                quote=quote,
                                source_kind="reference_context",
                                rank=rank,
                            )
                        )
                    elif source.source_kind == "reference_context":
                        source.quote = quote
                        source.rank = rank
                        source.source_kind = "reference_context"
                saved_models.append(duplicate)
                continue
            model = QuestionModel(
                id=uuid4(),
                knowledge_base_id=material.knowledge_base_id,
                knowledge_point_id=point_ids[question.knowledge_point_key],
                question_type=question.question_type,
                stem=question.stem,
                options=[option.model_dump() for option in question.options]
                if question.options
                else None,
                correct_answer=question.correct_answers,
                scoring_points=[],
                explanation=question.explanation,
                difficulty=question.difficulty,
                max_score=Decimal("10"),
                status="draft",
                generation_run_id=run.id,
                content_hash=content_hash,
            )
            session.add(model)
            await session.flush()
            for rank, (chunk_id, quote) in enumerate(
                zip(question.source_chunk_ids, question.source_quotes, strict=True), start=1
            ):
                session.add(
                    QuestionSourceModel(
                        question_id=model.id,
                        chunk_id=chunk_id,
                        quote=quote,
                        source_kind="reference_context",
                        rank=rank,
                    )
                )
            saved_models.append(model)
        await session.commit()

        records = [
            {
                "id": str(model.id),
                "knowledge_base_id": str(model.knowledge_base_id),
                "knowledge_point_id": str(model.knowledge_point_id),
                "question_type": model.question_type,
                "difficulty": model.difficulty,
                "status": model.status,
                "content": f"{model.stem}\n答案：{model.correct_answer}\n解析：{model.explanation}",
            }
            for model in saved_models
        ]
        vector_ids = await get_question_index().upsert(records)
        for model, vector_id in zip(saved_models, vector_ids, strict=True):
            # Deletion can occur during vector indexing. Do not leave a stale vector
            # behind or restore a question the user just removed.
            current = await session.scalar(
                select(QuestionModel)
                .where(QuestionModel.id == model.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if current.status == "deleted":
                await get_question_index().delete_questions([current.id])
                current.vector_id = None
            else:
                current.vector_id = vector_id

        job.generated_count = len(saved_models)
        job.rejected_count = len(job.rejected_candidates)
        job.status = "completed" if job.generated_count >= job.target_question_count else "partial"
        if job.status == "partial":
            reasons = "；".join(
                f"{reason} {count} 道"
                for reason, count in Counter(
                    str(item["reason"]) for item in job.rejected_candidates
                ).items()
            )
            job.error_code = "QUESTION_GENERATION_PARTIAL"
            job.error_message = (
                f"目标 {job.target_question_count} 道，通过校验 {job.generated_count} 道，"
                f"拒绝 {job.rejected_count} 道。" + (reasons or "模型返回的有效题目不足目标数量")
            )
            if supplement_error:
                job.error_message += "；补充生成未完成，已保留本轮有效题目"
        job.stage = "completed"
        job.progress = 100
        job.finished_at = datetime.now(UTC)
        run.status = job.status
        run.output_summary = {
            "generated_count": job.generated_count,
            "rejected_count": job.rejected_count,
        }
        run.finished_at = datetime.now(UTC)
        await session.commit()
        return {
            "job_id": job_id,
            "generated_count": job.generated_count,
            "rejected_count": job.rejected_count,
        }

    return asyncio.run(_with_session(operation))
