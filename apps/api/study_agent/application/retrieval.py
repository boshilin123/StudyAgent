"""Validate vector candidates against current PostgreSQL content and ownership."""

import asyncio
from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from study_agent.domain.ports import DocumentIndex
from study_agent.infrastructure.models import DocumentChunkModel, MaterialModel


def evidence_from_rows(
    chunk: DocumentChunkModel, material: MaterialModel, quote: str | None = None
) -> dict[str, Any]:
    excerpt = (quote if quote and quote in chunk.content else chunk.content)[:1200]
    return {
        "evidence_id": f"chunk:{chunk.id}:{chunk.content_hash}",
        "material_id": str(material.id),
        "chunk_id": str(chunk.id),
        "title": material.title,
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "quote": excerpt,
        "content_hash": chunk.content_hash,
        "valid": True,
    }


class LearningMaterialRetrieval:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        document_index: DocumentIndex | Callable[[], DocumentIndex],
    ) -> None:
        self.sessions = session_factory
        self.index = document_index

    async def search(self, knowledge_base_id: UUID, query: str, top_k: int) -> list[dict[str, Any]]:
        index = await asyncio.to_thread(self.index) if callable(self.index) else self.index
        hits = await index.search(knowledge_base_id=knowledge_base_id, query=query, limit=top_k)
        if not hits:
            return []
        async with self.sessions() as session:
            rows = (
                await session.execute(
                    select(DocumentChunkModel, MaterialModel)
                    .join(MaterialModel, DocumentChunkModel.material_id == MaterialModel.id)
                    .where(
                        DocumentChunkModel.id.in_([h.chunk_id for h in hits]),
                        MaterialModel.knowledge_base_id == knowledge_base_id,
                        MaterialModel.parse_status == "ready",
                    )
                )
            ).all()
        current = {chunk.id: (chunk, material) for chunk, material in rows}
        return [
            evidence_from_rows(*current[hit.chunk_id])
            for hit in hits
            if hit.chunk_id in current and current[hit.chunk_id][1].id == hit.material_id
        ]

    async def revalidate(self, knowledge_base_id: UUID, evidence: dict[str, Any]) -> bool:
        async with self.sessions() as session:
            row = (
                await session.execute(
                    select(DocumentChunkModel, MaterialModel)
                    .join(MaterialModel, DocumentChunkModel.material_id == MaterialModel.id)
                    .where(
                        DocumentChunkModel.id == UUID(evidence["chunk_id"]),
                        MaterialModel.id == UUID(evidence["material_id"]),
                        MaterialModel.knowledge_base_id == knowledge_base_id,
                        MaterialModel.parse_status == "ready",
                    )
                )
            ).first()
            return bool(
                row
                and row[0].content_hash == evidence["content_hash"]
                and evidence["quote"] in row[0].content
            )
