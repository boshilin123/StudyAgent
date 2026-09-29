from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from study_agent.evaluation.metrics import (  # noqa: E402
    question_is_valid,
    question_metrics,
    retrieval_metrics,
)


def read_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def write_result(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"\n结果已保存：{path}")


def metadata(kind: str) -> dict[str, Any]:
    return {
        "evaluation_type": kind,
        "generated_at": datetime.now(UTC).isoformat(),
        "python": platform.python_version(),
        "embedding_provider": os.getenv("EMBEDDING_PROVIDER", "unknown"),
        "embedding_model": os.getenv("EMBEDDING_MODEL") or "unknown",
        "llm_model": os.getenv("LLM_MODEL") or "unknown",
    }


def evaluate_retrieval(args: argparse.Namespace) -> None:
    dataset_path = Path(args.dataset)
    rows = [
        json.loads(line)
        for line in dataset_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    observations: list[dict[str, Any]] = []
    for row in rows:
        params = urllib.parse.urlencode({"q": row["query"], "limit": args.limit})
        url = f"{args.base_url}/api/knowledge-bases/{row['knowledge_base_id']}/search?{params}"
        started = time.perf_counter()
        response = read_json(url)
        latency_ms = (time.perf_counter() - started) * 1000
        observations.append(
            {
                "case_id": row["case_id"],
                "query": row["query"],
                "relevant_chunk_ids": row["relevant_chunk_ids"],
                "retrieved_chunk_ids": [item["chunk_id"] for item in response["items"]],
                "latency_ms": round(latency_ms, 3),
            }
        )
    result = {
        **metadata("retrieval"),
        "dataset": str(dataset_path),
        "dataset_sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
        "base_url": args.base_url,
        "limit": args.limit,
        "metrics": retrieval_metrics(observations),
        "cases": observations,
    }
    write_result(Path(args.output), result)


def evaluate_questions(args: argparse.Namespace) -> None:
    params = urllib.parse.urlencode(
        {"knowledge_base_id": args.knowledge_base_id, "page": 1, "page_size": 100}
    )
    response = read_json(f"{args.base_url}/api/questions?{params}")
    questions = response["items"]
    result = {
        **metadata("question_bank"),
        "knowledge_base_id": args.knowledge_base_id,
        "base_url": args.base_url,
        "metrics": question_metrics(questions),
        "question_ids": [item["id"] for item in questions],
        "limitations": [
            "结构合法率不等于人工审核通过率",
            "来源可追溯率只验证来源关联存在，不自动判断引文是否充分支持答案",
        ],
    }
    if args.review_output:
        review_path = Path(args.review_output)
        review_path.parent.mkdir(parents=True, exist_ok=True)
        review_rows = []
        for item in questions:
            review_rows.append(
                {
                    "question_id": item["id"],
                    "question_type": item["question_type"],
                    "difficulty": item["difficulty"],
                    "stem": item["stem"],
                    "options": item["options"],
                    "correct_answer": item["correct_answer"],
                    "explanation": item["explanation"],
                    "sources": item["sources"],
                    "automatic_checks": {
                        "schema_valid": question_is_valid(item),
                        "source_traceable": bool(item["sources"]),
                    },
                    "human_review": {
                        "status": "pending",
                        "answer_supported": None,
                        "stem_clear": None,
                        "options_valid": None,
                        "approved": None,
                        "notes": "",
                    },
                }
            )
        review_path.write_text(
            "".join(
                json.dumps(row, ensure_ascii=False) + "\n" for row in review_rows
            ),
            encoding="utf-8",
        )
        result["human_review_file"] = str(review_path)
        result["human_review_status"] = "pending"
    write_result(Path(args.output), result)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="StudyAgent P7 可复现评测基线")
    subparsers = root.add_subparsers(dest="command", required=True)

    retrieval = subparsers.add_parser("retrieval", help="运行真实检索评测")
    retrieval.add_argument("--dataset", required=True)
    retrieval.add_argument("--output", required=True)
    retrieval.add_argument("--base-url", default="http://127.0.0.1:58000")
    retrieval.add_argument("--limit", type=int, default=5)
    retrieval.set_defaults(handler=evaluate_retrieval)

    questions = subparsers.add_parser("questions", help="审计真实题库的确定性质量指标")
    questions.add_argument("--knowledge-base-id", required=True)
    questions.add_argument("--output", required=True)
    questions.add_argument("--base-url", default="http://127.0.0.1:58000")
    questions.add_argument("--review-output")
    questions.set_defaults(handler=evaluate_questions)
    return root


if __name__ == "__main__":
    arguments = parser().parse_args()
    arguments.handler(arguments)
