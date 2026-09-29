from functools import lru_cache

from study_agent.config import get_settings
from study_agent.ingestion.embeddings import build_embeddings
from study_agent.question_generation.vector_index import MilvusQuestionIndex


@lru_cache
def get_question_index() -> MilvusQuestionIndex:
    settings = get_settings()
    embeddings, model_name = build_embeddings(settings)
    return MilvusQuestionIndex(
        uri=settings.milvus_uri,
        collection_name=settings.milvus_question_collection,
        embeddings=embeddings,
        embedding_model=model_name,
    )
