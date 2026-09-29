from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from typing import Any


def percentile(values: Sequence[float], percent: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(len(ordered) * percent))
    return round(ordered[rank - 1], 3)


def retrieval_metrics(samples: Sequence[dict[str, Any]]) -> dict[str, float | int]:
    if not samples:
        return {
            "sample_count": 0,
            "hit_at_1": 0.0,
            "hit_at_3": 0.0,
            "hit_at_5": 0.0,
            "recall_at_5": 0.0,
            "mrr": 0.0,
            "latency_p50_ms": 0.0,
            "latency_p95_ms": 0.0,
        }

    hits = {1: 0, 3: 0, 5: 0}
    recalls: list[float] = []
    reciprocal_ranks: list[float] = []
    latencies: list[float] = []
    for sample in samples:
        relevant = set(sample["relevant_chunk_ids"])
        retrieved = list(sample["retrieved_chunk_ids"])
        for k in hits:
            hits[k] += int(bool(relevant.intersection(retrieved[:k])))
        recall = len(relevant.intersection(retrieved[:5])) / len(relevant) if relevant else 0.0
        recalls.append(recall)
        first_rank = next((index for index, item in enumerate(retrieved, 1) if item in relevant), 0)
        reciprocal_ranks.append(1 / first_rank if first_rank else 0.0)
        latencies.append(float(sample["latency_ms"]))

    count = len(samples)
    return {
        "sample_count": count,
        "hit_at_1": round(hits[1] / count, 4),
        "hit_at_3": round(hits[3] / count, 4),
        "hit_at_5": round(hits[5] / count, 4),
        "recall_at_5": round(sum(recalls) / count, 4),
        "mrr": round(sum(reciprocal_ranks) / count, 4),
        "latency_p50_ms": percentile(latencies, 0.5),
        "latency_p95_ms": percentile(latencies, 0.95),
    }


def _answers(question: dict[str, Any]) -> list[str]:
    value = question.get("correct_answer")
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def question_is_valid(question: dict[str, Any]) -> bool:
    question_type = question.get("question_type")
    answers = _answers(question)
    if not str(question.get("stem", "")).strip() or not answers:
        return False
    if question_type == "single_choice":
        options = question.get("options")
        if not isinstance(options, list) or len(options) < 2:
            return False
        keys = [str(item.get("key", "")).strip() for item in options]
        return len(set(keys)) == len(keys) and len(answers) == 1 and answers[0] in keys
    if question_type == "true_false":
        return len(answers) == 1 and answers[0].lower() in {
            "true",
            "false",
            "正确",
            "错误",
            "对",
            "错",
        }
    if question_type == "fill_blank":
        return bool(answers)
    return False


def _normalized_stem(value: str) -> str:
    return re.sub(r"\W+", "", value, flags=re.UNICODE).lower()


def question_metrics(questions: Iterable[dict[str, Any]]) -> dict[str, Any]:
    items = list(questions)
    total = len(items)
    valid = sum(question_is_valid(item) for item in items)
    traceable = sum(bool(item.get("sources")) for item in items)
    normalized = [_normalized_stem(str(item.get("stem", ""))) for item in items]
    duplicate_count = sum(count - 1 for count in Counter(normalized).values() if count > 1)
    return {
        "question_count": total,
        "schema_valid_rate": round(valid / total, 4) if total else 0.0,
        "source_traceable_rate": round(traceable / total, 4) if total else 0.0,
        "exact_duplicate_rate": round(duplicate_count / total, 4) if total else 0.0,
        "type_distribution": dict(
            sorted(Counter(item.get("question_type") for item in items).items())
        ),
        "status_distribution": dict(sorted(Counter(item.get("status") for item in items).items())),
    }
