"""
Automated Pytest Suite for Scene Retrieval Benchmark (Section 20)
Verifies:
- Benchmark dataset validity (at least 10 fixture scenes, at least 20 queries).
- Execution of retrieval queries against two-stage semantic search.
- Recall@1 >= 0.70, Recall@5 >= 0.85, MRR >= 0.75.
- Distractor query rejection >= 75%.
"""

import json
from pathlib import Path
import pytest

from production.contracts import SourceSceneRecord
from production.repositories.source_repository import get_scene_repository
from production.embedding_service import embedding_service
from scripts.run_retrieval_benchmark import run_benchmark, DATASET_PATH, OUTPUT_REPORT_PATH


def test_benchmark_dataset_integrity():
    assert DATASET_PATH.exists(), f"Benchmark dataset missing at {DATASET_PATH}"
    data = json.loads(DATASET_PATH.read_text(encoding="utf-8"))

    scenes = data.get("scenes", [])
    queries = data.get("queries", [])

    assert len(scenes) >= 10, f"Expected at least 10 fixture scenes, found {len(scenes)}"
    assert len(queries) >= 20, f"Expected at least 20 benchmark queries, found {len(queries)}"

    categories = set(q["category"] for q in queries)
    assert "entity" in categories
    assert "action" in categories
    assert "mood_style" in categories
    assert "multi_concept" in categories
    assert "negative_distractor" in categories


def test_run_retrieval_benchmark_execution():
    report = run_benchmark()
    assert report is not None
    assert OUTPUT_REPORT_PATH.exists()

    metrics = report["metrics"]
    assert metrics["positive_queries"] >= 15
    assert metrics["distractor_queries"] >= 3

    # Spec Section 20 Quality Requirements
    assert metrics["recall_at_1"] >= 0.75, f"Recall@1 too low: {metrics['recall_at_1']}"
    assert metrics["recall_at_3"] >= 0.85, f"Recall@3 too low: {metrics['recall_at_3']}"
    assert metrics["recall_at_5"] >= 0.90, f"Recall@5 too low: {metrics['recall_at_5']}"
    assert metrics["mrr"] >= 0.80, f"MRR too low: {metrics['mrr']}"
    assert metrics["distractor_rejection_rate"] >= 0.75, f"Distractor rejection too low: {metrics['distractor_rejection_rate']}"
