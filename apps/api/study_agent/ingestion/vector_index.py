from uuid import UUID

import anyio
from langchain_core.embeddings import Embeddings
from pymilvus import DataType, MilvusClient

from study_agent.domain.models import DocumentChunk, SearchHit


class MilvusDocumentIndex:
    def __init__(
        self,
        *,
        uri: str,
        collection_name: str,
        embeddings: Embeddings,
        embedding_model: str,
    ) -> None:
        self.client = MilvusClient(uri=uri)
        self.collection_name = collection_name
        self.embeddings = embeddings
        self.embedding_model = embedding_model

    def _ensure_collection(self, dimensions: int) -> None:
        if self.client.has_collection(self.collection_name):
            description = self.client.describe_collection(self.collection_name)
            fields = description.get("fields", [])
            vector_field = next((field for field in fields if field.get("name") == "vector"), None)
            existing = (vector_field or {}).get("params", {}).get("dim")
            if existing is not None and int(existing) != dimensions:
                raise ValueError(
                    f"Milvus Collection {self.collection_name} 的向量维度为 {existing}，"
                    f"当前 Embedding 返回 {dimensions} 维；请更换 Collection 名称或重建索引"
                )
            return
        schema = self.client.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field("id", DataType.VARCHAR, max_length=36, is_primary=True)
        schema.add_field("vector", DataType.FLOAT_VECTOR, dim=dimensions)
        schema.add_field("knowledge_base_id", DataType.VARCHAR, max_length=36)
        schema.add_field("material_id", DataType.VARCHAR, max_length=36)
        schema.add_field("content", DataType.VARCHAR, max_length=65535)
        schema.add_field("page_start", DataType.INT64, nullable=True)
        schema.add_field("page_end", DataType.INT64, nullable=True)
        schema.add_field("heading_path", DataType.JSON)
        index_params = self.client.prepare_index_params()
        index_params.add_index(field_name="vector", index_type="AUTOINDEX", metric_type="COSINE")
        self.client.create_collection(
            collection_name=self.collection_name,
            schema=schema,
            index_params=index_params,
            consistency_level="Strong",
        )

    async def upsert(self, *, knowledge_base_id: UUID, chunks: list[DocumentChunk]) -> list[str]:
        vectors = await anyio.to_thread.run_sync(
            self.embeddings.embed_documents, [chunk.content for chunk in chunks]
        )
        if not vectors:
            return []
        await anyio.to_thread.run_sync(self._ensure_collection, len(vectors[0]))
        records = [
            {
                "id": str(chunk.id),
                "vector": vector,
                "knowledge_base_id": str(knowledge_base_id),
                "material_id": str(chunk.material_id),
                "content": chunk.content,
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
                "heading_path": chunk.heading_path,
            }
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        await anyio.to_thread.run_sync(
            lambda: self.client.upsert(collection_name=self.collection_name, data=records)
        )
        return [str(chunk.id) for chunk in chunks]

    async def search(
        self,
        *,
        knowledge_base_id: UUID,
        query: str,
        limit: int,
        material_id: UUID | None = None,
    ) -> list[SearchHit]:
        exists = await anyio.to_thread.run_sync(
            self.client.has_collection, self.collection_name
        )
        if not exists:
            return []
        vector = await anyio.to_thread.run_sync(self.embeddings.embed_query, query)
        expression = f'knowledge_base_id == "{knowledge_base_id}"'
        if material_id:
            expression += f' and material_id == "{material_id}"'
        results = await anyio.to_thread.run_sync(
            lambda: self.client.search(
                collection_name=self.collection_name,
                data=[vector],
                filter=expression,
                limit=limit,
                output_fields=[
                    "material_id",
                    "content",
                    "page_start",
                    "page_end",
                    "heading_path",
                ],
            )
        )
        hits: list[SearchHit] = []
        for result in results[0] if results else []:
            entity = result.get("entity", {})
            hits.append(
                SearchHit(
                    chunk_id=UUID(str(result["id"])),
                    material_id=UUID(str(entity["material_id"])),
                    content=str(entity["content"]),
                    score=float(result.get("distance", 0.0)),
                    page_start=entity.get("page_start"),
                    page_end=entity.get("page_end"),
                    heading_path=list(entity.get("heading_path") or []),
                )
            )
        return hits

    async def delete_material(self, material_id: UUID) -> None:
        exists = await anyio.to_thread.run_sync(
            self.client.has_collection, self.collection_name
        )
        if exists:
            await anyio.to_thread.run_sync(
                lambda: self.client.delete(
                    collection_name=self.collection_name,
                    filter=f'material_id == "{material_id}"',
                )
            )
