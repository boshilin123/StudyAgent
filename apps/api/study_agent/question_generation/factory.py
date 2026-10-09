from functools import lru_cache

from study_agent.config import get_settings
from study_agent.ingestion.embeddings import build_embeddings
from study_agent.question_generation.vector_index import MilvusQuestionIndex


# 复用题库向量索引实例，避免重复创建客户端和模型适配器。
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
