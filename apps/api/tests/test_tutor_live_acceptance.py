"""Opt-in real provider + embeddings + isolated Milvus + PostgreSQL acceptance."""

import hashlib
import json
import os
import time
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import update

from study_agent.api.tutoring_schemas import CreateTutorConversation
from study_agent.application.retrieval import LearningMaterialRetrieval
from study_agent.config import Settings
from study_agent.domain.models import DocumentChunk
from study_agent.infrastructure.checkpointer import psycopg_connection_string
from study_agent.infrastructure.models import DocumentChunkModel
from study_agent.ingestion.embeddings import build_embeddings
from study_agent.ingestion.vector_index import MilvusDocumentIndex
from study_agent.llm.models import get_chat_model
from tests.test_postgres_reliability import create_session, submit
from tests.test_tutor_postgres_acceptance import (
    event_loop_policy as event_loop_policy,
)
from tests.test_tutor_postgres_acceptance import (
    payload,
    service_for,
)
from tests.test_tutor_postgres_acceptance import (
    seeded_database as seeded_database,
)
from tests.test_tutor_postgres_acceptance import (
    tutor_database as tutor_database,
)

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[3]


async def test_q01_q02_real_provider_tool_loop_and_distinct_business_intents(tutor_database):
    if os.environ.get("RUN_LIVE_TUTOR") != "1":
        pytest.skip("RUN_LIVE_TUTOR=1 required; scripted/HTTP tests are not real provider evidence")
    data = tutor_database
    settings = Settings(_env_file=ROOT / ".env")
    llm_ready = bool(
        (settings.tutor_llm_model or settings.llm_model)
        and (settings.tutor_llm_base_url or settings.llm_base_url)
        and (settings.tutor_llm_api_key or settings.llm_api_key)
    )
    embeddings_ready = bool(settings.embedding_base_url and settings.embedding_model)
    if not llm_ready or not embeddings_ready:
        pytest.skip("Existing model/embedding configuration unavailable")
    content = (
        "TCP三次握手：客户端发送SYN；服务器回复SYN和ACK；客户端回复ACK。"
        "三次握手确认双方发送接收能力并同步初始序列号。"
        "TCP是可靠字节流，UDP是无连接的数据报；不能把UDP说成有TCP握手。"
    )
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    async with data.factory() as session:
        await session.execute(
            update(DocumentChunkModel)
            .where(DocumentChunkModel.id == data.chunk)
            .values(content=content, content_hash=content_hash, page_start=2, page_end=2)
        )
        await session.commit()
    collection = "study_agent_test_upgrade_" + uuid4().hex
    embeddings, embedding_model = build_embeddings(settings)
    index = MilvusDocumentIndex(
        uri="http://127.0.0.1:59530",
        collection_name=collection,
        embeddings=embeddings,
        embedding_model=embedding_model,
    )
    records = []
    evidence_path = ROOT / "tmp" / "upgrade-acceptance" / "live-provider.json"
    try:
        chunk = DocumentChunk(
            id=data.chunk,
            material_id=data.material,
            chunk_index=0,
            content=content,
            content_hash=content_hash,
            token_count=100,
            page_start=2,
            page_end=2,
            heading_path=[],
            vector_id=str(data.chunk),
            embedding_model=embedding_model,
        )
        await index.upsert(knowledge_base_id=data.kb, chunks=[chunk])
        data.retrieval = LearningMaterialRetrieval(data.factory, index)
        # Real learning facts are created through the original application service.
        view = await create_session(data, mode="practice")
        await submit(data, view.session.id, view.current_question.id, uuid4(), answer=False)
        data.settings = settings.model_copy(update={"tutor_timeout_seconds": 90})
        for question, intent in [
            ("请检索当前资料，解释TCP三次握手的步骤，并引用实际返回的资料依据。", "materials"),
            ("请读取我当前的学习进度和近期错题，分析实际错题并给出复习顺序。", "mistakes"),
        ]:
            model = get_chat_model(data.settings, purpose="tutoring")
            provider_error = {}
            original_agenerate = model._agenerate

            async def capture_provider_error(
                *args, _original=original_agenerate, _errors=provider_error, **kwargs
            ):
                try:
                    return await _original(*args, **kwargs)
                except Exception as exc:
                    body = getattr(exc, "body", None)
                    if isinstance(body, dict):
                        body = body.get("error", body)
                    body = {key: body.get(key) for key in ["code", "message", "type", "param"]}
                    safe_text = json.dumps(body, ensure_ascii=False)
                    for secret in [
                        settings.llm_api_key,
                        settings.tutor_llm_api_key,
                        settings.embedding_api_key,
                    ]:
                        if secret:
                            safe_text = safe_text.replace(secret, "[redacted]")
                    _errors.update({"type": type(exc).__name__, "body": safe_text})
                    raise

            object.__setattr__(model, "_agenerate", capture_provider_error)
            async with AsyncPostgresSaver.from_conn_string(
                psycopg_connection_string(data.url)
            ) as saver:
                service = service_for(data, saver, model)
                conversation = await service.create(
                    CreateTutorConversation(knowledge_base_id=data.kb)
                )
                started = time.monotonic()
                answer = await service.submit(conversation.id, payload(question, intent))
                elapsed = time.monotonic() - started
                turn = await data.repository.turn(conversation.id, turn_id=UUID(answer["turn_id"]))
                tool_names = [step["name"] for step in turn.trace if step.get("kind") == "tool"]
                records.append(
                    {
                        "intent": intent,
                        "elapsed_seconds": round(elapsed, 3),
                        "model": data.settings.tutor_llm_model or data.settings.llm_model,
                        "provider": "configured OpenAI-compatible endpoint (not disclosed)",
                        "tools": tool_names,
                        "response": answer,
                        "trace": turn.trace,
                        "provider_error": provider_error,
                        "infrastructure": "real PostgreSQL + Milvus + provider + embeddings",
                    }
                )
                evidence_path.parent.mkdir(parents=True, exist_ok=True)
                evidence_path.write_text(
                    json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                assert answer["status"] == "completed", answer
                assert answer["usage"]["model_calls"] >= 2
                if intent == "materials":
                    assert "search_learning_materials" in tool_names
                    assert answer["citations"] and answer["citations"][0]["page_start"] == 2
                else:
                    assert {"get_learning_progress", "list_recent_mistakes"}.issubset(tool_names)
    finally:
        assert collection.startswith("study_agent_test_upgrade_")
        if index.client.has_collection(collection):
            index.client.drop_collection(collection)
        index.client.close()
