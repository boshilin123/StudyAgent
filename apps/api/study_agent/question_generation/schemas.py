from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

QuestionType = Literal["single_choice", "fill_blank", "true_false"]


class KnowledgePointDraft(BaseModel):
    canonical_key: str = Field(min_length=2, max_length=300)
    name: str = Field(min_length=2, max_length=300)
    description: str = Field(min_length=5, max_length=2000)
    importance: float = Field(ge=0, le=1)
    difficulty: int = Field(ge=1, le=5)
    source_chunk_ids: list[UUID] = Field(min_length=1, max_length=5)


class KnowledgePointBatch(BaseModel):
    items: list[KnowledgePointDraft] = Field(min_length=1, max_length=30)


class QuestionOption(BaseModel):
    key: Literal["A", "B", "C", "D"]
    text: str = Field(min_length=1, max_length=500)


class GeneratedQuestionDraft(BaseModel):
    knowledge_point_key: str = Field(min_length=2, max_length=300)
    question_type: QuestionType
    stem: str = Field(min_length=5, max_length=1000)
    options: list[QuestionOption] | None = None
    correct_answers: list[str] = Field(min_length=1, max_length=10)
    explanation: str = Field(min_length=5, max_length=3000)
    difficulty: int = Field(ge=1, le=5)
    source_chunk_ids: list[UUID] = Field(min_length=1, max_length=5)
    source_quotes: list[str] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def validate_type_shape(self) -> "GeneratedQuestionDraft":
        if self.question_type == "single_choice":
            if self.options is None or len(self.options) != 4:
                raise ValueError("单选题必须包含 A、B、C、D 四个选项")
            if {option.key for option in self.options} != {"A", "B", "C", "D"}:
                raise ValueError("单选题选项键必须为 A、B、C、D")
            if len(self.correct_answers) != 1 or self.correct_answers[0] not in {
                "A",
                "B",
                "C",
                "D",
            }:
                raise ValueError("单选题必须且只能有一个正确选项")
        elif self.question_type == "true_false":
            self.options = None
            if len(self.correct_answers) != 1 or self.correct_answers[0] not in {
                "正确",
                "错误",
            }:
                raise ValueError("判断题答案必须为正确或错误")
        else:
            self.options = None
        return self


class QuestionBatch(BaseModel):
    items: list[GeneratedQuestionDraft] = Field(min_length=1, max_length=100)
