from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class TutorContext:
    conversation_id: UUID
    turn_id: UUID
    knowledge_base_id: UUID
    study_session_id: UUID | None = None
    answered_question_id: UUID | None = None
    scope_key: str = "single-user"
    intent: str = "materials"
