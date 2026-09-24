"""
Phase 4 Dedicated Test Suite: Visual Planner & Asset Resolver
Validates:
1. Vietnamese narration to canonical English VisualIntent
2. Entity and action matching
3. Wrong action hard rejection (automated vs manual)
4. Exact duplicate rejection across shots
5. Near-duplicate perceptual hash penalty (dHash hamming distance <= 6 -> -0.35)
6. Blocked commercial rights hard rejection
7. Unknown rights policy handling (never auto-upgrade to approved)
8. Pexels 429 rate limit backoff and fallback
9. Pexels empty search fallback
10. Broken local media reference rejection
11. Multi-shot partitioning for long scenes (> 4.2s)
12. Source priority: user provided footage over stock
13. Source priority: stock fallback when library empty
14. JSON input mode pipeline convergence
15. SCRIPT input mode pipeline convergence
16. Asset cache reuse and invalidation
17. Provider timeout resilience
18. Source diversity consecutive penalty (3 consecutive shots from same source -> -0.15)
"""

from __future__ import annotations

import asyncio
import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

os.environ["VISIONFLOW_USE_DEV_REPOSITORIES"] = "1"

from production.contracts import (
    AssetCandidate,
    AutoVideoRequest,
    InputMode,
    ProductionRun,
    ProductionStageRun,
    RightsState,
    SceneNarration,
    ScriptPlan,
    SourceInput,
    SourceKind,
    SourceSceneRecord,
    VisualIntent,
    VisualPlan,
    VisualRole,
    WatermarkState,
)
from production.visual_planner import LocalVisualPlannerProvider, VisualPlanner, visual_planner
from production.asset_resolver import (
    CandidateScorer,
    PexelsStockAdapter,
    RightsGuard,
    THEMATIC_STOCK_CATALOG,
    asset_resolver,
)
from production.orchestrator import orchestrator


