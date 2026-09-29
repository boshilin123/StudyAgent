import re
from dataclasses import dataclass

from study_agent.domain.models import DocumentChunk
from study_agent.question_generation.schemas import GeneratedQuestionDraft, KnowledgePointDraft


@dataclass(slots=True)
class RejectedQuestion:
    question: GeneratedQuestionDraft
    reason: str


def _normalize(value: str) -> str:
    return re.sub(r"\s+", "", value).lower()


def validate_generation(
    *,
    knowledge_points: list[KnowledgePointDraft],
    questions: list[GeneratedQuestionDraft],
    chunks: list[DocumentChunk],
    allowed_types: set[str],
    difficulty_min: int,
    difficulty_max: int,
) -> tuple[list[GeneratedQuestionDraft], list[RejectedQuestion]]:
    chunk_map = {chunk.id: chunk for chunk in chunks}
    point_keys = {point.canonical_key for point in knowledge_points}
    accepted: list[GeneratedQuestionDraft] = []
    rejected: list[RejectedQuestion] = []
    seen_stems: set[str] = set()

    for question in questions:
        reason: str | None = None
        if question.question_type not in allowed_types:
            reason = "题型不在请求范围内"
        elif question.knowledge_point_key not in point_keys:
            reason = "知识点不存在"
        elif not difficulty_min <= question.difficulty <= difficulty_max:
            reason = "难度超出请求范围"
        elif any(chunk_id not in chunk_map for chunk_id in question.source_chunk_ids):
            reason = "引用了不存在的片段"
        elif len(question.source_chunk_ids) != len(question.source_quotes):
            reason = "片段与引文数量不一致"
        else:
            for chunk_id, quote in zip(
                question.source_chunk_ids, question.source_quotes, strict=True
            ):
                if _normalize(quote) not in _normalize(chunk_map[chunk_id].content):
                    reason = "引文无法在原文片段中匹配"
                    break

        normalized_stem = _normalize(question.stem)
        if reason is None and normalized_stem in seen_stems:
            reason = "同批次题干重复"
        if reason is None and question.question_type == "single_choice":
            option_texts = {_normalize(option.text) for option in question.options or []}
            if len(option_texts) != 4:
                reason = "单选题选项重复"
        if (
            reason is None
            and question.question_type == "fill_blank"
            and any(len(answer) > 100 for answer in question.correct_answers)
        ):
            reason = "填空题答案过长"

        if reason:
            rejected.append(RejectedQuestion(question=question, reason=reason))
        else:
            seen_stems.add(normalized_stem)
            accepted.append(question)
    return accepted, rejected
