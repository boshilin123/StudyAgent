"""Local-only vertical browser server using synthetic fixtures and an isolated database."""

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from study_agent.config import Settings

settings = Settings(_env_file=ROOT / ".env")
test_url = make_url(settings.database_url).set(host="127.0.0.1", port=55432,
                                             database="study_agent_test_upgrade")
assert test_url.database == "study_agent_test_upgrade"
os.environ["TEST_DATABASE_URL"] = test_url.render_as_string(hide_password=False)

import uvicorn
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import delete

from study_agent.api.dependencies import get_uow
from study_agent.api.tutoring_dependencies import get_tutor_service
from study_agent.application.learning_queries import LearningQueries
from study_agent.application.retrieval import LearningMaterialRetrieval
from study_agent.application.tutoring import TutorService
from study_agent.domain.models import DocumentChunk
from study_agent.infrastructure.checkpointer import psycopg_connection_string
from study_agent.infrastructure.tutoring import TutorRepository
from study_agent.infrastructure.tutoring_models import TutorConversationModel
from study_agent.infrastructure.unit_of_work import SqlAlchemyUnitOfWork
from study_agent.ingestion.embeddings import DeterministicEmbeddings
from study_agent.ingestion.vector_index import MilvusDocumentIndex
from study_agent.main import create_app, settings as app_settings
from tests.test_postgres_reliability import seeded_database
from tests.test_tutor_postgres_acceptance import model_for

# Public only on localhost during this controlled synthetic test. Production token is untouched.
app_settings.api_access_token = None
app = create_app()


@asynccontextmanager
async def acceptance_lifespan(application):
    fixture = seeded_database.__wrapped__()
    data = await anext(fixture)
    collection = "study_agent_test_upgrade_browser_" + uuid4().hex
    index = MilvusDocumentIndex(uri="http://127.0.0.1:59530", collection_name=collection,
        embeddings=DeterministicEmbeddings(), embedding_model="deterministic-local-v1")
    try:
        await index.upsert(knowledge_base_id=data.kb, chunks=[DocumentChunk(
            id=data.chunk, material_id=data.material, chunk_index=0, content="TCP测试来源",
            content_hash="a" * 64, token_count=3, page_start=None, page_end=None,
            heading_path=[], vector_id=str(data.chunk), embedding_model="deterministic-local-v1")])
        data.citation_id = f"chunk:{data.chunk}:{'a' * 64}"
        async with AsyncPostgresSaver.from_conn_string(psycopg_connection_string(data.url)) as saver:
            service = TutorService(TutorRepository(data.factory, data.engine),
                LearningQueries(data.factory), LearningMaterialRetrieval(data.factory, index),
                settings.model_copy(update={"tutor_timeout_seconds": 15}), saver, lambda: model_for(data))

            async def real_uow():
                async with data.factory() as session:
                    yield SqlAlchemyUnitOfWork(session)

            application.dependency_overrides[get_uow] = real_uow
            application.dependency_overrides[get_tutor_service] = lambda: service
            print("Synthetic browser acceptance server ready: isolated PostgreSQL/Milvus, scripted model.")
            yield
    finally:
        async with data.factory() as session:
            await session.execute(delete(TutorConversationModel).where(
                TutorConversationModel.knowledge_base_id == data.kb))
            await session.commit()
        assert collection.startswith("study_agent_test_upgrade_browser_")
        if index.client.has_collection(collection):
            index.client.drop_collection(collection)
        index.client.close()
        await fixture.aclose()


app.router.lifespan_context = acceptance_lifespan

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=58001, loop="study_agent.runtime:create_event_loop")
