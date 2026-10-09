"""完整离线实验：字符分块、稳定 ID、长资料生成上下文的覆盖范围。

运行生产函数；不执行 Embedding 或向量检索，不将材料拼接称为检索式 RAG。
"""

import json
from uuid import UUID

from langchain_core.documents import Document

from study_agent.ingestion.chunking import build_chunks
from study_agent.question_generation.tasks import build_generation_context


def run_demo() -> dict[str, object]:
    documents = [
        Document(
            page_content=f"第{page}节知识点。" + "TCP 用三次握手建立连接，确认双方收发能力。" * 25,
            metadata={"page_start": page, "page_end": page, "heading_path": [f"第{page}节"]},
        )
        for page in range(1, 65)
    ]
    kwargs = {"material_id": UUID(int=1), "chunk_size": 800, "chunk_overlap": 120}
    chunks = build_chunks(documents, **kwargs)
    repeated = build_chunks(documents, **kwargs)
    assert [c.id for c in chunks] == [c.id for c in repeated]
    context = build_generation_context(chunks, max_chars=24000)
    selected = [c for c in chunks if f"chunk_id={c.id};" in context]
    assert 0 < len(selected) < len(chunks)
    assert chunks[0] in selected and chunks[-1] not in selected
    return {
        "evidence_kind": "production character splitter + generation context; no retrieval",
        "chunk_size_unit": "characters",
        "stable_ids": True,
        "total_chunks": len(chunks),
        "selected_chunks": len(selected),
        "context_chars": len(context),
        "configured_max_chars": 24000,
        "selected_pages": [c.page_start for c in selected],
        "last_page_included": False,
        "limitation": "当前按顺序选取前部片段；不能保证长资料完整覆盖。",
        "budget_note": "当前计数未包含片段分隔符，且保留超预算首片段；不是严格总长上限。",
    }


if __name__ == "__main__":
    print(json.dumps(run_demo(), ensure_ascii=False, indent=2))
