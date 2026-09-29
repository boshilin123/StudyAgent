import hashlib
import re
from uuid import UUID, uuid5

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from study_agent.domain.models import DocumentChunk

CHUNK_NAMESPACE = UUID("0cd60cd7-c523-4710-9948-33037ca94a86")


def _estimate_tokens(text: str) -> int:
    latin_tokens = len(re.findall(r"[A-Za-z0-9_]+", text))
    cjk_characters = len(re.findall(r"[\u3400-\u9fff]", text))
    return max(1, latin_tokens + cjk_characters)


def build_chunks(
    documents: list[Document],
    *,
    material_id: UUID,
    chunk_size: int,
    chunk_overlap: int,
) -> list[DocumentChunk]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        add_start_index=True,
        separators=["\n\n", "\n", "。", "！", "？", ". ", " ", ""],
    )
    split_documents = splitter.split_documents(documents)
    chunks: list[DocumentChunk] = []
    for index, document in enumerate(split_documents):
        content = document.page_content.strip()
        if not content:
            continue
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        chunk_id = uuid5(CHUNK_NAMESPACE, f"{material_id}:{index}:{content_hash}")
        metadata = document.metadata
        chunks.append(
            DocumentChunk(
                id=chunk_id,
                material_id=material_id,
                chunk_index=index,
                content=content,
                token_count=_estimate_tokens(content),
                page_start=metadata.get("page_start"),
                page_end=metadata.get("page_end"),
                heading_path=list(metadata.get("heading_path", [])),
                content_hash=content_hash,
                vector_id=None,
                embedding_model=None,
            )
        )
    if not chunks:
        raise ValueError("document produced no chunks")
    return chunks
