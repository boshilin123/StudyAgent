from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from study_agent.domain.models import DocumentChunk
from study_agent.question_generation.context import bind_question_context, plan_generation_groups
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


def test_three_question_types_pass_with_backend_context() -> None:
    chunk = _chunk("TCP 通过三次握手建立连接。IP 提供尽力而为的数据报服务。")
    point = KnowledgePointDraft(
        canonical_key="tcp-handshake",
        name="TCP 三次握手",
        description="理解 TCP 建立连接的过程",
        importance=0.9,
        difficulty=2,
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
        ),
        GeneratedQuestionDraft(
            knowledge_point_key=point.canonical_key,
            question_type="fill_blank",
            stem="TCP 通过____握手建立连接。",
            correct_answers=["三次"],
            explanation="填入三次即可还原原文事实。",
            difficulty=1,
        ),
        GeneratedQuestionDraft(
            knowledge_point_key=point.canonical_key,
            question_type="true_false",
            stem="TCP 通过三次握手建立连接。",
            correct_answers=["正确"],
            explanation="该陈述与原文一致。",
            difficulty=1,
        ),
    ]
    accepted, rejected = validate_question_drafts(
        knowledge_points=[point],
        questions=[
            bind_question_context(
                question, plan_generation_groups([chunk], target_count=3, max_chars=1000)[0]
            )
            for question in questions
        ],
        chunks=[chunk],
        allowed_types={"single_choice", "fill_blank", "true_false"},
        difficulty_min=1,
        difficulty_max=3,
    )
    assert len(accepted) == 3
    assert rejected == []
    assert all(question.source_quotes == [chunk.content] for question in accepted)


def test_model_sources_cannot_override_backend_context() -> None:
    chunk = _chunk("TCP 通过三次握手建立连接。")
    point = KnowledgePointDraft(
        canonical_key="tcp-handshake",
        name="TCP 三次握手",
        description="理解 TCP 建立连接的过程",
        importance=0.9,
        difficulty=2,
    )
    question = GeneratedQuestionDraft.model_validate(
        dict(
            knowledge_point_key=point.canonical_key,
            question_type="true_false",
            stem="TCP 建立连接需要五次握手。",
            correct_answers=["错误"],
            explanation="与原文不符，因此错误。",
            difficulty=1,
            source_chunk_ids=[str(uuid4()), str(uuid4())],
            source_quotes=["TCP 通过五次握手建立连接"],
        )
    )
    group = plan_generation_groups([chunk], target_count=1, max_chars=1000)[0]
    bound = bind_question_context(question, group)
    accepted, rejected = validate_question_drafts(
        knowledge_points=[point],
        questions=[bound],
        chunks=[chunk],
        allowed_types={"true_false"},
        difficulty_min=1,
        difficulty_max=3,
    )
    assert len(accepted) == 1
    assert rejected == []
    assert bound.source_chunk_ids == [chunk.id]
    assert bound.source_quotes == [chunk.content]
    assert bound.source_kind == "reference_context"


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
        )


def test_model_schemas_do_not_request_sources() -> None:
    for schema in (GeneratedQuestionDraft, KnowledgePointDraft):
        properties = schema.model_json_schema()["properties"]
        assert "source_chunk_ids" not in properties
        assert "source_quotes" not in properties


def test_context_groups_cover_start_middle_end_with_bounded_budget() -> None:
    chunks = [_chunk(f"第 {index} 段内容。" * 200) for index in range(40)]
    for index, chunk in enumerate(chunks):
        chunk.chunk_index = index
    groups = plan_generation_groups(chunks, target_count=10, max_chars=1500)
    assert len(groups) == 3
    assert sum(group.target_count for group in groups) == 10
    assert sum(len(group.context) for group in groups) <= 1500
    assert [group.chunks[0].chunk_index for group in groups] == [0, 18, 36]
    for group in groups:
        assert all(chunk.content in group.context for chunk in group.chunks)
        assert all(str(chunk.id) not in group.context for chunk in group.chunks)
        bound = bind_question_context(
            GeneratedQuestionDraft(
                knowledge_point_key="test-point",
                question_type="true_false",
                stem="这是一道测试判断题。",
                correct_answers=["正确"],
                explanation="参考本组原文进行判断。",
                difficulty=2,
            ),
            group,
        )
        assert all(quote in group.context for quote in bound.source_quotes)


def test_context_binding_does_not_use_other_group_sources() -> None:
    chunks = [_chunk(f"第 {index} 段参考原文。") for index in range(12)]
    for index, chunk in enumerate(chunks):
        chunk.chunk_index = index
    groups = plan_generation_groups(chunks, target_count=3, max_chars=6000)
    question = GeneratedQuestionDraft(
        knowledge_point_key="test-point",
        question_type="true_false",
        stem="这是一道测试判断题。",
        correct_answers=["正确"],
        explanation="参考本组原文进行判断。",
        difficulty=2,
    )
    bound = bind_question_context(question, groups[1])
    assert bound.source_chunk_ids == [chunk.id for chunk in chunks[4:8]]
    assert not set(bound.source_chunk_ids) & {chunk.id for chunk in chunks[:4] + chunks[8:]}


def test_duplicate_questions_are_rejected_across_generation_rounds() -> None:
    chunk = _chunk("TCP 通过三次握手建立连接。")
    point = KnowledgePointDraft(
        canonical_key="tcp-handshake",
        name="TCP握手",
        description="TCP通过三次握手建立连接",
        importance=0.9,
        difficulty=2,
    )
    group = plan_generation_groups([chunk], target_count=1, max_chars=1000)[0]
    question = bind_question_context(
        GeneratedQuestionDraft(
            knowledge_point_key=point.canonical_key,
            question_type="true_false",
            stem="TCP通过三次握手建立连接。",
            correct_answers=["正确"],
            explanation="原文描述了连接建立过程。",
            difficulty=2,
        ),
        group,
    )
    seen: set[str] = set()
    kwargs = dict(
        knowledge_points=[point],
        questions=[question],
        chunks=[chunk],
        allowed_types={"true_false"},
        difficulty_min=1,
        difficulty_max=5,
        seen_stems=seen,
    )
    accepted, rejected = validate_question_drafts(**kwargs)
    assert len(accepted) == 1 and not rejected
    accepted, rejected = validate_question_drafts(**kwargs)
    assert not accepted and rejected[0].reason == "同批次题干重复"
