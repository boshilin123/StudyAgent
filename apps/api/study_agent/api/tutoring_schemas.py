from datetime import datetime
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CreateTutorConversation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    knowledge_base_id: UUID
    study_session_id: UUID | None = None
    answered_question_id: UUID | None = None

    @model_validator(mode="after")
    def validate_anchor(self) -> Self:
        if bool(self.study_session_id) != bool(self.answered_question_id):
            raise ValueError("答后辅导必须同时绑定学习会话和已答题目")
        return self


class SubmitTutorMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_message_id: UUID
    content: str = Field(min_length=1, max_length=2000)
    intent: Literal["materials", "answered_question", "progress", "mistakes", "general"] = (
        "materials"
    )

    @model_validator(mode="after")
    def nonblank(self) -> Self:
        if not self.content.strip():
            raise ValueError("问题不能为空")
        return self


class TutorConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    knowledge_base_id: UUID
    study_session_id: UUID | None
    answered_question_id: UUID | None
    status: str
    created_at: datetime


class TutorMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    turn_id: UUID
    sequence: int
    role: str
    content: str
    citations: list[dict[str, Any]]
    created_at: datetime
