"""Select small, bounded contexts and attach the exact text supplied to the model."""

from dataclasses import dataclass, replace

from study_agent.domain.models import DocumentChunk
from study_agent.question_generation.schemas import GeneratedQuestionDraft, SourcedQuestionDraft

# 控制模型调用量和每题参考片段数量，个人项目保持小组出题即可。
MAX_CONTEXT_GROUPS = 3
MAX_CHUNKS_PER_GROUP = 4


# 一组实际用于出题的原文和本组目标题数，后端用它绑定来源。
@dataclass(slots=True)
class GenerationGroup:
    chunks: list[DocumentChunk]
    context: str
    target_count: int


# 最多选三组前、中、后部原文，总长度受配置限制；长片段只绑定实际送给模型的部分。
def plan_generation_groups(
    chunks: list[DocumentChunk], *, target_count: int, max_chars: int
) -> list[GenerationGroup]:
    """Sample beginning/middle/end windows, at most three calls per generation round.

    The configured budget covers all groups combined, including headings/separators.
    A truncated chunk is bound with the same excerpt the model actually receives.
    """
    available = sorted(
        (chunk for chunk in chunks if chunk.content.strip()), key=lambda chunk: chunk.chunk_index
    )
    if not available:
        raise ValueError("资料没有可用于出题的原文")
    group_count = min(
        MAX_CONTEXT_GROUPS,
        target_count,
        (len(available) + MAX_CHUNKS_PER_GROUP - 1) // MAX_CHUNKS_PER_GROUP,
    )
    if group_count < 1 or max_chars < 100 * group_count:
        raise ValueError("出题数量或上下文预算过小")
    width = min(MAX_CHUNKS_PER_GROUP, len(available))
    quota, remainder = divmod(target_count, group_count)
    groups: list[GenerationGroup] = []
    for index in range(group_count):
        start = (
            round(index * (len(available) - width) / (group_count - 1)) if group_count > 1 else 0
        )
        budget = max_chars // group_count
        selected: list[DocumentChunk] = []
        sections: list[str] = []
        for chunk in available[start : start + width]:
            heading = " / ".join(chunk.heading_path) or "无标题"
            header = f"[标题={heading}; 页码={chunk.page_start or '未知'}]\n"
            remaining = budget - len(header) - (2 if sections else 0)
            if remaining <= 0:
                break
            content = chunk.content[:remaining]
            section = header + content
            selected.append(replace(chunk, content=content))
            sections.append(section)
            budget -= len(section) + (2 if len(sections) > 1 else 0)
            if len(content) < len(chunk.content):
                break
        if not selected:
            raise ValueError("原文标题过长，无法在上下文预算内出题")
        groups.append(
            GenerationGroup(
                chunks=selected,
                context="\n\n".join(sections),
                target_count=quota + (index < remainder),
            )
        )
    return groups


# 忽略模型自行返回的来源信息，把本组实际输入的原文绑定到题目。
def bind_question_context(
    question: GeneratedQuestionDraft, group: GenerationGroup
) -> SourcedQuestionDraft:
    # Construct from the parsed content schema, overriding any unsolicited model sources.
    return SourcedQuestionDraft(
        **question.model_dump(),
        source_chunk_ids=[chunk.id for chunk in group.chunks],
        source_quotes=[chunk.content for chunk in group.chunks],
    )
