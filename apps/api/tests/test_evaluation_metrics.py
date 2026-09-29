from study_agent.evaluation.metrics import question_metrics, retrieval_metrics


def test_retrieval_metrics() -> None:
    metrics = retrieval_metrics(
        [
            {
                "relevant_chunk_ids": ["a"],
                "retrieved_chunk_ids": ["a", "b"],
                "latency_ms": 10,
            },
            {
                "relevant_chunk_ids": ["c"],
                "retrieved_chunk_ids": ["b", "c"],
                "latency_ms": 20,
            },
        ]
    )
    assert metrics["hit_at_1"] == 0.5
    assert metrics["hit_at_3"] == 1.0
    assert metrics["recall_at_5"] == 1.0
    assert metrics["mrr"] == 0.75
    assert metrics["latency_p95_ms"] == 20


def test_question_metrics_distinguish_schema_and_traceability() -> None:
    metrics = question_metrics(
        [
            {
                "question_type": "single_choice",
                "stem": "选择正确答案",
                "options": [{"key": "A"}, {"key": "B"}],
                "correct_answer": ["A"],
                "sources": [{"chunk_id": "chunk-1"}],
                "status": "active",
            },
            {
                "question_type": "fill_blank",
                "stem": "填写____",
                "correct_answer": [],
                "sources": [],
                "status": "draft",
            },
        ]
    )
    assert metrics["schema_valid_rate"] == 0.5
    assert metrics["source_traceable_rate"] == 0.5
    assert metrics["exact_duplicate_rate"] == 0.0
