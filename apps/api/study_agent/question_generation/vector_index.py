from collections.abc import Sequence
from typing import Any
from uuid import UUID

import anyio
from langchain_core.embeddings import Embeddings
from pymilvus import DataType, MilvusClient

from study_agent.domain.models import Question


class MilvusQuestionIndex:
    def __init__(
        self, *, uri: str, collection_name: str, embeddings: Embeddings, embedding_model: str
    ) -> None:
        self.client = MilvusClient(uri=uri)
        self.collection_name = collection_name
        self.embeddings = embeddings
        self.embedding_model = embedding_model

    async def delete_questions(self, question_ids: Sequence[UUID]) -> None:
        if question_ids and await anyio.to_thread.run_sync(
            self.client.has_collection, self.collection_name
        ):
            await anyio.to_thread.run_sync(
                lambda: self.client.delete(
                    collection_name=self.collection_name,
                    ids=[str(question_id) for question_id in question_ids],
                )
            )

    def _ensure_collection(self, dimensions: int) -> None:
        if self.client.has_collection(self.collection_name):
            description = self.client.describe_collection(self.collection_name)
            fields = description.get("fields", [])
            vector_field = next((field for field in fields if field.get("name") == "vector"), None)
            existing = (vector_field or {}).get("params", {}).get("dim")
            if existing is not None and int(existing) != dimensions:
                raise ValueError(
                    f"Milvus Collection {self.collection_name} 向量维度为 {existing}，"
                    f"当前 Embedding 返回 {dimensions} 维"
                )
            return
        schema = self.client.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field("id", DataType.VARCHAR, max_length=36, is_primary=True)
        schema.add_field("vector", DataType.FLOAT_VECTOR, dim=dimensions)
        schema.add_field("knowledge_base_id", DataType.VARCHAR, max_length=36)
        schema.add_field("knowledge_point_id", DataType.VARCHAR, max_length=36)
        schema.add_field("question_type", DataType.VARCHAR, max_length=30)
        schema.add_field("difficulty", DataType.INT64)
        schema.add_field("status", DataType.VARCHAR, max_length=20)
        schema.add_field("content", DataType.VARCHAR, max_length=65535)
        index_params = self.client.prepare_index_params()
        index_params.add_index(field_name="vector", index_type="AUTOINDEX", metric_type="COSINE")
        self.client.create_collection(
            collection_name=self.collection_name,
            schema=schema,
            index_params=index_params,
            consistency_level="Strong",
        )

    async def upsert(self, records: list[dict[str, Any]]) -> list[str]:
        if not records:
            return []
        texts = [str(record["content"]) for record in records]
        vectors = await anyio.to_thread.run_sync(self.embeddings.embed_documents, texts)
        await anyio.to_thread.run_sync(self._ensure_collection, len(vectors[0]))
        payload = [
            dict(record, vector=vector) for record, vector in zip(records, vectors, strict=True)
        ]
        await anyio.to_thread.run_sync(
            lambda: self.client.upsert(collection_name=self.collection_name, data=payload)
        )
        return [str(record["id"]) for record in records]

    async def upsert_question(self, question: Question) -> str:
        records = [
            {
                "id": str(question.id),
                "knowledge_base_id": str(question.knowledge_base_id),
                "knowledge_point_id": str(question.knowledge_point_id),
                "question_type": question.question_type,
                "difficulty": question.difficulty,
                "status": question.status,
                "content": (
                    f"{question.stem}\n答案：{question.correct_answer}\n解析：{question.explanation}"
                ),
            }
        ]
        return (await self.upsert(records))[0]