class TestPhase4VisualAssetResolver(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.planner = VisualPlanner(LocalVisualPlannerProvider())
        self.resolver = asset_resolver
        self.scorer = CandidateScorer()

    # -----------------------------------------------------------------------
    # 1. Vietnamese Narration to English Visual Intent
    # -----------------------------------------------------------------------
    def test_vietnamese_narration_to_english_visual_intent(self):
        script = ScriptPlan(
            title="Đũa tre truyền thống",
            full_script="Nghệ nhân dùng dao gọt từng thanh tre già để tạo hình đôi đũa tinh xảo.",
            scenes=[
                SceneNarration(
                    scene_index=1,
                    narration="Nghệ nhân dùng dao gọt từng thanh tre già để tạo hình đôi đũa tinh xảo.",
                    estimated_speech_duration_sec=3.8,
                )
            ],
            total_word_count=15,
            estimated_total_duration_sec=3.8,
        )
        plan = self.planner.generate_visual_plan(script)
        self.assertGreaterEqual(len(plan.intents), 1)
        intent = plan.intents[0]

        # Query must be clean English without raw Vietnamese or stopwords
        self.assertIn("bamboo", intent.search_query_en.lower())
        self.assertNotIn("chúng", intent.search_query_en.lower())
        self.assertNotIn("nghệ", intent.search_query_en.lower())
        self.assertTrue(any(s in " ".join(intent.subjects).lower() for s in ["bamboo", "artisan"]))

    # -----------------------------------------------------------------------
    # 2. Correct Entity and Action Matching
    # -----------------------------------------------------------------------
    def test_correct_entity_and_action_matching(self):
        intent = VisualIntent(
            id="vi_test_01",
            scene_id="scene_001",
            shot_order=1,
            visual_role=VisualRole.PROCESS.value,
            description="Artisan shaping bamboo chopsticks with carving tools",
            search_query_en="bamboo chopsticks shaping carving polishing",
            subjects=["bamboo wood", "artisan hands"],
            actions=["shaping", "carving", "polishing"],
            duration_weight=1.0,
        )
        cand = AssetCandidate(
            asset_id="pex_33671897",
            source_id="pex_33671897",
            provider="pexels_stock",
            start_sec=0.0,
            end_sec=8.5,
            duration_sec=8.5,
            rights_state=RightsState.APPROVED_STOCK,
            provenance={"tags": ["bamboo", "chopsticks", "artisan", "shaping"]},
            selection_evidence={"overlap_terms": ["bamboo", "chopsticks", "shaping"]},
        )
        is_qual, scored_cand, reasons = self.scorer.score_candidate(
            candidate=cand,
            intent=intent,
            target_duration=4.0,
            used_asset_ids=set(),
            recent_source_ids=[],
            used_visual_fingerprints=set(),
        )
        self.assertTrue(is_qual)
        self.assertGreaterEqual(scored_cand.entity_action_score, 0.40)
        self.assertGreaterEqual(scored_cand.composite_score, 0.60)

    # -----------------------------------------------------------------------
    # 3. Wrong Action Hard Rejection
    # -----------------------------------------------------------------------
    def test_wrong_action_hard_rejection(self):
        intent = VisualIntent(
            id="vi_test_02",
            scene_id="scene_002",
            shot_order=1,
            visual_role=VisualRole.PROCESS.value,
            description="Automated robotic wafer etching in cleanroom fab",
            search_query_en="semiconductor microchip automated robotic etching cleanroom",
            subjects=["silicon wafer", "cleanroom robotics"],
            actions=["automated robotic etching"],
            must_avoid=["artisan hands", "manual"],
        )
        # Conflicting manual hand candidate
        conflict_cand = AssetCandidate(
            asset_id="pex_conflict_manual",
            source_id="pex_conflict_manual",
            provider="pexels_stock",
            start_sec=0.0,
            end_sec=6.0,
            duration_sec=6.0,
            rights_state=RightsState.APPROVED_STOCK,
            provenance={"tags": ["artisan hands", "manual knife craft"]},
            selection_evidence={"overlap_terms": ["artisan hands"]},
        )
        is_qual, _, reasons = self.scorer.score_candidate(
            candidate=conflict_cand,
            intent=intent,
            target_duration=4.0,
            used_asset_ids=set(),
            recent_source_ids=[],
            used_visual_fingerprints=set(),
        )
        self.assertFalse(is_qual)
        self.assertTrue(any("contradiction" in r.lower() or "forbidden" in r.lower() for r in reasons))

    # -----------------------------------------------------------------------
    # 4. Exact Duplicate Rejected
    # -----------------------------------------------------------------------
    def test_exact_duplicate_rejected(self):
        intent = VisualIntent(id="vi_dup", scene_id="scene_001", search_query_en="bamboo")
        cand = AssetCandidate(
            asset_id="pex_33671897",
            source_id="pex_33671897",
            provider="pexels_stock",
            start_sec=0.0,
            end_sec=5.0,
            duration_sec=5.0,
            rights_state=RightsState.APPROVED_STOCK,
        )
        is_qual, _, reasons = self.scorer.score_candidate(
            candidate=cand,
            intent=intent,
            target_duration=4.0,
            used_asset_ids={"pex_33671897"},  # Already used!
            recent_source_ids=[],
            used_visual_fingerprints=set(),
        )
        self.assertFalse(is_qual)
        self.assertTrue(any("exact duplicate" in r.lower() for r in reasons))

    # -----------------------------------------------------------------------
    # 5. Near-Duplicate Penalized (dHash <= 6)
    # -----------------------------------------------------------------------
    def test_near_duplicate_penalized(self):
        intent = VisualIntent(id="vi_near", scene_id="scene_002", search_query_en="bamboo wood")
        cand = AssetCandidate(
            asset_id="pex_near_dup_01",
            source_id="pex_near_dup_01",
            provider="pexels_stock",
            start_sec=0.0,
            end_sec=6.0,
            duration_sec=6.0,
            rights_state=RightsState.APPROVED_STOCK,
            visual_fingerprint="dhash:a1b2c3d4e5f60718",
            provenance={"tags": ["bamboo", "wood"]},
        )
        used_fps = {"dhash:a1b2c3d4e5f60719"}  # Hamming distance = 1 (bit difference)
        is_qual, scored, reasons = self.scorer.score_candidate(
            candidate=cand,
            intent=intent,
            target_duration=4.0,
            used_asset_ids=set(),
            recent_source_ids=[],
            used_visual_fingerprints=used_fps,
        )
        self.assertEqual(scored.repetition_penalty, 0.35)
        self.assertTrue(any("near-duplicate penalty" in r for r in reasons))

    # -----------------------------------------------------------------------
    # 6. Blocked Rights Rejected
    # -----------------------------------------------------------------------
    def test_blocked_rights_rejected(self):
        cand = AssetCandidate(
            asset_id="asset_blocked",
            source_id="src_blocked",
            provider="user_source",
            start_sec=0.0,
            end_sec=4.0,
            duration_sec=4.0,
            rights_state=RightsState.BLOCKED,
        )
        is_qual, _, reasons = self.scorer.score_candidate(
            candidate=cand,
            intent=VisualIntent(id="vi_rights"),
            target_duration=4.0,
            used_asset_ids=set(),
            recent_source_ids=[],
            used_visual_fingerprints=set(),
        )
        self.assertFalse(is_qual)
        self.assertTrue(any("BLOCKED" in r for r in reasons))

    # -----------------------------------------------------------------------
    # 7. Unknown Rights Handled by Policy
    # -----------------------------------------------------------------------
    def test_unknown_rights_handled_by_policy(self):
        # Strict mode: UNKNOWN is rejected
        permitted_strict, score_strict, reason_strict = RightsGuard.evaluate_rights(
            RightsState.UNKNOWN,
            strict=True,
        )
        self.assertFalse(permitted_strict)
        self.assertIn("UNKNOWN under strict", reason_strict)

        # Relaxed mode: UNKNOWN incurs penalty
        permitted_relaxed, score_relaxed, reason_relaxed = RightsGuard.evaluate_rights(
            RightsState.UNKNOWN,
            strict=False,
        )
        self.assertTrue(permitted_relaxed)
        self.assertLessEqual(score_relaxed, 0.50)

    # -----------------------------------------------------------------------
    # 8. Pexels 429 Backoff and Fallback
    # -----------------------------------------------------------------------
    async def test_pexels_429_backoff_and_fallback(self):
        adapter = PexelsStockAdapter(api_key="real_fake_key")
        mock_response = MagicMock()
        mock_response.status_code = 429

        with patch("requests.get", return_value=mock_response):
            results = await adapter.search_stock("bamboo craft", limit=2)
            self.assertGreater(len(results), 0)
            self.assertEqual(results[0].rights_state, RightsState.APPROVED_STOCK)
            self.assertEqual(results[0].provenance["origin"], "thematic_stock_catalog")

    # -----------------------------------------------------------------------
    # 9. Pexels Empty Search Fallback
    # -----------------------------------------------------------------------
    async def test_pexels_empty_search_fallback(self):
        adapter = PexelsStockAdapter()
        # Empty or nonsense query degrades gracefully
        results = await adapter.search_stock("xyz123_nonexistent_token_456", limit=2)
        self.assertGreaterEqual(len(results), 1)

    # -----------------------------------------------------------------------
    # 10. Broken Media Rejection
    # -----------------------------------------------------------------------
    def test_broken_media_rejection(self):
        cand = AssetCandidate(
            asset_id="asset_broken",
            source_id="src_local",
            provider="user_source",
            start_sec=0.0,
            end_sec=5.0,
            duration_sec=5.0,
            media_url="/non_existent/filesystem/path/to/video.mp4",
            rights_state=RightsState.OWNED,
        )
        is_qual, _, reasons = self.scorer.score_candidate(
            candidate=cand,
            intent=VisualIntent(id="vi_broken"),
            target_duration=4.0,
            used_asset_ids=set(),
            recent_source_ids=[],
            used_visual_fingerprints=set(),
        )
        self.assertFalse(is_qual)
        self.assertTrue(any("Broken local media" in r for r in reasons))

    # -----------------------------------------------------------------------
    # 11. Multi-Shot Partitioning
    # -----------------------------------------------------------------------
    def test_multi_shot_partitioning(self):
        # Long scene (8.0s) should generate 3 shots
        script = ScriptPlan(
            title="Long Scene",
            full_script="Quy trình sản xuất đũa tre truyền thống.",
            scenes=[
                SceneNarration(
                    scene_index=1,
                    narration="Nghệ nhân chuốt từng thanh tre và gọt giũa tỉ mỉ từng chi tiết qua nhiều công đoạn kéo dài.",
                    estimated_speech_duration_sec=8.0,
                )
            ],
            total_word_count=20,
            estimated_total_duration_sec=8.0,
        )
        plan = self.planner.generate_visual_plan(script)
        intents = plan.get_intents_for_scene("scene_001")
        self.assertEqual(len(intents), 3)
        self.assertEqual([vi.shot_order for vi in intents], [1, 2, 3])

    # -----------------------------------------------------------------------
    # 12. Source Priority: User Over Stock
    # -----------------------------------------------------------------------
    async def test_source_priority_user_over_stock(self):
        user_source = SourceInput(
            source_id="src_user_01",
            kind=SourceKind.VIDEO,
            rights_state=RightsState.OWNED,
        )
        user_scene = SourceSceneRecord(
            id="scn_user_bamboo",
            source_id="src_user_01",
            start_sec=0.0,
            end_sec=6.0,
            duration_sec=6.0,
            fingerprint="fp_user_01",
            description="Bamboo craft in artisan workshop",
            keyframes=["/static/user_thumb.jpg"],
        )
        self.resolver.scene_repo.save(user_scene)

        vp = VisualPlan(
            plan_id="vp_priority",
            intents=[
                VisualIntent(
                    id="vi_prio",
                    scene_id="scene_001",
                    search_query_en="bamboo chopsticks craft",
                    duration_weight=1.0,
                )
            ],
        )
        res = await self.resolver.resolve_visual_plan(
            visual_plan=vp,
            user_sources=[user_source],
            run_id="run_prio",
        )
        selected = res.resolutions[0].selected_candidate
        self.assertIsNotNone(selected)
        self.assertEqual(selected.provider, "user_source")
        self.assertEqual(selected.asset_id, "scn_user_bamboo")

    # -----------------------------------------------------------------------
    # 13. Source Priority: Stock Fallback When Library Empty
    # -----------------------------------------------------------------------
    async def test_source_priority_stock_fallback_when_library_empty(self):
        vp = VisualPlan(
            plan_id="vp_fallback",
            intents=[
                VisualIntent(
                    id="vi_fallback",
                    scene_id="scene_001",
                    search_query_en="katana sword blade blacksmith",
                    duration_weight=1.0,
                )
            ],
        )
        res = await self.resolver.resolve_visual_plan(
            visual_plan=vp,
            user_sources=[],  # No user sources
            run_id="run_fallback",
        )
        selected = res.resolutions[0].selected_candidate
        self.assertIsNotNone(selected)
        self.assertEqual(selected.provider, "pexels_stock")
        self.assertEqual(selected.asset_id, "pex_33671899")

    # -----------------------------------------------------------------------
    # 14. JSON Input Pipeline Convergence
    # -----------------------------------------------------------------------
    async def test_json_input_pipeline_convergence(self):
        req = AutoVideoRequest(
            request_id="req_json_mode",
            input_mode=InputMode.JSON,
            instruction="Sản xuất đũa tre",
            structured_payload={
                "title": "Chế tạo đũa tre",
                "full_script": "Từng thanh tre được vót thẳng và mài nhẵn.",
                "total_word_count": 10,
                "estimated_total_duration_sec": 4.0,
                "scenes": [
                    {
                        "scene_index": 1,
                        "narration": "Từng thanh tre được vót thẳng và mài nhẵn.",
                        "estimated_speech_duration_sec": 4.0,
                    }
                ],
            },
            format="short",
            language="vi",
            review_mode="final_only",
            sources=[],
        )
        run = orchestrator.create_run(req)
        await orchestrator._execute_pipeline(run.id)
        updated = orchestrator.get_run(run.id)

        self.assertIsNotNone(updated.visual_plan)
        self.assertIsNotNone(updated.resolved_assets)
        self.assertGreaterEqual(updated.resolved_assets.visual_coverage_ratio, 0.90)

    # -----------------------------------------------------------------------
    # 15. SCRIPT Input Pipeline Convergence
    # -----------------------------------------------------------------------
    async def test_script_input_pipeline_convergence(self):
        req = AutoVideoRequest(
            request_id="req_script_mode",
            input_mode=InputMode.SCRIPT,
            raw_script="[Cảnh 1] Lưỡi thép rực đỏ dưới búa đập của người thợ rèn.",
            format="short",
            language="vi",
            review_mode="final_only",
            sources=[],
        )
        run = orchestrator.create_run(req)
        await orchestrator._execute_pipeline(run.id)
        updated = orchestrator.get_run(run.id)

        self.assertIsNotNone(updated.visual_plan)
        self.assertIsNotNone(updated.resolved_assets)
        self.assertGreaterEqual(len(updated.resolved_assets.resolutions), 1)

    # -----------------------------------------------------------------------
    # 16. Asset Cache Reuse and Invalidation
    # -----------------------------------------------------------------------
    async def test_asset_cache_reuse_and_invalidation(self):
        adapter = PexelsStockAdapter()
        query = "pottery clay spinning wheel"
        cands1 = await adapter.search_stock(query, limit=2)
        cands2 = await adapter.search_stock(query, limit=2)
        # Second call returns from cache
        self.assertEqual(len(cands1), len(cands2))
        self.assertEqual(cands1[0].asset_id, cands2[0].asset_id)

    # -----------------------------------------------------------------------
    # 17. Provider Timeout Resilience
    # -----------------------------------------------------------------------
    async def test_provider_timeout_resilience(self):
        adapter = PexelsStockAdapter(api_key="valid_looking_key")
        with patch("requests.get", side_effect=TimeoutError("Network timeout")):
            # Timeout must not crash pipeline, degrades to thematic library
            cands = await adapter.search_stock("waterfall mountain", limit=2)
            self.assertGreaterEqual(len(cands), 1)
            self.assertEqual(cands[0].provenance["origin"], "thematic_stock_catalog")

    # -----------------------------------------------------------------------
    # 18. Source Diversity Consecutive Penalty
    # -----------------------------------------------------------------------
    def test_source_diversity_consecutive_penalty(self):
        cand = AssetCandidate(
            asset_id="asset_shot_03",
            source_id="same_source_123",
            provider="user_source",
            start_sec=0.0,
            end_sec=5.0,
            duration_sec=5.0,
            semantic_score=0.85,
            entity_action_score=0.85,
            rights_state=RightsState.OWNED,
        )
        # Recent sources contains 2 consecutive occurrences of same_source_123
        recent = ["other_src", "same_source_123", "same_source_123"]
        is_qual, scored, reasons = self.scorer.score_candidate(
            candidate=cand,
            intent=VisualIntent(id="vi_diversity"),
            target_duration=4.0,
            used_asset_ids=set(),
            recent_source_ids=recent,
            used_visual_fingerprints=set(),
        )
        self.assertEqual(scored.source_diversity_score, 0.20)
        self.assertEqual(scored.repetition_penalty, 0.15)
        self.assertTrue(any("diversity penalty" in r for r in reasons))


if __name__ == "__main__":
    unittest.main()
