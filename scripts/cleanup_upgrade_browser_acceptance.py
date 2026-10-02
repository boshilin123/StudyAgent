"""Clean only the random entities and collection identified by this run's localhost log."""

import asyncio
import re
from pathlib import Path
from uuid import UUID

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from pymilvus import MilvusClient
from sqlalchemy import delete, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from study_agent.config import Settings
from study_agent.infrastructure.checkpointer import psycopg_connection_string
from study_agent.infrastructure.models import KnowledgeBaseModel, StudySessionModel
from study_agent.infrastructure.tutoring_models import TutorConversationModel
from study_agent.runtime import create_event_loop

ROOT = Path(__file__).resolve().parents[1]


async def cleanup():
    log = (ROOT / "tmp" / "upgrade-acceptance" / "browser-live-api.log").read_text()
    owned = set(re.findall(r"knowledge_base_id=([0-9a-f-]{36})", log))
    assert len(owned) == 1, "refuse ambiguous knowledge base ownership"
    kb = UUID(owned.pop())
    configured = Settings(_env_file=ROOT / ".env")
    target = make_url(configured.database_url).set(host="127.0.0.1", port=55432,
                                                 database="study_agent_test_upgrade")
    assert target.database == "study_agent_test_upgrade"
    url = target.render_as_string(hide_password=False)
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine)
    try:
        async with factory() as session:
            row = await session.get(KnowledgeBaseModel, kb)
            threads = (await session.scalars(select(TutorConversationModel.graph_thread_id)
                .where(TutorConversationModel.knowledge_base_id == kb))).all()
            if row is not None:
                assert row.name == "P10测试", "refuse non-synthetic knowledge base"
                await session.execute(delete(TutorConversationModel).where(
                    TutorConversationModel.knowledge_base_id == kb))
                await session.execute(delete(StudySessionModel).where(
                    StudySessionModel.knowledge_base_id == kb))
                await session.execute(delete(KnowledgeBaseModel).where(KnowledgeBaseModel.id == kb))
                await session.commit()
        async with AsyncPostgresSaver.from_conn_string(psycopg_connection_string(url)) as saver:
            for thread in threads:
                assert thread.startswith("tutor:")
                await saver.adelete_thread(thread)
        async with factory() as session:
            assert await session.get(KnowledgeBaseModel, kb) is None
        print("Owned browser synthetic PostgreSQL entities and checkpoint thread cleaned.")
    finally:
        await engine.dispose()
    client = MilvusClient(uri="http://127.0.0.1:59530")
    try:
        collections = [name for name in client.list_collections()
                       if name.startswith("study_agent_test_upgrade_browser_")]
        assert len(collections) <= 1, "refuse ambiguous browser collection ownership"
        for name in collections:
            client.drop_collection(name)
        print("Owned browser Milvus collection cleaned; other collections untouched.")
    finally:
        client.close()


if __name__ == "__main__":
    with asyncio.Runner(loop_factory=create_event_loop) as runner:
        runner.run(cleanup())
