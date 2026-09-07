"""
Production Real-World Scene Retrieval Benchmark Runner (Phase 2.5 - Section 7, 8, 9, 10, 11)
Evaluates:
- Track 1: Same-language EN -> EN (Recall@1, @3, @5, MRR)
- Track 2: Cross-language VI -> EN (Recall@1, @3, @5, MRR)
- Track 3: Cross-language VI -> Foreign/ZH (Recall@1, @3, @5, MRR)
- Track 4: Hard-negative discrimination rate (Rank(True Positive) < Rank(Hard Negative))
- Track 5: Negative distractor rejection rate
- Latency profile: P50, P95, P99 for vector search, reranker, and end-to-end retrieval.
- Retrieval mode telemetry: CLOUD_SEMANTIC vs LEXICAL_FALLBACK.

Outputs full results to scripts/realworld_benchmark_report.json
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from production.contracts import (
    RightsState,
    SceneSearchFilter,
    SourceAssetRecord,
    SourceIngestState,
    SourceSceneRecord,
    WatermarkState,
)
from production.repositories.source_repository import (
    get_embedding_repository,
    get_scene_repository,
    get_source_repository,
)
from production.embedding_service import embedding_service

DATASET_PATH = BACKEND_ROOT / "tests" / "fixtures" / "scene_retrieval_realworld_dataset.json"
OUTPUT_REPORT_PATH = BACKEND_ROOT / "scripts" / "realworld_benchmark_report.json"


def run_realworld_benchmark(
    distractor_threshold: float = 0.35,
    provider_name: str = "local",
) -> Dict[str, Any]:
    print("=" * 80)
    print("VISIONFLOW AUTO PRODUCTION - REAL-WORLD SCENE RETRIEVAL BENCHMARK")
    print(f"Target Provider: {provider_name}")
    print("=" * 80)

    if not DATASET_PATH.exists():
        raise FileNotFoundError(f"Real-world dataset not found at {DATASET_PATH}. Run generate script first.")

    dataset = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    sources_data = dataset.get("sources", [])
    scenes_data = dataset.get("scenes", [])
    queries_data = dataset.get("queries", [])

    print(f"Loaded {len(sources_data)} sources, {len(scenes_data)} scenes, and {len(queries_data)} queries.")

    source_repo = get_source_repository()
    scene_repo = get_scene_repository()
    embedding_repo = get_embedding_repository()

    # 1. Index sources and scenes
    print("\n[1/3] Indexing real-world sources and scenes...")
    for s_dict in sources_data:
        if not source_repo.get(s_dict["id"]):
            rec = SourceAssetRecord(
                id=s_dict["id"],
                source_type=s_dict.get("source_type", "video"),
                original_uri=s_dict.get("original_uri", ""),
                storage_ref=s_dict.get("storage_ref", ""),
                fingerprint=s_dict.get("fingerprint", f"fp_{s_dict['id']}"),
                fast_fingerprint=s_dict.get("fast_fingerprint"),
                duration=s_dict.get("duration", 20.0),
                width=s_dict.get("width", 640),
                height=s_dict.get("height", 360),
                fps=s_dict.get("fps", 24.0),
                codec=s_dict.get("codec", "h264"),
                language=s_dict.get("language", "en"),
                rights_state=RightsState.OWNED,
                watermark_state=WatermarkState.NONE,
                ingest_status=SourceIngestState.INGESTED,
                analysis_version="v1",
                metadata_json=s_dict.get("metadata_json", {}),
            )
            source_repo.save(rec)

    active_prov = embedding_service.local_provider if provider_name == "local" else embedding_service.primary_provider
    for scn_dict in scenes_data:
        if not scene_repo.get(scn_dict["id"]):
            scn_rec = SourceSceneRecord(
                id=scn_dict["id"],
                source_id=scn_dict["source_id"],
                start_sec=scn_dict.get("start_sec", 0.0),
                end_sec=scn_dict.get("end_sec", 2.0),
                duration_sec=scn_dict.get("duration_sec", 2.0),
                fingerprint=scn_dict.get("fingerprint", f"fp_{scn_dict['id']}"),
                visual_fingerprint=scn_dict.get("visual_fingerprint"),
                description=scn_dict.get("description", ""),
                transcript=scn_dict.get("transcript"),
                entities=scn_dict.get("entities", []),
                actions=scn_dict.get("actions", []),
                location_context=scn_dict.get("location_context"),
                shot_type=scn_dict.get("shot_type"),
                motion_score=scn_dict.get("motion_score", 0.5),
                technical_quality_score=scn_dict.get("technical_quality_score", 0.9),
                keyframes=scn_dict.get("keyframes", []),
                analysis_version="v1",
            )
            scene_repo.save(scn_rec)
            embedding_service.index_scene_embedding(scn_rec, provider=active_prov)

    print(f"  -> Successfully verified/indexed {len(scenes_data)} scenes in library.")

    # 2. Run queries
    print(f"\n[2/3] Evaluating 54 benchmark queries across 5 tracks using {active_prov.provider_name} ({active_prov.model_name})...")
    header = f"{'ID':<10} | {'Track':<16} | {'Target':<14} | {'Rank':<6} | {'Top Score':<10} | {'Status'}"
    print(header)
    print("-" * len(header))

    track_stats: Dict[str, Dict[str, Any]] = {
        "en_to_en": {"r1": 0, "r3": 0, "r5": 0, "rr_sum": 0.0, "total": 0},
        "vi_to_en": {"r1": 0, "r3": 0, "r5": 0, "rr_sum": 0.0, "total": 0},
        "vi_to_foreign": {"r1": 0, "r3": 0, "r5": 0, "rr_sum": 0.0, "total": 0},
        "hard_negative": {"discriminated": 0, "total": 0},
        "distractor": {"rejected": 0, "total": 0},
    }

    latencies_vector: List[float] = []
    latencies_rerank: List[float] = []
    latencies_total: List[float] = []
    query_eval_results: List[Dict[str, Any]] = []
    search_filter = SceneSearchFilter(provider=provider_name)

    for q in queries_data:
        qid = q["id"]
        track = q["track"]
        qtext = q["query"]
        target = q.get("target")
        hard_neg = q.get("hard_negative")

        t_start = time.perf_counter()
        results = embedding_service.search_scenes(qtext, filters=search_filter, top_k=10)
        t_elapsed = (time.perf_counter() - t_start) * 1000

        latencies_total.append(t_elapsed)
        if results:
            evidence = results[0].match_evidence
            latencies_vector.append(evidence.get("vector_search_ms", 0.0))
            latencies_rerank.append(evidence.get("rerank_ms", 0.0))
            top_score = results[0].score
            top_scene_id = results[0].scene_id
            used_mode = results[0].retrieval_mode.value
        else:
            top_score = 0.0
            top_scene_id = "NONE"
            used_mode = "NONE"

        # Track Evaluation
        status_str = "FAIL"
        rank_str = "N/A"
        rank: Optional[int] = None

        if track in ("en_to_en", "vi_to_en", "vi_to_foreign"):
            stats = track_stats[track]
            stats["total"] += 1

            for idx, res in enumerate(results):
                if res.scene_id == target:
                    rank = idx + 1
                    break

            if rank is not None:
                rank_str = str(rank)
                stats["rr_sum"] += 1.0 / rank
                if rank == 1:
                    stats["r1"] += 1
                if rank <= 3:
                    stats["r3"] += 1
                if rank <= 5:
                    stats["r5"] += 1
                status_str = f"HIT (Rank {rank})"
            else:
                rank_str = ">10"
                status_str = "MISS"

        elif track == "hard_negative":
            stats = track_stats["hard_negative"]
            stats["total"] += 1

            target_rank = next((idx + 1 for idx, r in enumerate(results) if r.scene_id == target), 999)
            hard_neg_rank = next((idx + 1 for idx, r in enumerate(results) if r.scene_id == hard_neg), 999)

            if target_rank < hard_neg_rank:
                stats["discriminated"] += 1
                status_str = f"DISCRIMINATED (Target R{target_rank} < HardNeg R{hard_neg_rank})"
                rank_str = str(target_rank)
            else:
                status_str = f"FAILED_DISCRIMINATION (Target R{target_rank} >= HardNeg R{hard_neg_rank})"
                rank_str = str(target_rank)

        elif track == "distractor":
            stats = track_stats["distractor"]
            stats["total"] += 1

            # Rejection criteria: top score below threshold
            if top_score < distractor_threshold:
                stats["rejected"] += 1
                status_str = f"REJECTED (Score {top_score:.3f} < {distractor_threshold})"
            else:
                status_str = f"FALSE_POSITIVE (Score {top_score:.3f} >= {distractor_threshold})"
            rank_str = "N/A"

        print(f"{qid:<10} | {track:<16} | {str(target):<14} | {rank_str:<6} | {top_score:<10.3f} | {status_str}")

        query_eval_results.append({
            "query_id": qid,
            "track": track,
            "query": qtext,
            "target": target,
            "hard_negative": hard_neg,
            "top_match_id": top_scene_id,
            "top_score": top_score,
            "rank": rank,
            "status": status_str,
            "retrieval_mode": used_mode,
            "latency_ms": round(t_elapsed, 2),
        })

    # 3. Compute Metrics
    def _safe_div(a: float, b: float) -> float:
        return round(a / b, 4) if b > 0 else 0.0

    metrics_en = {
        "queries": track_stats["en_to_en"]["total"],
        "recall_at_1": _safe_div(track_stats["en_to_en"]["r1"], track_stats["en_to_en"]["total"]),
        "recall_at_3": _safe_div(track_stats["en_to_en"]["r3"], track_stats["en_to_en"]["total"]),
        "recall_at_5": _safe_div(track_stats["en_to_en"]["r5"], track_stats["en_to_en"]["total"]),
        "mrr": _safe_div(track_stats["en_to_en"]["rr_sum"], track_stats["en_to_en"]["total"]),
    }

    metrics_vi = {
        "queries": track_stats["vi_to_en"]["total"],
        "recall_at_1": _safe_div(track_stats["vi_to_en"]["r1"], track_stats["vi_to_en"]["total"]),
        "recall_at_3": _safe_div(track_stats["vi_to_en"]["r3"], track_stats["vi_to_en"]["total"]),
        "recall_at_5": _safe_div(track_stats["vi_to_en"]["r5"], track_stats["vi_to_en"]["total"]),
        "mrr": _safe_div(track_stats["vi_to_en"]["rr_sum"], track_stats["vi_to_en"]["total"]),
    }

    metrics_foreign = {
        "queries": track_stats["vi_to_foreign"]["total"],
        "recall_at_1": _safe_div(track_stats["vi_to_foreign"]["r1"], track_stats["vi_to_foreign"]["total"]),
        "recall_at_3": _safe_div(track_stats["vi_to_foreign"]["r3"], track_stats["vi_to_foreign"]["total"]),
        "recall_at_5": _safe_div(track_stats["vi_to_foreign"]["r5"], track_stats["vi_to_foreign"]["total"]),
        "mrr": _safe_div(track_stats["vi_to_foreign"]["rr_sum"], track_stats["vi_to_foreign"]["total"]),
    }

    metrics_hard_neg = {
        "queries": track_stats["hard_negative"]["total"],
        "discriminated": track_stats["hard_negative"]["discriminated"],
        "discrimination_rate": _safe_div(track_stats["hard_negative"]["discriminated"], track_stats["hard_negative"]["total"]),
    }

    metrics_distractor = {
        "queries": track_stats["distractor"]["total"],
        "rejected": track_stats["distractor"]["rejected"],
        "rejection_rate": _safe_div(track_stats["distractor"]["rejected"], track_stats["distractor"]["total"]),
    }

    # Combined positive metrics across all positive queries (EN + VI + Foreign)
    pos_r1 = track_stats["en_to_en"]["r1"] + track_stats["vi_to_en"]["r1"] + track_stats["vi_to_foreign"]["r1"]
    pos_r3 = track_stats["en_to_en"]["r3"] + track_stats["vi_to_en"]["r3"] + track_stats["vi_to_foreign"]["r3"]
    pos_r5 = track_stats["en_to_en"]["r5"] + track_stats["vi_to_en"]["r5"] + track_stats["vi_to_foreign"]["r5"]
    pos_rr = track_stats["en_to_en"]["rr_sum"] + track_stats["vi_to_en"]["rr_sum"] + track_stats["vi_to_foreign"]["rr_sum"]
    pos_tot = track_stats["en_to_en"]["total"] + track_stats["vi_to_en"]["total"] + track_stats["vi_to_foreign"]["total"]

    combined_metrics = {
        "positive_queries": pos_tot,
        "overall_recall_at_1": _safe_div(pos_r1, pos_tot),
        "overall_recall_at_3": _safe_div(pos_r3, pos_tot),
        "overall_recall_at_5": _safe_div(pos_r5, pos_tot),
        "overall_mrr": _safe_div(pos_rr, pos_tot),
        "hard_negative_discrimination_rate": metrics_hard_neg["discrimination_rate"],
        "distractor_rejection_rate": metrics_distractor["rejection_rate"],
    }

    latency_metrics = {
        "vector_search_p50_ms": float(np.percentile(latencies_vector, 50)) if latencies_vector else 0.0,
        "vector_search_p95_ms": float(np.percentile(latencies_vector, 95)) if latencies_vector else 0.0,
        "vector_search_p99_ms": float(np.percentile(latencies_vector, 99)) if latencies_vector else 0.0,
        "rerank_p50_ms": float(np.percentile(latencies_rerank, 50)) if latencies_rerank else 0.0,
        "rerank_p95_ms": float(np.percentile(latencies_rerank, 95)) if latencies_rerank else 0.0,
        "total_p50_ms": float(np.percentile(latencies_total, 50)) if latencies_total else 0.0,
        "total_p95_ms": float(np.percentile(latencies_total, 95)) if latencies_total else 0.0,
        "total_p99_ms": float(np.percentile(latencies_total, 99)) if latencies_total else 0.0,
    }

    active_provider = embedding_service.primary_provider
    report = {
        "benchmark_type": "REAL_WORLD_PRODUCTION_SCALE",
        "dataset_source": "scene_retrieval_realworld_dataset.json",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "active_provider": {
            "provider": active_provider.provider_name,
            "model": active_provider.model_name,
            "dimensions": active_provider.dimensions,
            "retrieval_mode": active_provider.retrieval_mode.value,
        },
        "dataset_scale": {
            "sources": len(sources_data),
            "scenes": len(scenes_data),
            "total_queries": len(queries_data),
        },
        "overall_metrics": combined_metrics,
        "tracks": {
            "en_to_en": metrics_en,
            "vi_to_en": metrics_vi,
            "vi_to_foreign": metrics_foreign,
            "hard_negative": metrics_hard_neg,
            "distractor": metrics_distractor,
        },
        "latency_percentiles": latency_metrics,
        "evaluations": query_eval_results,
    }

    OUTPUT_REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n[3/3] BENCHMARK SUMMARY REPORT")
    print("=" * 60)
    print(f"Active Provider        : {active_provider.provider_name} ({active_provider.model_name}, dim {active_provider.dimensions})")
    print(f"Retrieval Mode         : {active_provider.retrieval_mode.value}")
    print(f"EN -> EN Recall@1      : {metrics_en['recall_at_1'] * 100:.1f}% | R@5: {metrics_en['recall_at_5'] * 100:.1f}% | MRR: {metrics_en['mrr']:.4f}")
    print(f"VI -> EN Recall@1      : {metrics_vi['recall_at_1'] * 100:.1f}% | R@5: {metrics_vi['recall_at_5'] * 100:.1f}% | MRR: {metrics_vi['mrr']:.4f}")
    print(f"VI -> Foreign Recall@1 : {metrics_foreign['recall_at_1'] * 100:.1f}% | R@5: {metrics_foreign['recall_at_5'] * 100:.1f}% | MRR: {metrics_foreign['mrr']:.4f}")
    print(f"Hard Negative Discrim. : {metrics_hard_neg['discrimination_rate'] * 100:.1f}% ({metrics_hard_neg['discriminated']}/{metrics_hard_neg['queries']})")
    print(f"Distractor Rejection   : {metrics_distractor['rejection_rate'] * 100:.1f}% ({metrics_distractor['rejected']}/{metrics_distractor['queries']})")
    print(f"Latency Total P50/P95  : {latency_metrics['total_p50_ms']:.1f}ms / {latency_metrics['total_p95_ms']:.1f}ms")
    print("=" * 60)
    print(f"Report saved to: {OUTPUT_REPORT_PATH}")

    return report


if __name__ == "__main__":
    run_realworld_benchmark()
