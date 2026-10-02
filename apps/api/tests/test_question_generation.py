from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from study_agent.domain.models import DocumentChunk
from study_agent.question_generation.quality import validate_question_drafts
from study_agent.question_generation.schemas import (
    GeneratedQuestionDraft,
    KnowledgePointDraft,
    QuestionOption,
)


def _chunk(content: str) -> DocumentChunk:
    return DocumentChunk(
        id=uuid4(),
        material_id=uuid4(),
        chunk_index=0,
        content=content,
        token_count=20,
        page_start=1,
        page_end=1,
        heading_path=["网络"],
        content_hash="hash",
        vector_id=None,
        embedding_model=None,
        created_at=datetime.now(UTC),
    )


def test_three_question_types_pass_grounding_gate() -> None:
    chunk = _chunk("TCP 通过三次握手建立连接。IP 提供尽力而为的数据报服务。")
    point = KnowledgePointDraft(
        canonical_key="tcp-handshake",
        name="TCP 三次握手",
        description="理解 TCP 建立连接的过程",
        importance=0.9,
        difficulty=2,
        source_chunk_ids=[chunk.id],
    )
    questions = [
        GeneratedQuestionDraft(
            knowledge_point_key=point.canonical_key,
            question_type="single_choice",
            stem="TCP 建立连接通常使用几次握手？",
            options=[
                QuestionOption(key="A", text="一次"),
                QuestionOption(key="B", text="两次"),
                QuestionOption(key="C", text="三次"),
                QuestionOption(key="D", text="四次"),
            ],
            correct_answers=["C"],
            explanation="原文明确说明 TCP 通过三次握手建立连接。",
            difficulty=1,
            source_chunk_ids=[chunk.id],
            source_quotes=["TCP 通过三次握手建立连接"],
        ),
        GeneratedQuestionDraft(
            knowledge_point_key=point.canonical_key,
            question_type="fill_blank",
            stem="TCP 通过____握手建立连接。",
            correct_answers=["三次"],
            explanation="填入三次即可还原原文事实。",
            difficulty=1,
            source_chunk_ids=[chunk.id],
            source_quotes=["TCP 通过三次握手建立连接"],
        ),
        GeneratedQuestionDraft(
            knowledge_point_key=point.canonical_key,
            question_type="true_false",
            stem="TCP 通过三次握手建立连接。",
            correct_answers=["正确"],
            explanation="该陈述与原文一致。",
            difficulty=1,
            source_chunk_ids=[chunk.id],
            source_quotes=["TCP 通过三次握手建立连接"],
        ),
    ]
    accepted, rejected = validate_question_drafts(
        knowledge_points=[point],
        questions=questions,
        chunks=[chunk],
        allowed_types={"single_choice", "fill_blank", "true_false"},
        difficulty_min=1,
        difficulty_max=3,
    )
    assert len(accepted) == 3
    assert rejected == []


def test_grounding_gate_rejects_fabricated_quote() -> None:
    chunk = _chunk("TCP 通过三次握手建立连接。")
    point = KnowledgePointDraft(
        canonical_key="tcp-handshake",
        name="TCP 三次握手",
        description="理解 TCP 建立连接的过程",
        importance=0.9,
        difficulty=2,
        source_chunk_ids=[chunk.id],
    )
    question = GeneratedQuestionDraft(
        knowledge_point_key=point.canonical_key,
        question_type="true_false",
        stem="TCP 建立连接需要五次握手。",
        correct_answers=["错误"],
        explanation="与原文不符，因此错误。",
        difficulty=1,
        source_chunk_ids=[chunk.id],
        source_quotes=["TCP 通过五次握手建立连接"],
    )
    accepted, rejected = validate_question_drafts(
        knowledge_points=[point],
        questions=[question],
        chunks=[chunk],
        allowed_types={"true_false"},
        difficulty_min=1,
        difficulty_max=3,
    )
    assert accepted == []
    assert rejected[0].reason == "引文无法在原文片段中匹配"


def test_single_choice_schema_requires_four_options() -> None:
    with pytest.raises(ValidationError):
        GeneratedQuestionDraft(
            knowledge_point_key="tcp-handshake",
            question_type="single_choice",
            stem="TCP 建立连接需要几次握手？",
            options=[QuestionOption(key="A", text="一次")],
            correct_answers=["A"],
            explanation="测试非法选项数量。",
            difficulty=1,
            source_chunk_ids=[uuid4()],
            source_quotes=["TCP"],
        )
