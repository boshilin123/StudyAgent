from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


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


def wrong_answer(question: dict[str, Any], correct_answer: object) -> str | bool:
    question_type = question["question_type"]
    answers = correct_answer if isinstance(correct_answer, list) else [correct_answer]
    if question_type == "single_choice":
        return "Z"
    if question_type == "true_false":
        return str(answers[0]) not in {"正确", "true", "True", "1"}
    return "__P9_故意错误答案__"


def main() -> None:
    parser = argparse.ArgumentParser(description="StudyAgent P9 全面真实链路验收")
    parser.add_argument("--base-url", default="http://127.0.0.1:58000")
    parser.add_argument("--question-count", type=int, default=6)
    parser.add_argument("--timeout-seconds", type=float, default=360)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    started = time.perf_counter()
    token = f"P9-{uuid4().hex[:12]}"
    knowledge_base_id: str | None = None
    result: dict[str, Any] = {
        "evaluation_type": "p9_comprehensive_end_to_end",
        "generated_at": datetime.now(UTC).isoformat(),
        "token": token,
        "steps": {},
    }

    material_text = f"""# TCP 可靠传输全面验收资料 {token}

## 三次握手
TCP 建立连接需要三次握手。客户端发送 SYN，服务端回复 SYN-ACK，客户端再发送 ACK。
三次握手的目标是确认双方的发送和接收能力，并同步初始序列号。

## 四次挥手
TCP 关闭连接通常需要四次挥手，因为 TCP 是全双工协议，两个方向需要分别关闭。
主动关闭方发送 FIN，被动关闭方先回复 ACK，处理完剩余数据后再发送 FIN，最后收到 ACK。

## 可靠传输
TCP 使用序列号、确认应答、超时重传、滑动窗口和拥塞控制提供可靠的字节流传输。
校验和用于发现传输错误，重复报文可依据序列号识别。该验收资料的唯一标识是 {token}。
""".encode()

    with httpx.Client(base_url=args.base_url, timeout=90) as client:
        ready = client.get("/api/health/ready")
        ready.raise_for_status()
        require(ready.json().get("status") == "ok", "API 未就绪")
        result["steps"]["health"] = {"status": "passed"}

        invalid = client.post("/api/knowledge-bases", json={"name": ""})
        require(invalid.status_code == 422, "空知识库名称应返回 422")
        invalid_body = invalid.json().get("error", {})
        require(invalid_body.get("code") == "VALIDATION_ERROR", "校验错误结构不正确")
        require(bool(invalid_body.get("request_id")), "错误响应缺少 request_id")
        result["steps"]["error_contract"] = {"status": "passed"}

        created = client.post(
            "/api/knowledge-bases",
            json={
                "name": f"P9 全面验收 {token}",
                "description": "自动验收创建，结束后归档",
                "language": "zh-CN",
            },
        )
        created.raise_for_status()
        knowledge_base = created.json()
        knowledge_base_id = knowledge_base["id"]
        require(knowledge_base["status"] == "active", "新知识库状态错误")
        listed = client.get("/api/knowledge-bases", params={"keyword": token})
        listed.raise_for_status()
        require(listed.json()["total"] == 1, "知识库列表未返回新建记录")
        result["steps"]["knowledge_base_crud"] = {
            "status": "passed",
            "knowledge_base_id": knowledge_base_id,
        }

        unsupported = client.post(
            f"/api/knowledge-bases/{knowledge_base_id}/materials",
            files={"file": ("unsafe.exe", b"not executable", "application/octet-stream")},
        )
        require(unsupported.status_code == 422, "不支持的扩展名应返回 422")
        require(
            unsupported.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE",
            "不支持文件错误码不正确",
        )

        uploaded = client.post(
            f"/api/knowledge-bases/{knowledge_base_id}/materials",
            files={"file": (f"{token}.md", material_text, "text/markdown")},
            data={"title": f"TCP 全面验收 {token}"},
        )
        uploaded.raise_for_status()
        upload_payload = uploaded.json()
        material_id = upload_payload["material"]["id"]
        ingestion = wait_job(
            client,
            f"/api/ingestion-jobs/{upload_payload['job']['id']}",
            terminal={"completed", "failed"},
            timeout_seconds=args.timeout_seconds,
        )
        require(ingestion["status"] == "completed", f"资料处理失败：{ingestion}")
        require(ingestion["progress"] == 100, "资料处理进度不是 100")

        duplicate = client.post(
            f"/api/knowledge-bases/{knowledge_base_id}/materials",
            files={"file": (f"duplicate-{token}.md", material_text, "text/markdown")},
        )
        require(duplicate.status_code == 409, "重复资料应返回 409")
        require(duplicate.json()["error"]["code"] == "DUPLICATE_MATERIAL", "重复错误码错误")

        chunks = client.get(f"/api/materials/{material_id}/chunks")
        chunks.raise_for_status()
        chunk_items = chunks.json()
        require(bool(chunk_items), "资料没有生成片段")
        require(all(item["vector_id"] for item in chunk_items), "存在未建立向量的片段")
        search = client.get(
            f"/api/knowledge-bases/{knowledge_base_id}/search",
            params={"q": token, "material_id": material_id, "limit": 5},
        )
        search.raise_for_status()
        hits = search.json()["items"]
        require(bool(hits), "唯一标识未被检索召回")
        require(hits[0]["material_id"] == material_id, "检索召回了错误资料")
        result["steps"]["upload_parse_index_search"] = {
            "status": "passed",
            "material_id": material_id,
            "chunk_count": len(chunk_items),
            "top_score": hits[0]["score"],
        }

        reprocess = client.post(f"/api/materials/{material_id}/reprocess")
        reprocess.raise_for_status()
        reprocessed = wait_job(
            client,
            f"/api/ingestion-jobs/{reprocess.json()['id']}",
            terminal={"completed", "failed"},
            timeout_seconds=args.timeout_seconds,
        )
        require(reprocessed["status"] == "completed", "资料重建索引失败")
        chunks_after = client.get(f"/api/materials/{material_id}/chunks")
        chunks_after.raise_for_status()
        require(len(chunks_after.json()) == len(chunk_items), "重建索引后片段数量异常")
        result["steps"]["reprocess"] = {"status": "passed"}

        generated = client.post(
            f"/api/materials/{material_id}/question-generation-jobs",
            json={
                "target_question_count": args.question_count,
                "allowed_types": ["single_choice", "fill_blank", "true_false"],
                "difficulty_min": 1,
                "difficulty_max": 4,
                "language": "zh-CN",
            },
        )
        generated.raise_for_status()
        generation = wait_job(
            client,
            f"/api/question-generation-jobs/{generated.json()['id']}",
            terminal={"completed", "partial", "failed"},
            timeout_seconds=args.timeout_seconds,
        )
        require(generation["status"] != "failed", f"题库生成失败：{generation}")
        require(generation["generated_count"] >= 3, "生成的有效题目不足 3 道")

        questions_response = client.get(
            "/api/questions",
            params={"knowledge_base_id": knowledge_base_id, "page": 1, "page_size": 100},
        )
        questions_response.raise_for_status()
        questions = questions_response.json()["items"]
        require(len(questions) >= 3, "题库列表数量不足")
        require(all(question["sources"] for question in questions), "存在无来源题目")
        require(all(question["vector_id"] for question in questions), "存在无向量题目")

        activated: list[dict[str, Any]] = []
        for question in questions:
            activation = client.post(f"/api/questions/{question['id']}/activate")
            activation.raise_for_status()
            activated.append(activation.json())
        edited_target = activated[0]
        edited = client.patch(
            f"/api/questions/{edited_target['id']}",
            json={"stem": edited_target["stem"] + "（P9验收修订）"},
        )
        edited.raise_for_status()
        require(edited.json()["status"] == "draft", "编辑启用题目后应退回草稿")
        reactivated = client.post(f"/api/questions/{edited_target['id']}/activate")
        reactivated.raise_for_status()
        require(reactivated.json()["status"] == "active", "修订题目重新启用失败")
        result["steps"]["question_generation_review"] = {
            "status": "passed",
            "generated_count": generation["generated_count"],
            "rejected_count": generation["rejected_count"],
            "question_types": sorted({question["question_type"] for question in questions}),
        }

        session_response = client.post(
            "/api/study/sessions",
            json={
                "knowledge_base_id": knowledge_base_id,
                "mode": "mock_exam",
                "question_count": min(3, len(activated)),
                "question_types": ["single_choice", "fill_blank", "true_false"],
                "difficulty_min": 1,
                "difficulty_max": 5,
            },
        )
        session_response.raise_for_status()
        session = session_response.json()
        session_id = session["id"]
        require(session["current_question"] is not None, "学习会话没有首题")
        require("correct_answer" not in session["current_question"], "学习接口泄露答案")
        answered = 0
        first_submission: dict[str, Any] | None = None
        while session["current_question"] is not None:
            public_question = session["current_question"]
            detail_response = client.get(f"/api/questions/{public_question['id']}")
            detail_response.raise_for_status()
            detail = detail_response.json()
            answer: str | bool | int
            if answered == 0:
                answer = wrong_answer(public_question, detail["correct_answer"])
            else:
                answer = detail["correct_answer"][0]
            submission_id = str(uuid4())
            request_body = {
                "submission_id": submission_id,
                "question_id": public_question["id"],
                "answer": answer,
                "elapsed_seconds": 1,
            }
            submitted = client.post(
                f"/api/study/sessions/{session_id}/answers", json=request_body
            )
            submitted.raise_for_status()
            answer_result = submitted.json()
            if answered == 0:
                require(answer_result["verdict"] == "incorrect", "故意错答未判为错误")
                require(bool(answer_result["rag_explanation"]), "错答没有返回讲解数据")
                replay = client.post(
                    f"/api/study/sessions/{session_id}/answers", json=request_body
                )
                replay.raise_for_status()
                require(replay.json()["idempotent_replay"] is True, "幂等重放未命中")
                conflict_body = dict(request_body)
                conflict_body["answer"] = "P9-conflict"
                conflict = client.post(
                    f"/api/study/sessions/{session_id}/answers", json=conflict_body
                )
                require(conflict.status_code == 409, "submission_id 冲突应返回 409")
                require(
                    conflict.json()["error"]["code"] == "SUBMISSION_ID_CONFLICT",
                    "submission_id 冲突错误码错误",
                )
                first_submission = answer_result
            else:
                require(answer_result["verdict"] == "correct", "正确答案未通过判分")
            answered += 1
            session = answer_result["session"]

        require(session["status"] == "completed", "学习会话未自动完成")
        require(first_submission is not None, "未执行错答分支")
        restored = client.get(f"/api/study/sessions/{session_id}")
        restored.raise_for_status()
        require(restored.json()["status"] == "completed", "会话恢复状态错误")

        mastery = client.get("/api/mastery", params={"knowledge_base_id": knowledge_base_id})
        mastery.raise_for_status()
        require(bool(mastery.json()), "没有生成掌握度记录")
        due_before = (datetime.now(UTC) + timedelta(days=2)).isoformat()
        reviews = client.get(
            "/api/reviews/due",
            params={"knowledge_base_id": knowledge_base_id, "due_before": due_before},
        )
        reviews.raise_for_status()
        require(bool(reviews.json()), "没有生成复习任务")
        history = client.get(
            "/api/study/history",
            params={"knowledge_base_id": knowledge_base_id, "page": 1, "page_size": 10},
        )
        history.raise_for_status()
        require(history.json()["total"] >= 1, "学习历史为空")
        result["steps"]["study_idempotency_progress"] = {
            "status": "passed",
            "session_id": session_id,
            "answered_count": answered,
            "correct_count": session["correct_count"],
            "incorrect_count": session["incorrect_count"],
            "mastery_count": len(mastery.json()),
            "due_review_count": len(reviews.json()),
        }

        archived = client.patch(
            f"/api/knowledge-bases/{knowledge_base_id}", json={"status": "archived"}
        )
        archived.raise_for_status()
        require(archived.json()["status"] == "archived", "知识库归档失败")
        blocked = client.post(
            "/api/study/sessions",
            json={"knowledge_base_id": knowledge_base_id, "mode": "practice"},
        )
        require(blocked.status_code == 409, "归档知识库仍能创建学习会话")
        require(blocked.json()["error"]["code"] == "KNOWLEDGE_BASE_ARCHIVED", "归档错误码错误")
        result["steps"]["archive_guard"] = {"status": "passed"}

    result["knowledge_base_id"] = knowledge_base_id
    result["status"] = "passed"
    result["duration_ms"] = round((time.perf_counter() - started) * 1000, 3)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n结果已保存：{output}")


if __name__ == "__main__":
    main()
