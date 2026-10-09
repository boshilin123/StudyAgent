from functools import lru_cache

from study_agent.config import get_settings
from study_agent.ingestion.embeddings import build_embeddings
from study_agent.ingestion.vector_index import MilvusDocumentIndex


# 按当前向量配置创建原文索引实例，并缓存复用。
@lru_cache
def get_document_index() -> MilvusDocumentIndex:
    settings = get_settings()
    embeddings, model_name = build_embeddings(settings)
    return MilvusDocumentIndex(
        uri=settings.milvus_uri,
        collection_name=settings.milvus_document_collection,
        embeddings=embeddings,
        embedding_model=model_name,
    )
