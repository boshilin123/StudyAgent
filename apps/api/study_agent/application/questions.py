import builtins
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from study_agent.config import get_settings
from study_agent.domain.errors import DomainError
from study_agent.domain.models import Question, QuestionGenerationJob
from study_agent.domain.ports import QuestionGenerationDispatcher, QuestionIndex, UnitOfWork


def question_content_hash(question_type: str, stem: str, correct_answer: object) -> str:
    canonical = json.dumps(
        {
            "type": question_type,
            "stem": " ".join(stem.lower().split()),
            "answer": correct_answer,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_question_shape(question: Question) -> None:
    answers = question.correct_answer
    if not isinstance(answers, list) or not answers or not all(
        isinstance(answer, str) and answer.strip() for answer in answers
    ):
        raise DomainError("QUESTION_QUALITY_GATE_FAILED", "题目答案不能为空", status_code=422)
    if question.question_type == "single_choice":
        options = question.options or []
        keys = {option.get("key") for option in options}
        texts = {" ".join(option.get("text", "").lower().split()) for option in options}
        if len(options) != 4 or keys != {"A", "B", "C", "D"} or len(texts) != 4:
            raise DomainError(
                "QUESTION_QUALITY_GATE_FAILED",
                "单选题必须包含 A、B、C、D 四个互异选项",
                status_code=422,
            )
        if len(answers) != 1 or answers[0] not in keys:
            raise DomainError(
                "QUESTION_QUALITY_GATE_FAILED", "单选题必须且只能有一个合法答案", status_code=422
            )
    elif question.question_type == "true_false":
        if question.options or len(answers) != 1 or answers[0] not in {"正确", "错误"}:
            raise DomainError(
                "QUESTION_QUALITY_GATE_FAILED",
                "判断题不能包含选项，答案只能是正确或错误",
                status_code=422,
            )
    elif question.options:
        raise DomainError(
            "QUESTION_QUALITY_GATE_FAILED", "填空题不能包含选择项", status_code=422
        )


class QuestionService:
    async def create_generation_job(
        self,
        uow: UnitOfWork,
        dispatcher: QuestionGenerationDispatcher,
        *,
        material_id: UUID,
        target_question_count: int,
        allowed_types: list[str],
        difficulty_min: int,
        difficulty_max: int,
        language: str,
    ) -> QuestionGenerationJob:
        material = await uow.materials.get(material_id)
        if material is None:
            raise DomainError("MATERIAL_NOT_FOUND", "资料不存在", status_code=404)
        if material.parse_status != "ready":
            raise DomainError("MATERIAL_NOT_READY", "资料尚未完成解析和索引", status_code=409)
        if await uow.question_generation_jobs.has_running_for_material(material_id):
            raise DomainError(
                "QUESTION_GENERATION_RUNNING", "该资料已有运行中的题库生成任务", status_code=409
            )
        settings = get_settings()
        if not settings.llm_base_url or not settings.llm_model:
            raise DomainError(
                "LLM_NOT_CONFIGURED",
                "题库生成需要先配置 LLM_BASE_URL、LLM_MODEL 和可选的 LLM_API_KEY",
                status_code=503,
            )
        now = datetime.now(UTC)
        job = QuestionGenerationJob(
            id=uuid4(),
            material_id=material_id,
            status="pending",
            stage="queued",
            progress=0,
            target_question_count=target_question_count,
            allowed_types=allowed_types,
            difficulty_min=difficulty_min,
            difficulty_max=difficulty_max,
            language=language,
            created_at=now,
        )
        job = await uow.question_generation_jobs.add(job)
        await uow.commit()
        try:
            dispatcher.dispatch(job_id=job.id, material_id=material_id)
        except Exception as exc:
            raise DomainError(
                "TASK_QUEUE_UNAVAILABLE", "题库生成任务提交失败", status_code=503
            ) from exc
        return job

    async def get_generation_job(
        self, uow: UnitOfWork, job_id: UUID
    ) -> QuestionGenerationJob:
        job = await uow.question_generation_jobs.get(job_id)
        if job is None:
            raise DomainError(
                "QUESTION_GENERATION_JOB_NOT_FOUND", "题库生成任务不存在", status_code=404
            )
        return job

    async def get(self, uow: UnitOfWork, question_id: UUID) -> Question:
        question = await uow.questions.get(question_id)
        if question is None:
            raise DomainError("QUESTION_NOT_FOUND", "题目不存在", status_code=404)
        return question

    async def list(
        self,
        uow: UnitOfWork,
        *,
        knowledge_base_id: UUID | None,
        material_id: UUID | None,
        question_type: str | None,
        status: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[Question], int]:
        items, total = await uow.questions.list(
            knowledge_base_id=knowledge_base_id,
            material_id=material_id,
            question_type=question_type,
            status=status,
            page=page,
            page_size=page_size,
        )
        return list(items), total

    async def update(
        self,
        uow: UnitOfWork,
        question_index: QuestionIndex,
        question_id: UUID,
        *,
        stem: str | None = None,
        options: builtins.list[dict[str, str]] | None = None,
        correct_answers: builtins.list[str] | None = None,
        explanation: str | None = None,
        difficulty: int | None = None,
        options_is_set: bool = False,
    ) -> Question:
        current = await self.get(uow, question_id)
        updated = replace(
            current,
            stem=stem.strip() if stem is not None else current.stem,
            options=options if options_is_set else current.options,
            correct_answer=(
                correct_answers if correct_answers is not None else current.correct_answer
            ),
            explanation=explanation.strip() if explanation is not None else current.explanation,
            difficulty=difficulty if difficulty is not None else current.difficulty,
            status="draft" if current.status == "active" else current.status,
            updated_at=datetime.now(UTC),
        )
        updated = replace(
            updated,
            content_hash=question_content_hash(
                updated.question_type, updated.stem, updated.correct_answer
            ),
        )
        validate_question_shape(updated)
        vector_id = await question_index.upsert_question(updated)
        updated = replace(updated, vector_id=vector_id)
        result = await uow.questions.update(updated)
        await uow.commit()
        return result

    async def set_status(
        self, uow: UnitOfWork, question_index: QuestionIndex, question_id: UUID, status: str
    ) -> Question:
        current = await self.get(uow, question_id)
        validate_question_shape(current)
        if status == "active" and not current.sources:
            raise DomainError(
                "QUESTION_SOURCE_REQUIRED", "无真实来源片段的题目不能启用", status_code=409
            )
        updated = replace(current, status=status, updated_at=datetime.now(UTC))
        vector_id = await question_index.upsert_question(updated)
        result = await uow.questions.update(replace(updated, vector_id=vector_id))
        await uow.commit()
        return result
