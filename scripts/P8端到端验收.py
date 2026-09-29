from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx


def wait_job(
    client: httpx.Client,
    path: str,
    *,
    terminal: set[str],
    timeout_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        response = client.get(path)
        response.raise_for_status()
        payload = response.json()
        if payload["status"] in terminal:
            return payload
        time.sleep(1)
    raise TimeoutError(f"等待任务超时：{path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="StudyAgent P8 真实端到端验收")
    parser.add_argument("--knowledge-base-id", required=True)
    parser.add_argument("--generation-material-id", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:58000")
    parser.add_argument("--question-count", type=int, default=3)
    parser.add_argument("--timeout-seconds", type=float, default=300)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    started = time.perf_counter()
    token = f"P8-{uuid4().hex[:12]}"
    uploaded_material_id: str | None = None
    result: dict[str, Any] = {
        "evaluation_type": "p8_end_to_end",
        "generated_at": datetime.now(UTC).isoformat(),
        "knowledge_base_id": args.knowledge_base_id,
        "steps": {},
    }

    with httpx.Client(base_url=args.base_url, timeout=60) as client:
        ready = client.get("/api/health/ready")
        ready.raise_for_status()
        result["steps"]["health"] = ready.json()

        try:
            content = (
                "# P8 自动化验收资料\n\n"
                f"唯一检索口令是 {token}。该资料只用于验证上传、异步解析、"
                "外部 Embedding、Milvus 入库与检索，完成后自动删除。\n"
            ).encode()
            upload = client.post(
                f"/api/knowledge-bases/{args.knowledge_base_id}/materials",
                files={"file": (f"{token}.md", content, "text/markdown")},
                data={"title": f"P8 自动化验收 {token}"},
            )
            upload.raise_for_status()
            upload_payload = upload.json()
            uploaded_material_id = upload_payload["material"]["id"]
            ingestion = wait_job(
                client,
                f"/api/ingestion-jobs/{upload_payload['job']['id']}",
                terminal={"completed", "failed"},
                timeout_seconds=args.timeout_seconds,
            )
            if ingestion["status"] != "completed":
                raise RuntimeError(f"资料处理失败：{ingestion.get('error_message')}")
            search = client.get(
                f"/api/knowledge-bases/{args.knowledge_base_id}/search",
                params={"q": token, "limit": 3, "material_id": uploaded_material_id},
            )
            search.raise_for_status()
            hits = search.json()["items"]
            if not hits or hits[0]["material_id"] != uploaded_material_id:
                raise RuntimeError("上传资料未被检索召回")
            result["steps"]["upload_and_retrieval"] = {
                "status": "passed",
                "ingestion_job_id": ingestion["id"],
                "top_score": hits[0]["score"],
            }
        finally:
            if uploaded_material_id:
                cleanup = client.delete(f"/api/materials/{uploaded_material_id}")
                if cleanup.status_code not in {204, 404}:
                    cleanup.raise_for_status()

        generation = client.post(
            f"/api/materials/{args.generation_material_id}/question-generation-jobs",
            json={
                "target_question_count": args.question_count,
                "allowed_types": ["single_choice", "fill_blank", "true_false"],
                "difficulty_min": 1,
                "difficulty_max": 5,
                "language": "zh-CN",
            },
        )
        generation.raise_for_status()
        generation_job = wait_job(
            client,
            f"/api/question-generation-jobs/{generation.json()['id']}",
            terminal={"completed", "partial", "failed"},
            timeout_seconds=args.timeout_seconds,
        )
        if generation_job["status"] == "failed":
            raise RuntimeError(f"题库生成失败：{generation_job.get('error_message')}")
        result["steps"]["question_generation"] = {
            "status": generation_job["status"],
            "job_id": generation_job["id"],
            "generated_count": generation_job["generated_count"],
            "rejected_count": generation_job["rejected_count"],
        }

        questions_response = client.get(
            "/api/questions",
            params={
                "knowledge_base_id": args.knowledge_base_id,
                "page": 1,
                "page_size": 100,
            },
        )
        questions_response.raise_for_status()
        sourced_questions = [
            question
            for question in questions_response.json()["items"]
            if question["sources"]
        ]
        active_questions = [
            question for question in sourced_questions if question["status"] == "active"
        ]
        for question in sourced_questions:
            if len(active_questions) >= args.question_count:
                break
            if question["status"] != "active":
                response = client.post(f"/api/questions/{question['id']}/activate")
                response.raise_for_status()
                active_questions.append(response.json())
        if len(active_questions) < args.question_count:
            raise RuntimeError("可启用且有来源的题目数量不足")
        result["steps"]["question_activation"] = {
            "status": "passed",
            "active_question_count": len(active_questions),
        }

        session_response = client.post(
            "/api/study/sessions",
            json={
                "knowledge_base_id": args.knowledge_base_id,
                "mode": "mock_exam",
                "question_count": args.question_count,
                "question_types": ["single_choice", "fill_blank", "true_false"],
                "difficulty_min": 1,
                "difficulty_max": 5,
            },
        )
        session_response.raise_for_status()
        session = session_response.json()
        session_id = session["id"]
        answered = 0
        while session.get("current_question") is not None:
            public_question = session["current_question"]
            detail = client.get(f"/api/questions/{public_question['id']}")
            detail.raise_for_status()
            answer = detail.json()["correct_answer"][0]
            submitted = client.post(
                f"/api/study/sessions/{session_id}/answers",
                json={
                    "submission_id": str(uuid4()),
                    "question_id": public_question["id"],
                    "answer": answer,
                    "elapsed_seconds": 1,
                },
            )
            submitted.raise_for_status()
            answer_result = submitted.json()
            if answer_result["verdict"] != "correct":
                raise RuntimeError(f"正确答案未通过判分：{public_question['id']}")
            answered += 1
            session = answer_result["session"]

        if session["status"] != "completed":
            finish = client.post(f"/api/study/sessions/{session_id}/finish")
            finish.raise_for_status()
            session = finish.json()
        result["steps"]["study_loop"] = {
            "status": "passed",
            "session_id": session_id,
            "answered_count": answered,
            "correct_count": session["correct_count"],
            "total_score": session["total_score"],
        }

        mastery = client.get(
            "/api/mastery", params={"knowledge_base_id": args.knowledge_base_id}
        )
        mastery.raise_for_status()
        history = client.get(
            "/api/study/history",
            params={"knowledge_base_id": args.knowledge_base_id, "page": 1, "page_size": 5},
        )
        history.raise_for_status()
        result["steps"]["progress"] = {
            "status": "passed",
            "mastery_count": len(mastery.json()),
            "history_total": history.json()["total"],
        }

    result["status"] = "passed"
    result["duration_ms"] = round((time.perf_counter() - started) * 1000, 3)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n结果已保存：{output}")


if __name__ == "__main__":
    main()
