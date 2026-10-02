from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TutorAnswerDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["answered", "needs_clarification", "insufficient_evidence"]
    answer: str = Field(min_length=1, max_length=4000)
    citation_ids: list[str] = Field(default_factory=list, max_length=10)
    suggested_questions: list[str] = Field(default_factory=list, max_length=3)
    study_suggestions: list[str] = Field(default_factory=list, max_length=5)
