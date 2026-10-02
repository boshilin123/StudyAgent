from typing import Any

from study_agent.agents.tutor.schemas import TutorAnswerDraft
from study_agent.domain.errors import DomainError


def validate_draft(
    draft: TutorAnswerDraft, state: dict[str, Any], intent: str, anchored: bool
) -> list[dict[str, Any]]:
    flags = set(state.get("evidence_flags", []))
    required = {"answered_question"} if anchored else set()
    required |= {"progress": {"progress"}, "mistakes": {"progress", "mistakes"}}.get(intent, set())
    if draft.status != "needs_clarification" and not required.issubset(flags):
        raise DomainError(
            "TUTOR_REQUIRED_TOOL_MISSING", "回答未读取必需的最新学习记录", status_code=503
        )
    ledger = state.get("evidence", {})
    if (
        draft.status == "insufficient_evidence"
        and intent == "materials"
        and "materials" not in flags
    ):
        raise DomainError(
            "TUTOR_REQUIRED_TOOL_MISSING",
            "尚未检索资料，不能判定当前知识库证据不足",
            status_code=503,
        )
    citations = []
    for key in dict.fromkeys(draft.citation_ids):
        if key not in ledger:
            raise DomainError("TUTOR_INVALID_CITATION", "回答包含未经取证的引用", status_code=503)
        citations.append(ledger[key])
    if (
        draft.status == "answered"
        and intent in {"materials", "answered_question"}
        and not citations
    ):
        raise DomainError(
            "TUTOR_INSUFFICIENT_EVIDENCE", "资料回答缺少本轮有效依据", status_code=503
        )
    if draft.status == "answered" and intent in {"progress", "mistakes"} and "no_history" in flags:
        raise DomainError(
            "TUTOR_NO_LEARNING_HISTORY", "没有学习记录，不能形成个性化诊断", status_code=503
        )
    return citations
