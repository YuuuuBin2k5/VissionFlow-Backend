"""
Visual Resolution Benchmark Runner (Phase 4 - Section 18)
Evaluates Visual Planner and Asset Resolver over a 36-query annotated benchmark dataset.
Measures:
- Precision@1 (Target >= 75%)
- Precision@3 (Target >= 85%)
- Unresolved Rate (Target <= 5%)
- Wrong Entity/Action Rate (Target <= 8%)
- Duplicate Rate (Target = 0%)
- Rights Rejection Accuracy (Target = 100%)
Outputs report to scripts/visual_resolution_benchmark_report.json.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add backend root to sys.path
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))
os.environ["VISIONFLOW_USE_DEV_REPOSITORIES"] = "1"

from production.contracts import (
    AssetCandidate,
    RightsState,
    SceneNarration,
    ScriptPlan,
    VisualPlan,
    VisualRole,
)
from production.visual_planner import visual_planner
from production.asset_resolver import RightsGuard, asset_resolver

FIXTURE_PATH = BACKEND_DIR / "tests" / "fixtures" / "visual_resolution_benchmark_dataset.json"
REPORT_PATH = BACKEND_DIR / "scripts" / "visual_resolution_benchmark_report.json"


async def run_benchmark():
    print("=" * 70)
    print("VISIONFLOW PHASE 4 — VISUAL RESOLUTION BENCHMARK")
    print("=" * 70)

    if not FIXTURE_PATH.exists():
        raise FileNotFoundError(f"Benchmark dataset fixture not found at {FIXTURE_PATH}")

    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    items = dataset.get("items", [])
    total_queries = len(items)
    print(f"Loaded {total_queries} annotated benchmark queries from {FIXTURE_PATH.name}...")

    p1_hits = 0
    p3_hits = 0
    unresolved_count = 0
    wrong_entity_action_count = 0
    duplicate_count = 0
    role_alignment_hits = 0

    per_query_results = []
    used_asset_ids = set()

    for idx, item in enumerate(items, 1):
        q_id = item["query_id"]
        narration = item["narration_vi"]
        expected_role = item["expected_top_role"]
        gt_rel = item["ground_truth_relevance"]
        highly_relevant = set(gt_rel.get("highly_relevant_ids", []))
        acceptable = set(gt_rel.get("acceptable_ids", []))
        all_relevant = highly_relevant.union(acceptable)
        forbidden = set(gt_rel.get("forbidden_ids", []))

        # 1. Generate VisualIntent via VisualPlanner Local Provider
        single_scene = SceneNarration(
            scene_index=idx,
            narration=narration,
            estimated_speech_duration_sec=4.5,
        )
        dummy_script = ScriptPlan(
            title="Benchmark Test",
            full_script=narration,
            scenes=[single_scene],
            total_word_count=len(narration.split()),
            estimated_total_duration_sec=4.5,
        )

        visual_plan = visual_planner.generate_visual_plan(
            script_plan=dummy_script,
            run_id=f"bench_{q_id}",
        )

        # 2. Resolve Asset via AssetResolver
        resolution_result = await asset_resolver.resolve_visual_plan(
            visual_plan=visual_plan,
            run_id=f"run_{q_id}",
        )

        first_res = resolution_result.resolutions[0] if resolution_result.resolutions else None
        selected = first_res.selected_candidate if first_res else None

        if not selected or first_res.is_unresolved or selected.provider == "graphic_fallback":
            unresolved_count += 1
            is_p1 = False
            is_p3 = False
            has_conflict = False
            selected_id = "UNRESOLVED"
        else:
            selected_id = selected.asset_id

            # Check Precision@1
            is_p1 = selected_id in all_relevant
            if is_p1:
                p1_hits += 1

            # Check Precision@3
            all_top_ids = [selected_id] + [a.asset_id for a in first_res.alternate_candidates[:2]]
            is_p3 = any(aid in all_relevant for aid in all_top_ids)
            if is_p3:
                p3_hits += 1

            # Check Wrong Entity / Action / Forbidden
            has_conflict = selected_id in forbidden
            if has_conflict:
                wrong_entity_action_count += 1

            # Check Role Alignment
            first_intent = visual_plan.intents[0] if visual_plan.intents else None
            if first_intent and first_intent.visual_role == expected_role:
                role_alignment_hits += 1

        per_query_results.append({
            "query_id": q_id,
            "narration_vi": narration,
            "generated_query_en": visual_plan.intents[0].search_query_en if visual_plan.intents else "",
            "generated_role": visual_plan.intents[0].visual_role if visual_plan.intents else "",
            "expected_role": expected_role,
            "selected_asset_id": selected_id,
            "composite_score": selected.composite_score if selected else 0.0,
            "precision_1": is_p1,
            "precision_3": is_p3,
            "conflict": has_conflict,
        })

    # 3. Dedicated Rights Rejection Test
    print("\nExecuting dedicated Rights Guard rejection benchmark...")
    rights_cases = [
        (RightsState.OWNED, True),
        (RightsState.APPROVED_STOCK, True),
        (RightsState.LICENSED_COMMERCIAL, True),
        (RightsState.PERMISSION_COMMERCIAL, True),
        (RightsState.BLOCKED, False),
        (RightsState.UNKNOWN, False),  # Under strict commercial policy
    ]

    rights_test_success = 0
    for state, expected_permitted in rights_cases:
        permitted, score, reason = RightsGuard.evaluate_rights(state, strict=True)
        if permitted == expected_permitted:
            rights_test_success += 1

    rights_accuracy = rights_test_success / len(rights_cases)

    # 3b. Dedicated Multi-Scene Project Exact Duplicate Test
    print("\nExecuting multi-scene project duplicate test...")
    multi_scenes = [
        SceneNarration(scene_index=1, narration="Nghệ nhân dùng dao gọt từng thanh tre già để tạo hình đôi đũa."),
        SceneNarration(scene_index=2, narration="Khớp mộng gỗ đan chặt vào nhau mà không cần dùng đến đinh kim loại."),
        SceneNarration(scene_index=3, narration="Lưỡi thép rực đỏ dưới búa đập chan chát của người thợ rèn kiếm."),
        SceneNarration(scene_index=4, narration="Cánh tay robot đang quang khắc từng vi mạch trên đĩa bán dẫn."),
        SceneNarration(scene_index=5, narration="Người thợ đồng hồ dùng nhíp vi cơ gắp bánh răng chuyển động tourbillon."),
    ]
    multi_script = ScriptPlan(
        title="Multi Scene Run",
        full_script=" ".join(s.narration for s in multi_scenes),
        scenes=multi_scenes,
        total_word_count=50,
        estimated_total_duration_sec=20.0,
    )
    multi_vp = visual_planner.generate_visual_plan(multi_script, run_id="bench_multi")
    multi_res = await asset_resolver.resolve_visual_plan(multi_vp, run_id="bench_multi")
    chosen_ids = [r.selected_candidate.asset_id for r in multi_res.resolutions if r.selected_candidate]
    project_duplicate_count = len(chosen_ids) - len(set(chosen_ids))

    # 4. Compute Aggregate Metrics
    precision_1 = round(p1_hits / max(1, total_queries), 4)
    precision_3 = round(p3_hits / max(1, total_queries), 4)
    unresolved_rate = round(unresolved_count / max(1, total_queries), 4)
    wrong_rate = round(wrong_entity_action_count / max(1, total_queries), 4)
    dup_rate = round(project_duplicate_count / max(1, len(multi_scenes)), 4)
    role_rate = round(role_alignment_hits / max(1, total_queries), 4)

    print("\n" + "=" * 70)
    print("BENCHMARK RESULTS & QUALITY TARGET VERIFICATION")
    print("=" * 70)
    print(f"Total Queries Evaluated:          {total_queries}")
    print(f"Precision@1:                      {precision_1 * 100:.1f}% (Target >= 75%) -> {'PASS' if precision_1 >= 0.75 else 'FAIL'}")
    print(f"Precision@3:                      {precision_3 * 100:.1f}% (Target >= 85%) -> {'PASS' if precision_3 >= 0.85 else 'FAIL'}")
    print(f"Unresolved Rate:                  {unresolved_rate * 100:.1f}% (Target <= 5%)  -> {'PASS' if unresolved_rate <= 0.05 else 'FAIL'}")
    print(f"Wrong Entity/Action Rate:         {wrong_rate * 100:.1f}% (Target <= 8%)  -> {'PASS' if wrong_rate <= 0.08 else 'FAIL'}")
    print(f"Exact Duplicate Rate:             {dup_rate * 100:.1f}% (Target = 0%)   -> {'PASS' if dup_rate == 0.0 else 'FAIL'}")
    print(f"Rights Rejection Accuracy:        {rights_accuracy * 100:.1f}% (Target = 100%) -> {'PASS' if rights_accuracy == 1.0 else 'FAIL'}")
    print(f"Visual Role Alignment Rate:       {role_rate * 100:.1f}% (Uncalibrated Baseline — Informational Only)")
    print("=" * 70)

    report_data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_queries": total_queries,
        "metrics": {
            "precision_at_1": precision_1,
            "precision_at_3": precision_3,
            "unresolved_rate": unresolved_rate,
            "wrong_entity_action_rate": wrong_rate,
            "duplicate_rate": dup_rate,
            "rights_rejection_accuracy": rights_accuracy,
            "role_alignment_rate": role_rate,
        },
        "targets": {
            "precision_at_1": ">= 0.75",
            "precision_at_3": ">= 0.85",
            "unresolved_rate": "<= 0.05",
            "wrong_entity_action_rate": "<= 0.08",
            "duplicate_rate": "== 0.0",
            "rights_rejection_accuracy": "== 1.0",
        },
        "all_targets_passed": (
            precision_1 >= 0.75
            and precision_3 >= 0.85
            and unresolved_rate <= 0.05
            and wrong_rate <= 0.08
            and dup_rate == 0.0
            and rights_accuracy == 1.0
        ),
        "query_results": per_query_results,
    }

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2, ensure_ascii=False)

    print(f"Detailed benchmark report saved to: {REPORT_PATH}")
    return report_data


if __name__ == "__main__":
    asyncio.run(run_benchmark())
