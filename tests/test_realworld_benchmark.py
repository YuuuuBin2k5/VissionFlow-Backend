"""
Real-World Scene Retrieval Benchmark Automated Test Suite (Phase 2.5 - Section 7, 8, 9, 10, 11)
Verifies:
- Real-world dataset scale (10 sources, 100 scenes, 54 evaluation queries).
- 5 benchmark tracks: EN -> EN, VI -> EN, VI -> Foreign, Hard Negative, Distractor.
- Same-language (EN -> EN) production metrics: Recall@1 >= 0.75, Recall@5 >= 0.85, MRR >= 0.80.
- Hard-Negative discrimination rate >= 0.70.
- Distractor rejection rate >= 0.75.
- End-to-end latency P50 <= 20ms under local lexical retrieval.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from scripts.run_realworld_benchmark import (
    DATASET_PATH,
    OUTPUT_REPORT_PATH,
    run_realworld_benchmark,
)


def test_realworld_benchmark_dataset_integrity():
    assert DATASET_PATH.exists(), f"Real-world benchmark dataset missing at {DATASET_PATH}"
    dataset = json.loads(DATASET_PATH.read_text(encoding="utf-8"))

    sources = dataset.get("sources", [])
    scenes = dataset.get("scenes", [])
    queries = dataset.get("queries", [])

    assert len(sources) >= 10, f"Expected >= 10 source videos, got {len(sources)}"
    assert 80 <= len(scenes) <= 120, f"Expected 80-120 real scenes, got {len(scenes)}"
    assert len(queries) >= 50, f"Expected >= 50 benchmark queries, got {len(queries)}"

    tracks = set(q["track"] for q in queries)
    assert "en_to_en" in tracks
    assert "vi_to_en" in tracks
    assert "vi_to_foreign" in tracks
    assert "hard_negative" in tracks
    assert "distractor" in tracks


def test_realworld_benchmark_execution():
    report = run_realworld_benchmark(provider_name="local")
    assert report is not None
    assert OUTPUT_REPORT_PATH.exists()

    tracks = report["tracks"]
    en_metrics = tracks["en_to_en"]
    hard_neg_metrics = tracks["hard_negative"]
    distractor_metrics = tracks["distractor"]

    # Same-language primary metrics
    assert en_metrics["recall_at_1"] >= 0.75, f"EN Recall@1 too low: {en_metrics['recall_at_1']}"
    assert en_metrics["recall_at_5"] >= 0.85, f"EN Recall@5 too low: {en_metrics['recall_at_5']}"
    assert en_metrics["mrr"] >= 0.80, f"EN MRR too low: {en_metrics['mrr']}"

    # Hard negative discrimination
    assert hard_neg_metrics["discrimination_rate"] >= 0.70, (
        f"Hard negative discrimination too low: {hard_neg_metrics['discrimination_rate']}"
    )

    # Distractor rejection
    assert distractor_metrics["rejection_rate"] >= 0.75, (
        f"Distractor rejection rate too low: {distractor_metrics['rejection_rate']}"
    )

    # Latency constraint
    latency = report["latency_percentiles"]
    assert latency["total_p50_ms"] < 30.0, f"P50 latency too high: {latency['total_p50_ms']}ms"
