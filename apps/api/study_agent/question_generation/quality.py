import re
from dataclasses import dataclass

from study_agent.domain.models import DocumentChunk
from study_agent.question_generation.schemas import KnowledgePointDraft, SourcedQuestionDraft


# 保留基础校验未通过的候选题和原因，不让它进入练习题库。
@dataclass(slots=True)
class RejectedQuestion:
    question: SourcedQuestionDraft
    reason: str


def _normalize(value: str) -> str:
    return re.sub(r"\s+", "", value).lower()


# 检查题型、难度、知识点和重复内容；引用已由后端管理，这里不再逐字匹配引文。
def validate_question_drafts(
    *,
    knowledge_points: list[KnowledgePointDraft],
    questions: list[SourcedQuestionDraft],
    chunks: list[DocumentChunk],
    allowed_types: set[str],
    difficulty_min: int,
    difficulty_max: int,
    seen_stems: set[str] | None = None,
) -> tuple[list[SourcedQuestionDraft], list[RejectedQuestion]]:
    chunk_map = {chunk.id: chunk for chunk in chunks}
    point_keys = {point.canonical_key for point in knowledge_points}
    accepted: list[SourcedQuestionDraft] = []
    rejected: list[RejectedQuestion] = []
    if seen_stems is None:
        seen_stems = set()

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


# Compatibility alias; remove with the next internal interface cleanup.
validate_generation = validate_question_drafts
