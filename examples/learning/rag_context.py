"""完整离线实验：字符分块、稳定 ID、长资料生成上下文的覆盖范围。

运行生产函数；不执行 Embedding 或向量检索，不将材料拼接称为检索式 RAG。
"""

import json
from uuid import UUID

from langchain_core.documents import Document

from study_agent.ingestion.chunking import build_chunks
from study_agent.question_generation.context import plan_generation_groups


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
    groups = plan_generation_groups(chunks, target_count=10, max_chars=24000)
    # 每组保留实际送入模型的片段；模型输入不包含数据库 UUID。
    selected = [chunk for group in groups for chunk in group.chunks]
    selected_ids = {chunk.id for chunk in selected}
    context_chars = sum(len(group.context) for group in groups)
    assert 0 < len(selected) < len(chunks)
    assert chunks[0].id in selected_ids and chunks[-1].id in selected_ids
    assert context_chars <= 24000
    assert sum(group.target_count for group in groups) == 10
    return {
        "evidence_kind": "production character splitter + generation context; no retrieval",
        "chunk_size_unit": "characters",
        "stable_ids": True,
        "total_chunks": len(chunks),
        "context_groups": len(groups),
        "group_targets": [group.target_count for group in groups],
        "selected_chunks": len(selected),
        "context_chars": context_chars,
        "configured_max_chars": 24000,
        "selected_pages": [c.page_start for c in selected],
        "last_page_included": chunks[-1].id in selected_ids,
        "limitation": "最多取前、中、后三组，每组最多四块；抽样不能保证长资料完整覆盖。",
        "budget_note": "总字符预算包含标题和分隔符；过长正文截断后按实际输入绑定来源。",
    }


if __name__ == "__main__":
    print(json.dumps(run_demo(), ensure_ascii=False, indent=2))
