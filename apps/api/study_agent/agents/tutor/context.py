from dataclasses import dataclass
from uuid import UUID


# 服务器确定的本轮知识库与作答范围，模型不能通过工具参数擅自切换。
@dataclass(frozen=True, slots=True)
class TutorContext:
    conversation_id: UUID
    turn_id: UUID
    knowledge_base_id: UUID
    study_session_id: UUID | None = None
    answered_question_id: UUID | None = None
    scope_key: str = "single-user"
    intent: str = "materials"
