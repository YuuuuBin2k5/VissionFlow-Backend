"""
Standalone Scene Retrieval Benchmark Suite (Phase 2 - Section 20)
Evaluates:
- Recall@1
- Recall@3
- Recall@5
- Mean Reciprocal Rank (MRR)
- Distractor / Negative query calibration

Outputs machine-readable report to scripts/retrieval_benchmark_report.json
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from production.contracts import (
    RightsState,
    SceneSearchFilter,
    SourceAssetRecord,
    SourceIngestState,
    SourceKind,
    SourceSceneRecord,
)
from production.repositories.source_repository import (
    get_embedding_repository,
    get_scene_repository,
    get_source_repository,
)
from production.embedding_service import embedding_service

DATASET_PATH = BACKEND_ROOT / "tests" / "fixtures" / "scene_retrieval_sanity_dataset.json"
OUTPUT_REPORT_PATH = BACKEND_ROOT / "scripts" / "retrieval_benchmark_report.json"


def run_benchmark(provider_name: str = "local"):
    print("=" * 70)
    print("VISIONFLOW AUTO PRODUCTION - SCENE RETRIEVAL BENCHMARK SUITE")
    print(f"Target Provider: {provider_name}")
    print("=" * 70)

    if not DATASET_PATH.exists():
        raise FileNotFoundError(f"Benchmark dataset not found at {DATASET_PATH}")

    data = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    scenes_data = data.get("scenes", [])
    queries_data = data.get("queries", [])

    print(f"Loaded {len(scenes_data)} fixture scenes and {len(queries_data)} evaluation queries.")

    scene_repo = get_scene_repository()
    embedding_repo = get_embedding_repository()

    active_prov = embedding_service.local_provider if provider_name == "local" else embedding_service.primary_provider
    search_filter = SceneSearchFilter(provider=provider_name)

    # 1. Index fixture scenes into repository
    print("\n[1/3] Indexing scenes and generating embeddings...")
    source_repo = get_source_repository()
    indexed_scenes: List[SourceSceneRecord] = []

    # First ensure parent sources exist for referential integrity
    for scn_dict in scenes_data:
        src_id = scn_dict["source_id"]
        if not source_repo.get(src_id):
            source_repo.save(
                SourceAssetRecord(
                    id=src_id,
                    source_type="video",
                    fingerprint=f"fp_{src_id}",
                    duration=10.0,
                    width=1920,
                    height=1080,
                    fps=30.0,
                    codec="h264",
                    rights_state=RightsState.OWNED,
                    ingest_status=SourceIngestState.INGESTED,
                )
            )

    for scn_dict in scenes_data:
        record_data = {
            "id": scn_dict["id"],
            "source_id": scn_dict["source_id"],
            "start_sec": scn_dict.get("start_sec", 0.0),
            "end_sec": scn_dict.get("end_sec", 5.0),
            "duration_sec": scn_dict.get("duration_sec", 5.0),
            "fingerprint": scn_dict.get("fingerprint", f"fp_{scn_dict['id']}"),
            "description": scn_dict.get("description", ""),
            "transcript": scn_dict.get("transcript"),
            "entities": scn_dict.get("entities", []),
            "actions": scn_dict.get("actions", []),
            "location_context": scn_dict.get("location_context"),
            "shot_type": scn_dict.get("shot_type"),
            "motion_score": scn_dict.get("motion_score", 0.5),
            "technical_quality_score": scn_dict.get("technical_quality_score", 0.85),
            "keyframes": scn_dict.get("keyframes", []),
        }
        scene_obj = SourceSceneRecord(**record_data)
        scene_repo.save(scene_obj)
        embedding_service.index_scene_embedding(scene_obj, provider=active_prov)
        indexed_scenes.append(scene_obj)

    print(f"  -> Successfully indexed {len(indexed_scenes)} scenes.")

    # 2. Run retrieval queries
    print("\n[2/3] Executing retrieval benchmark queries...")

    positive_results = []
    negative_results = []

    r1_hits = 0
    r3_hits = 0
    r5_hits = 0
    rr_sum = 0.0

    header = f"{'ID':<5} | {'Category':<19} | {'Target':<23} | {'Rank':<6} | {'Top Match':<23} | {'Score':<6} | {'Status'}"
    print(header)
    print("-" * 105)

    for q_item in queries_data:
        qid = q_item["id"]
        category = q_item["category"]
        query_text = q_item["query"]
        target_id = q_item.get("target_scene_id")

        results = embedding_service.search_scenes(query_text, filters=search_filter, top_k=5)
        top_match = results[0] if results else None
        top_id = top_match.scene_id if top_match else "NONE"
        top_score = top_match.score if top_match else 0.0

        if target_id is not None:
            # Positive query evaluation
            ranks = [idx for idx, r in enumerate(results) if r.scene_id == target_id]
            if ranks:
                rank_0 = ranks[0]
                rank_1based = rank_0 + 1
                rr = 1.0 / rank_1based
                if rank_1based == 1:
                    r1_hits += 1
                if rank_1based <= 3:
                    r3_hits += 1
                if rank_1based <= 5:
                    r5_hits += 1
            else:
                rank_1based = None
                rr = 0.0

            rr_sum += rr

            status = "PASS (Rank 1)" if rank_1based == 1 else (f"PASS (Rank {rank_1based})" if rank_1based else "FAIL (Not in top 5)")
            row = f"{qid:<5} | {category:<19} | {target_id:<23} | {str(rank_1based or '>5'):<6} | {top_id:<23} | {top_score:<6.3f} | {status}"
            print(row)

            positive_results.append({
                "query_id": qid,
                "category": category,
                "query": query_text,
                "target_scene_id": target_id,
                "found_rank": rank_1based,
                "top_result_id": top_id,
                "top_result_score": top_score,
                "reciprocal_rank": rr,
                "match_evidence": top_match.match_evidence if top_match else {}
            })
        else:
            # Negative / Distractor evaluation
            # Negative queries should have low composite score (< 0.25) or no strong overlap
            rejected = top_score < 0.25 or (top_match and len(top_match.match_evidence.get("entity_matches", [])) == 0 and len(top_match.match_evidence.get("action_matches", [])) == 0)
            status = "CORRECTLY REJECTED" if rejected else "FALSE POSITIVE"
            row = f"{qid:<5} | {category:<19} | {'NONE (distractor)':<23} | {'N/A':<6} | {top_id:<23} | {top_score:<6.3f} | {status}"
            print(row)

            negative_results.append({
                "query_id": qid,
                "category": category,
                "query": query_text,
                "top_result_id": top_id,
                "top_result_score": top_score,
                "rejected": rejected,
                "match_evidence": top_match.match_evidence if top_match else {}
            })

    total_positive = len(positive_results)
    recall_1 = round(r1_hits / total_positive, 4) if total_positive else 0.0
    recall_3 = round(r3_hits / total_positive, 4) if total_positive else 0.0
    recall_5 = round(r5_hits / total_positive, 4) if total_positive else 0.0
    mrr = round(rr_sum / total_positive, 4) if total_positive else 0.0

    total_negative = len(negative_results)
    distractor_rejection_rate = round(sum(1 for n in negative_results if n["rejected"]) / total_negative, 4) if total_negative else 1.0

    print("\n[3/3] BENCHMARK SUMMARY RESULTS")
    print("=" * 50)
    print(f"Total Evaluation Queries  : {len(queries_data)}")
    print(f"  - Positive Queries      : {total_positive}")
    print(f"  - Distractor Queries    : {total_negative}")
    print("-" * 50)
    print(f"Recall@1                  : {recall_1 * 100:.1f}% ({r1_hits}/{total_positive})")
    print(f"Recall@3                  : {recall_3 * 100:.1f}% ({r3_hits}/{total_positive})")
    print(f"Recall@5                  : {recall_5 * 100:.1f}% ({r5_hits}/{total_positive})")
    print(f"MRR (Mean Reciprocal Rank): {mrr:.4f}")
    print(f"Distractor Rejection Rate : {distractor_rejection_rate * 100:.1f}%")
    print("=" * 50)

    report = {
        "benchmark_version": "v1_phase2",
        "dataset_path": str(DATASET_PATH),
        "metrics": {
            "total_queries": len(queries_data),
            "positive_queries": total_positive,
            "distractor_queries": total_negative,
            "recall_at_1": recall_1,
            "recall_at_3": recall_3,
            "recall_at_5": recall_5,
            "mrr": mrr,
            "distractor_rejection_rate": distractor_rejection_rate,
        },
        "positive_queries": positive_results,
        "negative_queries": negative_results,
    }

    OUTPUT_REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nSaved full machine-readable benchmark report to: {OUTPUT_REPORT_PATH}")
    return report


if __name__ == "__main__":
    run_benchmark()
