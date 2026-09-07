"""
Cross-Language Retrieval Benchmark for VisionFlow (Phase 3.5)
Evaluates 20+ realistic Vietnamese visual intent queries against English/bilingual scene library.
Measures Recall@1, Recall@3, latency, and query normalization telemetry.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

backend_root = Path(__file__).resolve().parent.parent
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from production.contracts import RightsState, SourceSceneRecord
from production.embedding_service import embedding_service, VietnameseQueryTranslationBridge
from production.repositories.source_repository import get_scene_repository, get_source_repository

BENCHMARK_SCENES = [
    {
        "id": "scn_bm_01",
        "description": "Japanese master carpenter using traditional chisel to carve mortise and tenon wood joinery",
        "entities": ["carpenter", "wood joinery", "chisel", "timber"],
        "actions": ["carving", "chiseling"],
        "shot_type": "close-up",
    },
    {
        "id": "scn_bm_02",
        "description": "Boiling rich tonkotsu broth with noodles and pork chashu in ramen kitchen",
        "entities": ["ramen", "noodle", "broth", "pork"],
        "actions": ["boiling", "simmering"],
        "shot_type": "medium",
    },
    {
        "id": "scn_bm_03",
        "description": "Technician in cleanroom inspecting silicon wafer microchip under microscope",
        "entities": ["cleanroom", "silicon wafer", "microchip", "semiconductor"],
        "actions": ["inspecting", "fabricating"],
        "shot_type": "macro",
    },
    {
        "id": "scn_bm_04",
        "description": "Dramatic aerial wide shot of snow covered alpine mountain peaks and glacier at sunset",
        "entities": ["alpine", "mountain peak", "glacier", "snow"],
        "actions": ["flying", "aerial pan"],
        "shot_type": "wide",
    },
    {
        "id": "scn_bm_05",
        "description": "Lead surgeon in operating room holding scalpel performing complex surgical operation",
        "entities": ["surgeon", "operating room", "scalpel", "doctor"],
        "actions": ["operating", "cutting"],
        "shot_type": "close-up",
    },
    {
        "id": "scn_bm_06",
        "description": "Sprinter athlete sprinting on track field in stadium reaching finish line",
        "entities": ["athlete", "sprinter", "stadium", "track"],
        "actions": ["running", "sprinting"],
        "shot_type": "tracking",
    },
    {
        "id": "scn_bm_07",
        "description": "Ancient buddhist pagoda temple with bronze bell in zen garden",
        "entities": ["pagoda", "temple", "bell", "zen"],
        "actions": ["ringing", "praying"],
        "shot_type": "medium",
    },
    {
        "id": "scn_bm_08",
        "description": "Underwater view of colorful coral reef with clownfish swimming among anemone",
        "entities": ["coral reef", "clownfish", "underwater", "marine"],
        "actions": ["swimming", "floating"],
        "shot_type": "underwater",
    },
    {
        "id": "scn_bm_09",
        "description": "Futuristic cyborg robot walking through rainy cyberpunk city illuminated by neon lights",
        "entities": ["robot", "cyberpunk", "neon lights", "futuristic city"],
        "actions": ["walking", "glowing"],
        "shot_type": "wide",
    },
    {
        "id": "scn_bm_10",
        "description": "Film director on studio set calling action through clapperboard near cinema camera",
        "entities": ["director", "film set", "clapperboard", "camera"],
        "actions": ["directing", "filming"],
        "shot_type": "medium",
    },
]

BENCHMARK_QUERIES = [
    # 1-4: Woodworking & Craft
    ("thợ mộc đục mộng gỗ", "scn_bm_01"),
    ("cận cảnh lưỡi đục gỗ", "scn_bm_01"),
    ("kỹ thuật ghép gỗ kigumi", "scn_bm_01"),
    ("bào gỗ thủ công truyền thống", "scn_bm_01"),
    # 5-7: Culinary & Ramen
    ("nấu nước dùng mì ramen sôi sùng sục", "scn_bm_02"),
    ("bát mì với thịt hầm", "scn_bm_02"),
    ("nồi nước dùng đang sôi", "scn_bm_02"),
    # 8-10: Semiconductor & High-tech
    ("cận cảnh wafer silicon vi mạch", "scn_bm_03"),
    ("phòng sạch sản xuất bán dẫn", "scn_bm_03"),
    ("kỹ sư kiểm tra tấm vi mạch", "scn_bm_03"),
    # 11-13: Alpine & Landscapes
    ("toàn cảnh núi tuyết hoàng hôn", "scn_bm_04"),
    ("đỉnh núi băng giá hùng vĩ", "scn_bm_04"),
    ("sông băng trên dãy núi cao", "scn_bm_04"),
    # 14-16: Medical & Surgery
    ("bác sĩ phẫu thuật trong phòng mổ", "scn_bm_05"),
    ("cầm dao mổ chuyên dụng", "scn_bm_05"),
    ("ca phẫu thuật y khoa bệnh viện", "scn_bm_05"),
    # 17-18: Sports & Athletics
    ("vận động viên chạy nước rút", "scn_bm_06"),
    ("chạy đua trên sân vận động", "scn_bm_06"),
    # 19-20: Cultural & Underwater
    ("chùa cổ thanh tịnh hoàng hôn", "scn_bm_07"),
    ("rạn san hô và cá hề dưới biển", "scn_bm_08"),
    # 21-22: Futuristic & Cinema
    ("thành phố tương lai ánh đèn neon robot", "scn_bm_09"),
    ("đạo diễn chỉ đạo trên phim trường", "scn_bm_10"),
]


def run_benchmark() -> Dict[str, Any]:
    scene_repo = get_scene_repository()
    # Populate benchmark scenes in in-memory repo
    for scn_data in BENCHMARK_SCENES:
        record = SourceSceneRecord(
            id=scn_data["id"],
            source_id="src_benchmark_01",
            start_sec=0.0,
            end_sec=5.0,
            duration_sec=5.0,
            fingerprint=f"fp_{scn_data['id']}",
            description=scn_data["description"],
            entities=[{"name": e, "value": e} for e in scn_data["entities"]],
            actions=[{"name": a, "value": a} for a in scn_data["actions"]],
            shot_type=scn_data["shot_type"],
            motion_score=0.6,
            technical_quality_score=0.9,
        )
        scene_repo.save(record)

    total_queries = len(BENCHMARK_QUERIES)
    recall_at_1_hits = 0
    recall_at_3_hits = 0
    total_latency_ms = 0.0
    detailed_results = []

    print(f"\n=======================================================")
    print(f"Running Cross-Language Retrieval Benchmark ({total_queries} queries)")
    print(f"=======================================================")

    for idx, (vi_query, expected_id) in enumerate(BENCHMARK_QUERIES):
        t0 = time.perf_counter()
        results = embedding_service.search_scenes(vi_query, top_k=3)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        total_latency_ms += elapsed_ms

        retrieved_ids = [r.scene_id for r in results]
        hit_at_1 = len(retrieved_ids) > 0 and retrieved_ids[0] == expected_id
        hit_at_3 = expected_id in retrieved_ids[:3]

        if hit_at_1:
            recall_at_1_hits += 1
        if hit_at_3:
            recall_at_3_hits += 1

        top_match = results[0] if results else None
        top_score = top_match.score if top_match else 0.0
        telemetry = top_match.match_evidence if top_match else {}

        detailed_results.append({
            "query_index": idx + 1,
            "query_original": vi_query,
            "expected_id": expected_id,
            "top_retrieved_id": retrieved_ids[0] if retrieved_ids else None,
            "top_score": top_score,
            "hit_at_1": hit_at_1,
            "hit_at_3": hit_at_3,
            "latency_ms": round(elapsed_ms, 2),
            "translation_used": telemetry.get("translation_used", False),
            "translated_query": telemetry.get("translated_query"),
        })

        status_sym = "[HIT@1]" if hit_at_1 else ("[HIT@3]" if hit_at_3 else "[MISS]")
        print(f"[{idx+1:02d}/{total_queries}] {status_sym} '{vi_query}' -> Top: {retrieved_ids[:1]} (Exp: {expected_id}) [Score: {top_score:.2f}, Latency: {elapsed_ms:.1f}ms]")

    r1_rate = round(recall_at_1_hits / total_queries * 100, 1)
    r3_rate = round(recall_at_3_hits / total_queries * 100, 1)
    avg_latency = round(total_latency_ms / total_queries, 2)

    summary = {
        "total_queries": total_queries,
        "recall_at_1_pct": r1_rate,
        "recall_at_3_pct": r3_rate,
        "average_latency_ms": avg_latency,
        "detailed_results": detailed_results,
    }

    print(f"\n-------------------------------------------------------")
    print(f"Cross-Language Benchmark Summary:")
    print(f"  Total Queries: {total_queries}")
    print(f"  Recall@1:      {r1_rate}% ({recall_at_1_hits}/{total_queries})")
    print(f"  Recall@3:      {r3_rate}% ({recall_at_3_hits}/{total_queries})")
    print(f"  Avg Latency:   {avg_latency} ms")
    print(f"=======================================================\n")

    return summary


if __name__ == "__main__":
    summary = run_benchmark()
    with open("scripts/cross_language_benchmark_results.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print("Benchmark results written to scripts/cross_language_benchmark_results.json")
