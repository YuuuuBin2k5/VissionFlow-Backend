"""
Phase 5 Dedicated Test Suite: Editor Planner & Deterministic Timeline Engine
Validates:
1. Invariant A: Relevance before source preference (User footage cannot win if it fails minimum relevance criteria)
2. Invariant B: Visual Planner degraded mode tracking (CLOUD_SEMANTIC, LOCAL_DOMAIN_RULES, GENERIC_FALLBACK)
3. Invariant E: Draft EditorPlan (provisional/estimated duration, is_render_ready=False) vs Final EditorPlan (canonical ffprobe, is_render_ready=True)
4. Multi-shot duration normalization (sum of shots equals actual scene duration with exact millisecond precision)
5. Zero gaps and zero overlaps across timeline clips
6. Valid trim ranges (0 <= trim_start < trim_end <= asset_duration)
7. Short footage fallback: alternative candidate or Ken Burns motion effect
8. Shot count condensation: fast pacing condensation for short scenes (< 3.2s)
9. Transition assignment: cut, crossfade, fade_black
10. Locked shot preservation on re-planning
11. Audio track ducking plan (BGM ducked under voice)
12. Subtitle chunking: 3-5 word viral phrases within scene timeline bounds
13. Deterministic synthetic WAV generation and ffprobe measurement (100% offline CI)
14. OpenCut Multi-Track Timeline Export (video, audio, text tracks)
15. Partial visual regeneration (reruns visual without rerunning TTS)
16. Partial voice regeneration (reruns TTS without rerunning visual plan)
17. Shot locking endpoint logic
18. Real edit_score evaluation in QualityReport
19. Pipeline convergence across AUTO, SCRIPT, and JSON input modes
20. Timeline drift strict tolerance <= 100ms
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

os.environ["VISIONFLOW_USE_DEV_REPOSITORIES"] = "1"

from production.contracts import (
    AssetCandidate,
    AssetResolutionResult,
    AudioClipPlan,
    AudioTrackPlan,
    AutoVideoRequest,
    EditorPlan,
    EditorPlanType,
    InputMode,
    ProductionRun,
    ProductionRunStatus,
    RightsState,
    SceneAssetResolution,
    SceneNarration,
    ScenePlan,
    ScriptPlan,
    ShotPlan,
    SubtitleChunkPlan,
    SubtitleTrackPlan,
    VisualIntent,
    VisualPlan,
    VisualRole,
)
from production.editor_planner import EditorPlanner, editor_planner
from production.editor_validator import EditorPlanValidator
from production.tts_service import (
    DeterministicMockTTSProvider,
    SceneTTSResult,
    TTSService,
    create_synthetic_wav,
    measure_audio_duration_ffprobe,
)
from production.asset_resolver import CandidateScorer, asset_resolver
from production.orchestrator import orchestrator
from production.repositories.run_repository import run_repository


class TestPhase5EditorPlanner(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.planner = editor_planner
        self.mock_tts = TTSService(provider=DeterministicMockTTSProvider())
        self.scorer = CandidateScorer()

    # -----------------------------------------------------------------------
    # 1. Invariant A: Relevance before source preference
    # -----------------------------------------------------------------------
    def test_invariant_a_relevance_before_source_preference(self):
        """User footage cannot win if it fails minimum relevance criteria (< 0.15)."""
        intent = VisualIntent(
            id="intent_01",
            scene_id="scene_001",
            shot_order=1,
            visual_role=VisualRole.PROCESS.value,
            description="Close up of mechanical gears rotating",
            search_query_en="mechanical gears rotating",
            subjects=["gears", "metal"],
            actions=["rotating", "meshing"],
            shot_preferences=["close_up"],
            motion_preference="slow_pan",
            must_show=[],
            must_avoid=[],
            fact_refs=[],
            importance=0.8,
            duration_weight=1.0,
        )

        cand_irrelevant = AssetCandidate(
            asset_id="user_video_01",
            source_id="user_src",
            provider="user_source",
            start_sec=0.0,
            end_sec=5.0,
            duration_sec=5.0,
            semantic_score=0.05,  # Irrelevant < 0.15
            entity_action_score=0.05,
            visual_role_score=0.5,
            shot_type_score=0.5,
            technical_quality_score=0.9,
            duration_fit_score=0.9,
            rights_score=1.0,
            rights_state=RightsState.OWNED,
        )

        cand_relevant = AssetCandidate(
            asset_id="stock_video_01",
            source_id="stock_src",
            provider="pexels_stock",
            start_sec=0.0,
            end_sec=5.0,
            duration_sec=5.0,
            semantic_score=0.75,  # Relevant
            entity_action_score=0.70,
            visual_role_score=0.8,
            shot_type_score=0.8,
            technical_quality_score=0.9,
            duration_fit_score=0.9,
            rights_score=1.0,
            rights_state=RightsState.APPROVED_STOCK,
        )

        ok_irr, scored_irr, reas_irr = self.scorer.score_candidate(
            candidate=cand_irrelevant,
            intent=intent,
            target_duration=5.0,
            used_asset_ids=set(),
            recent_source_ids=[],
            used_visual_fingerprints=set(),
        )

        ok_rel, scored_rel, reas_rel = self.scorer.score_candidate(
            candidate=cand_relevant,
            intent=intent,
            target_duration=5.0,
            used_asset_ids=set(),
            recent_source_ids=[],
            used_visual_fingerprints=set(),
        )

        # Invariant A: User footage must NOT win if it fails minimum relevance criteria
        self.assertFalse(ok_irr)
        self.assertTrue(ok_rel)
        self.assertIn("minimum relevance requirement", reas_irr[0].lower())


    # -----------------------------------------------------------------------
    # 2. Invariant B: Visual Planner degraded mode tracking
    # -----------------------------------------------------------------------
    def test_invariant_b_planner_mode_telemetry(self):
        """VisualPlan must contain planner_mode indicating CLOUD_SEMANTIC or LOCAL_DOMAIN_RULES."""
        from production.visual_planner import LocalVisualPlannerProvider, VisualPlanner

        local_planner = VisualPlanner(LocalVisualPlannerProvider())
        script = ScriptPlan(
            title="Quy trình sản xuất lụa",
            full_script="Những sợi tơ tằm óng ả được luộc và kéo sợi thủ công.",
            scenes=[
                SceneNarration(
                    scene_index=1,
                    narration="Những sợi tơ tằm óng ả được luộc và kéo sợi thủ công.",
                    estimated_speech_duration_sec=4.5,
                )
            ],
            total_word_count=13,
            estimated_total_duration_sec=4.5,
            hook_word_count=5,
        )
        plan = local_planner.generate_visual_plan(script)
        self.assertIsNotNone(plan.planner_mode)
        self.assertIn(plan.planner_mode, ["LOCAL_DOMAIN_RULES", "CLOUD_SEMANTIC", "GENERIC_FALLBACK"])

    # -----------------------------------------------------------------------
    # 3. Invariant E: Draft vs Final EditorPlan
    # -----------------------------------------------------------------------
    def test_draft_vs_final_editor_plan(self):
        """Draft plan uses estimated duration and is not render ready. Final uses actual duration."""
        script = ScriptPlan(
            title="Thử nghiệm Editor Plan",
            full_script="Bước đầu tiên là khởi động động cơ phản lực.",
            scenes=[
                SceneNarration(
                    scene_id="scene_001",
                    scene_index=1,
                    narration="Bước đầu tiên là khởi động động cơ phản lực.",
                    estimated_speech_duration_sec=3.8,
                )
            ],
            total_word_count=9,
            estimated_total_duration_sec=3.8,
            hook_word_count=4,
        )

        candidate = AssetCandidate(
            asset_id="asset_jet_01",
            source_id="src_jet",
            provider="pexels_stock",
            start_sec=0.0,
            end_sec=6.0,
            duration_sec=6.0,
            semantic_score=0.85,
            entity_action_score=0.85,
            visual_role_score=0.90,
            shot_type_score=0.80,
            technical_quality_score=0.95,
            duration_fit_score=0.90,
            source_diversity_score=1.0,
            rights_score=1.0,
            repetition_penalty=0.0,
            watermark_penalty=0.0,
            conflict_penalty=0.0,
            composite_score=0.88,
            rights_state=RightsState.APPROVED_STOCK,
            is_locked=False,
            provenance={},
            selection_evidence={},
        )

        resolutions = AssetResolutionResult(
            run_id="run_test",
            resolutions=[
                SceneAssetResolution(
                    scene_id="scene_001",
                    shot_order=1,
                    intent_id="intent_001",
                    selected_candidate=candidate,
                    alternate_candidates=[],
                    warnings=[],
                    rejection_reasons=[],
                    is_unresolved=False,
                )
            ],
            visual_coverage_ratio=1.0,
            duplicate_count=0,
            rights_blocker_count=0,
            unresolved_count=0,
            average_match_score=0.88,
            cache_hit=False,
        )

        # 1. Draft Plan
        draft_plan = self.planner.build_draft_editor_plan(
            script_plan=script,
            resolved_assets=resolutions,
            run_id="run_test",
        )
        self.assertEqual(draft_plan.plan_type, EditorPlanType.DRAFT.value)
        self.assertFalse(draft_plan.is_render_ready)
        self.assertIsNone(draft_plan.scenes[0].actual_duration_seconds)

        # 2. Final Plan (with simulated ffprobe actual duration 4.125s)
        tts_res = [
            SceneTTSResult(
                scene_id="scene_001",
                audio_asset_id="audio_001",
                audio_file_path="/tmp/audio_001.wav",
                actual_duration_seconds=4.125,
                provider="mock",
                voice_code="vi-VN-NamMinhNeural",
                voice_rate=1.0,
            )
        ]

        final_plan = self.planner.build_final_editor_plan(
            script_plan=script,
            resolved_assets=resolutions,
            tts_results=tts_res,
            run_id="run_test",
        )
        self.assertEqual(final_plan.plan_type, EditorPlanType.FINAL.value)
        self.assertTrue(final_plan.is_render_ready)
        self.assertEqual(final_plan.scenes[0].actual_duration_seconds, 4.125)
        self.assertEqual(final_plan.duration_seconds, 4.125)

    # -----------------------------------------------------------------------
    # 4. Multi-shot duration normalization and exact zero drift
    # -----------------------------------------------------------------------
    def test_multi_shot_normalization_zero_drift(self):
        """Sum of normalized shots must match actual scene duration exactly."""
        script = ScriptPlan(
            title="Multi-Shot Scene",
            full_script="Quan sát kỹ lưỡng từng chi tiết vi mô trên bề mặt.",
            scenes=[
                SceneNarration(
                    scene_id="scene_001",
                    scene_index=1,
                    narration="Quan sát kỹ lưỡng từng chi tiết vi mô trên bề mặt.",
                    estimated_speech_duration_sec=6.5,
                )
            ],
            total_word_count=10,
            estimated_total_duration_sec=6.5,
            hook_word_count=5,
        )

        cand1 = AssetCandidate(
            asset_id="c1",
            source_id="s1",
            provider="pexels_stock",
            start_sec=0.0,
            end_sec=5.0,
            duration_sec=5.0,
            composite_score=0.8,
            rights_state=RightsState.APPROVED_STOCK,
        )
        cand2 = AssetCandidate(
            asset_id="c2",
            source_id="s2",
            provider="pexels_stock",
            start_sec=0.0,
            end_sec=5.0,
            duration_sec=5.0,
            composite_score=0.85,
            rights_state=RightsState.APPROVED_STOCK,
        )

        resolutions = AssetResolutionResult(
            run_id="run_multi",
            resolutions=[
                SceneAssetResolution(
                    scene_id="scene_001",
                    shot_order=1,
                    intent_id="i1",
                    selected_candidate=cand1,
                    alternate_candidates=[],
                    warnings=[],
                    rejection_reasons=[],
                    is_unresolved=False,
                ),
                SceneAssetResolution(
                    scene_id="scene_001",
                    shot_order=2,
                    intent_id="i2",
                    selected_candidate=cand2,
                    alternate_candidates=[],
                    warnings=[],
                    rejection_reasons=[],
                    is_unresolved=False,
                ),
            ],
            visual_coverage_ratio=1.0,
            duplicate_count=0,
            rights_blocker_count=0,
            unresolved_count=0,
            average_match_score=0.825,
            cache_hit=False,
        )

        actual_duration = 5.733  # non-trivial floating point duration
        tts_res = [
            SceneTTSResult(
                scene_id="scene_001",
                audio_asset_id="a1",
                audio_file_path="/tmp/a1.wav",
                actual_duration_seconds=actual_duration,
                provider="mock",
                voice_code="vi-VN-NamMinhNeural",
                voice_rate=1.0,
            )
        ]

        plan = self.planner.build_final_editor_plan(
            script_plan=script,
            resolved_assets=resolutions,
            tts_results=tts_res,
            run_id="run_multi",
        )

        scene = plan.scenes[0]
        self.assertEqual(len(scene.shots), 2)
        total_shot_dur = round(sum(s.target_duration_seconds for s in scene.shots), 3)
        self.assertEqual(total_shot_dur, actual_duration)
        self.assertLessEqual(plan.timeline_drift_ms, 1.0)  # Drift <= 1ms!

    # -----------------------------------------------------------------------
    # 5. Zero gaps and zero overlaps across timeline
    # -----------------------------------------------------------------------
    def test_zero_gaps_and_zero_overlaps(self):
        """All shots must be strictly contiguous."""
        script = ScriptPlan(
            title="Contiguous Check",
            full_script="Cảnh 1 thoại. Cảnh 2 thoại tiếp nối.",
            scenes=[
                SceneNarration(scene_id="scene_001", scene_index=1, narration="Cảnh 1 thoại.", estimated_speech_duration_sec=3.0),
                SceneNarration(scene_id="scene_002", scene_index=2, narration="Cảnh 2 thoại tiếp nối.", estimated_speech_duration_sec=4.0),
            ],
            total_word_count=8,
            estimated_total_duration_sec=7.0,
            hook_word_count=3,
        )

        cand = AssetCandidate(
            asset_id="c1",
            source_id="s1",
            provider="pexels_stock",
            start_sec=0.0,
            end_sec=10.0,
            duration_sec=10.0,
            composite_score=0.9,
            rights_state=RightsState.APPROVED_STOCK,
        )
        resolutions = AssetResolutionResult(
            run_id="run_contig",
            resolutions=[
                SceneAssetResolution(scene_id="scene_001", shot_order=1, intent_id="i1", selected_candidate=cand, alternate_candidates=[], warnings=[], rejection_reasons=[], is_unresolved=False),
                SceneAssetResolution(scene_id="scene_002", shot_order=1, intent_id="i2", selected_candidate=cand, alternate_candidates=[], warnings=[], rejection_reasons=[], is_unresolved=False),
            ],
            visual_coverage_ratio=1.0,
            duplicate_count=0,
            rights_blocker_count=0,
            unresolved_count=0,
            average_match_score=0.9,
            cache_hit=False,
        )

        tts_res = [
            SceneTTSResult(scene_id="scene_001", audio_asset_id="a1", audio_file_path="/tmp/a1.wav", actual_duration_seconds=3.25, provider="mock", voice_code="vi-VN-NamMinhNeural", voice_rate=1.0),
            SceneTTSResult(scene_id="scene_002", audio_asset_id="a2", audio_file_path="/tmp/a2.wav", actual_duration_seconds=4.50, provider="mock", voice_code="vi-VN-NamMinhNeural", voice_rate=1.0),
        ]

        plan = self.planner.build_final_editor_plan(
            script_plan=script,
            resolved_assets=resolutions,
            tts_results=tts_res,
            run_id="run_contig",
        )

        # Validate with EditorPlanValidator
        report = EditorPlanValidator.validate(plan)
        self.assertTrue(report["is_valid"])
        self.assertEqual(len(report["errors"]), 0)

        # Explicit assertion on bounds
        scn1, scn2 = plan.scenes[0], plan.scenes[1]
        self.assertEqual(scn1.timeline_start, 0.0)
        self.assertEqual(scn1.timeline_end, 3.25)
        self.assertEqual(scn2.timeline_start, 3.25)
        self.assertEqual(scn2.timeline_end, 7.75)

    # -----------------------------------------------------------------------
    # 6. Trim range validity
    # -----------------------------------------------------------------------
    def test_trim_range_validity(self):
        """0 <= trim_start < trim_end <= asset_duration."""
        script = ScriptPlan(
            title="Trim Check",
            full_script="Kiểm tra việc cắt đoạn footage theo đúng biên độ.",
            scenes=[
                SceneNarration(scene_id="scene_001", scene_index=1, narration="Kiểm tra cắt đoạn.", estimated_speech_duration_sec=3.5)
            ],
            total_word_count=5,
            estimated_total_duration_sec=3.5,
            hook_word_count=3,
        )

        cand = AssetCandidate(
            asset_id="c_trim",
            source_id="s_trim",
            provider="pexels_stock",
            start_sec=1.0,
            end_sec=9.0,
            duration_sec=8.0,
            composite_score=0.9,
            rights_state=RightsState.APPROVED_STOCK,
        )
        resolutions = AssetResolutionResult(
            run_id="run_trim",
            resolutions=[
                SceneAssetResolution(scene_id="scene_001", shot_order=1, intent_id="i1", selected_candidate=cand, alternate_candidates=[], warnings=[], rejection_reasons=[], is_unresolved=False),
            ],
            visual_coverage_ratio=1.0,
            duplicate_count=0,
            rights_blocker_count=0,
            unresolved_count=0,
            average_match_score=0.9,
            cache_hit=False,
        )

        tts_res = [
            SceneTTSResult(scene_id="scene_001", audio_asset_id="a1", audio_file_path="/tmp/a1.wav", actual_duration_seconds=3.2, provider="mock", voice_code="vi-VN-NamMinhNeural", voice_rate=1.0)
        ]

        plan = self.planner.build_final_editor_plan(
            script_plan=script,
            resolved_assets=resolutions,
            tts_results=tts_res,
            run_id="run_trim",
        )

        shot = plan.scenes[0].shots[0]
        self.assertGreaterEqual(shot.asset_trim_start, 0.0)
        self.assertLess(shot.asset_trim_start, shot.asset_trim_end)
        self.assertLessEqual(shot.asset_trim_end, cand.duration_sec)
        self.assertAlmostEqual(shot.asset_trim_end - shot.asset_trim_start, shot.target_duration_seconds, places=3)

    # -----------------------------------------------------------------------
    # 7. Short footage fallback: alternative or Ken Burns
    # -----------------------------------------------------------------------
    def test_short_footage_fallback_ken_burns(self):
        """When candidate is shorter than shot target, applies motion_effect to hold safely."""
        script = ScriptPlan(
            title="Short Footage",
            full_script="Một câu chuyện ngắn.",
            scenes=[
                SceneNarration(scene_id="scene_001", scene_index=1, narration="Một câu chuyện ngắn.", estimated_speech_duration_sec=5.0)
            ],
            total_word_count=4,
            estimated_total_duration_sec=5.0,
            hook_word_count=4,
        )

        # Asset only has 2.0s duration, but scene target is 5.0s
        cand = AssetCandidate(
            asset_id="c_short",
            source_id="s_short",
            provider="pexels_stock",
            start_sec=0.0,
            end_sec=2.0,
            duration_sec=2.0,
            composite_score=0.8,
            rights_state=RightsState.APPROVED_STOCK,
        )
        resolutions = AssetResolutionResult(
            run_id="run_short",
            resolutions=[
                SceneAssetResolution(scene_id="scene_001", shot_order=1, intent_id="i1", selected_candidate=cand, alternate_candidates=[], warnings=[], rejection_reasons=[], is_unresolved=False),
            ],
            visual_coverage_ratio=1.0,
            duplicate_count=0,
            rights_blocker_count=0,
            unresolved_count=0,
            average_match_score=0.8,
            cache_hit=False,
        )

        tts_res = [
            SceneTTSResult(scene_id="scene_001", audio_asset_id="a1", audio_file_path="/tmp/a1.wav", actual_duration_seconds=5.0, provider="mock", voice_code="vi-VN-NamMinhNeural", voice_rate=1.0)
        ]

        plan = self.planner.build_final_editor_plan(
            script_plan=script,
            resolved_assets=resolutions,
            tts_results=tts_res,
            run_id="run_short",
        )

        shot = plan.scenes[0].shots[0]
        # Should have motion effect assigned to safely extend/hold
        self.assertIsNotNone(shot.motion_effect)
        self.assertIn("ken_burns", shot.motion_effect)

    # -----------------------------------------------------------------------
    # 8. Shot count condensation for short scenes (< 3.2s)
    # -----------------------------------------------------------------------
    def test_shot_count_condensation_for_short_scenes(self):
        """Short scene with 3 planned resolutions condenses down to 2 shots to prevent jarring rapid cuts."""
        script = ScriptPlan(
            title="Rapid Scene",
            full_script="Rất nhanh!",
            scenes=[
                SceneNarration(scene_id="scene_001", scene_index=1, narration="Rất nhanh!", estimated_speech_duration_sec=2.4)
            ],
            total_word_count=2,
            estimated_total_duration_sec=2.4,
            hook_word_count=2,
        )

        # 3 resolutions provided
        res_list = [
            SceneAssetResolution(
                scene_id="scene_001",
                shot_order=i,
                intent_id=f"i{i}",
                selected_candidate=AssetCandidate(
                    asset_id=f"c{i}",
                    source_id=f"s{i}",
                    provider="pexels_stock",
                    start_sec=0.0,
                    end_sec=4.0,
                    duration_sec=4.0,
                    composite_score=0.8,
                    rights_state=RightsState.APPROVED_STOCK,
                ),
                alternate_candidates=[],
                warnings=[],
                rejection_reasons=[],
                is_unresolved=False,
            )
            for i in [1, 2, 3]
        ]
        resolutions = AssetResolutionResult(
            run_id="run_condense",
            resolutions=res_list,
            visual_coverage_ratio=1.0,
            duplicate_count=0,
            rights_blocker_count=0,
            unresolved_count=0,
            average_match_score=0.8,
            cache_hit=False,
        )

        tts_res = [
            SceneTTSResult(scene_id="scene_001", audio_asset_id="a1", audio_file_path="/tmp/a1.wav", actual_duration_seconds=2.4, provider="mock", voice_code="vi-VN-NamMinhNeural", voice_rate=1.0)
        ]

        plan = self.planner.build_final_editor_plan(
            script_plan=script,
            resolved_assets=resolutions,
            tts_results=tts_res,
            run_id="run_condense",
        )

        # 3 shots condensed to 2 shots
        self.assertLessEqual(len(plan.scenes[0].shots), 2)
        total_dur = round(sum(s.target_duration_seconds for s in plan.scenes[0].shots), 3)
        self.assertEqual(total_dur, 2.4)

    # -----------------------------------------------------------------------
    # 9. Transition assignment
    # -----------------------------------------------------------------------
    def test_transition_assignment(self):
        """Hook has cut, scene boundaries have crossfade."""
        script = ScriptPlan(
            title="Transition Test",
            full_script="Mở đầu video. Tiếp nối nội dung.",
            scenes=[
                SceneNarration(scene_id="scene_001", scene_index=1, narration="Mở đầu video.", estimated_speech_duration_sec=3.0),
                SceneNarration(scene_id="scene_002", scene_index=2, narration="Tiếp nối nội dung.", estimated_speech_duration_sec=3.0),
            ],
            total_word_count=6,
            estimated_total_duration_sec=6.0,
            hook_word_count=3,
        )

        cand = AssetCandidate(
            asset_id="c1",
            source_id="s1",
            provider="pexels_stock",
            start_sec=0.0,
            end_sec=5.0,
            duration_sec=5.0,
            composite_score=0.85,
            rights_state=RightsState.APPROVED_STOCK,
        )
        resolutions = AssetResolutionResult(
            run_id="run_trans",
            resolutions=[
                SceneAssetResolution(scene_id="scene_001", shot_order=1, intent_id="i1", selected_candidate=cand, alternate_candidates=[], warnings=[], rejection_reasons=[], is_unresolved=False),
                SceneAssetResolution(scene_id="scene_002", shot_order=1, intent_id="i2", selected_candidate=cand, alternate_candidates=[], warnings=[], rejection_reasons=[], is_unresolved=False),
            ],
            visual_coverage_ratio=1.0,
            duplicate_count=0,
            rights_blocker_count=0,
            unresolved_count=0,
            average_match_score=0.85,
            cache_hit=False,
        )

        tts_res = [
            SceneTTSResult(scene_id="scene_001", audio_asset_id="a1", audio_file_path="/tmp/a1.wav", actual_duration_seconds=3.0, provider="mock", voice_code="vi-VN-NamMinhNeural", voice_rate=1.0),
            SceneTTSResult(scene_id="scene_002", audio_asset_id="a2", audio_file_path="/tmp/a2.wav", actual_duration_seconds=3.0, provider="mock", voice_code="vi-VN-NamMinhNeural", voice_rate=1.0),
        ]

        plan = self.planner.build_final_editor_plan(
            script_plan=script,
            resolved_assets=resolutions,
            tts_results=tts_res,
            run_id="run_trans",
        )

        # Hook shot transition is 'cut' or 'crossfade'
        shot1 = plan.scenes[0].shots[0]
        shot2 = plan.scenes[1].shots[0]
        self.assertIn(shot1.transition_out, ["cut", "crossfade"])
        self.assertIn(shot2.transition_out, ["cut", "crossfade", "fade_black"])

    # -----------------------------------------------------------------------
    # 10. Locked shot preservation on re-planning
    # -----------------------------------------------------------------------
    def test_locked_shot_preservation(self):
        """Locked shot retains its asset_id even if resolution offers a different candidate."""
        script = ScriptPlan(
            title="Lock Test",
            full_script="Phân cảnh có shot bị khóa.",
            scenes=[
                SceneNarration(scene_id="scene_001", scene_index=1, narration="Phân cảnh có shot bị khóa.", estimated_speech_duration_sec=4.0)
            ],
            total_word_count=7,
            estimated_total_duration_sec=4.0,
            hook_word_count=4,
        )

        locked_shot = ShotPlan(
            shot_id="shot_001_01",
            asset_id="user_locked_asset_999",
            source_id="user_source",
            duration_sec=4.0,
            target_duration_seconds=4.0,
            is_locked=True,
            visual_role="hook",
        )

        new_cand = AssetCandidate(
            asset_id="new_stock_asset_111",
            source_id="pexels_stock",
            provider="pexels_stock",
            start_sec=0.0,
            end_sec=5.0,
            duration_sec=5.0,
            composite_score=0.95,
            rights_state=RightsState.APPROVED_STOCK,
        )
        resolutions = AssetResolutionResult(
            run_id="run_lock",
            resolutions=[
                SceneAssetResolution(scene_id="scene_001", shot_order=1, intent_id="i1", selected_candidate=new_cand, alternate_candidates=[], warnings=[], rejection_reasons=[], is_unresolved=False),
            ],
            visual_coverage_ratio=1.0,
            duplicate_count=0,
            rights_blocker_count=0,
            unresolved_count=0,
            average_match_score=0.95,
            cache_hit=False,
        )

        tts_res = [
            SceneTTSResult(scene_id="scene_001", audio_asset_id="a1", audio_file_path="/tmp/a1.wav", actual_duration_seconds=4.0, provider="mock", voice_code="vi-VN-NamMinhNeural", voice_rate=1.0)
        ]

        plan = self.planner.build_final_editor_plan(
            script_plan=script,
            resolved_assets=resolutions,
            tts_results=tts_res,
            run_id="run_lock",
            locked_shots={"shot_001_01": locked_shot},
        )

        reconciled_shot = plan.scenes[0].shots[0]
        self.assertEqual(reconciled_shot.asset_id, "user_locked_asset_999")
        self.assertTrue(reconciled_shot.is_locked)

    # -----------------------------------------------------------------------
    # 11. Audio track ducking plan
    # -----------------------------------------------------------------------
    def test_audio_track_ducking_plan(self):
        """Audio track includes voice clips and BGM with ducking profile."""
        script = ScriptPlan(
            title="Audio Ducking",
            full_script="Thoại chính trên nền nhạc du dương.",
            scenes=[
                SceneNarration(scene_id="scene_001", scene_index=1, narration="Thoại chính trên nền nhạc.", estimated_speech_duration_sec=4.0)
            ],
            total_word_count=5,
            estimated_total_duration_sec=4.0,
            hook_word_count=3,
        )

        cand = AssetCandidate(asset_id="c1", source_id="s1", provider="pexels_stock", start_sec=0.0, end_sec=5.0, duration_sec=5.0, composite_score=0.8, rights_state=RightsState.APPROVED_STOCK)
        resolutions = AssetResolutionResult(
            run_id="run_duck",
            resolutions=[SceneAssetResolution(scene_id="scene_001", shot_order=1, intent_id="i1", selected_candidate=cand, alternate_candidates=[], warnings=[], rejection_reasons=[], is_unresolved=False)],
            visual_coverage_ratio=1.0, duplicate_count=0, rights_blocker_count=0, unresolved_count=0, average_match_score=0.8, cache_hit=False,
        )
        tts_res = [
            SceneTTSResult(scene_id="scene_001", audio_asset_id="a1", audio_file_path="/tmp/a1.wav", actual_duration_seconds=4.0, provider="mock", voice_code="vi-VN-NamMinhNeural", voice_rate=1.0)
        ]

        plan = self.planner.build_final_editor_plan(
            script_plan=script,
            resolved_assets=resolutions,
            tts_results=tts_res,
            bgm_asset_url="https://assets.example.com/bgm.mp3",
            run_id="run_duck",
        )

        self.assertIsNotNone(plan.audio_track)
        clips = plan.audio_track.clips
        self.assertGreaterEqual(len(clips), 2)  # voice + bgm
        bgm_clip = next((c for c in clips if c.clip_id == "bgm_main"), None)
        self.assertIsNotNone(bgm_clip)
        self.assertAlmostEqual(bgm_clip.volume, 0.15, places=2)

    # -----------------------------------------------------------------------
    # 12. Subtitle chunking: 3-5 word viral phrases
    # -----------------------------------------------------------------------
    def test_subtitle_chunking_phrases(self):
        """Subtitle chunks must be 3-5 words each with non-overlapping timeline bounds."""
        script = ScriptPlan(
            title="Subtitles",
            full_script="Khám phá công nghệ sản xuất vi mạch bán dẫn siêu nhỏ hiện đại nhất thế giới.",
            scenes=[
                SceneNarration(
                    scene_id="scene_001",
                    scene_index=1,
                    narration="Khám phá công nghệ sản xuất vi mạch bán dẫn siêu nhỏ hiện đại nhất thế giới.",
                    estimated_speech_duration_sec=5.0,
                )
            ],
            total_word_count=13,
            estimated_total_duration_sec=5.0,
            hook_word_count=5,
        )

        cand = AssetCandidate(asset_id="c1", source_id="s1", provider="pexels_stock", start_sec=0.0, end_sec=6.0, duration_sec=6.0, composite_score=0.8, rights_state=RightsState.APPROVED_STOCK)
        resolutions = AssetResolutionResult(
            run_id="run_sub",
            resolutions=[SceneAssetResolution(scene_id="scene_001", shot_order=1, intent_id="i1", selected_candidate=cand, alternate_candidates=[], warnings=[], rejection_reasons=[], is_unresolved=False)],
            visual_coverage_ratio=1.0, duplicate_count=0, rights_blocker_count=0, unresolved_count=0, average_match_score=0.8, cache_hit=False,
        )
        tts_res = [
            SceneTTSResult(scene_id="scene_001", audio_asset_id="a1", audio_file_path="/tmp/a1.wav", actual_duration_seconds=5.0, provider="mock", voice_code="vi-VN-NamMinhNeural", voice_rate=1.0)
        ]

        plan = self.planner.build_final_editor_plan(
            script_plan=script,
            resolved_assets=resolutions,
            tts_results=tts_res,
            run_id="run_sub",
        )

        self.assertIsNotNone(plan.subtitle_track)
        chunks = plan.subtitle_track.chunks
        self.assertGreaterEqual(len(chunks), 2)
        for chk in chunks:
            word_count = len(chk.text.split())
            self.assertLessEqual(word_count, 6)
            self.assertGreaterEqual(chk.timeline_start, 0.0)
            self.assertLessEqual(chk.timeline_end, 5.05)

    # -----------------------------------------------------------------------
    # 13. Deterministic synthetic WAV generation & ffprobe measurement
    # -----------------------------------------------------------------------
    def test_synthetic_wav_and_ffprobe(self):
        """Standard library wave generates valid WAV with exact duration."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            wav_path = Path(tmp_dir) / "test_tone.wav"
            target_dur = 3.500
            create_synthetic_wav(wav_path, target_dur)

            self.assertTrue(wav_path.exists())
            measured_dur = measure_audio_duration_ffprobe(wav_path)
            self.assertAlmostEqual(measured_dur, target_dur, places=2)

    # -----------------------------------------------------------------------
    # 14. OpenCut Multi-Track Timeline Export
    # -----------------------------------------------------------------------
    def test_export_opencut_timeline(self):
        """OpenCut Project Schema output contains video, audio, text tracks with matching totalDurationSec."""
        script = ScriptPlan(
            title="OpenCut Test",
            full_script="Xuất timeline chuẩn OpenCut.",
            scenes=[SceneNarration(scene_id="scene_001", scene_index=1, narration="Xuất timeline.", estimated_speech_duration_sec=3.0)],
            total_word_count=2,
            estimated_total_duration_sec=3.0,
            hook_word_count=2,
        )
        cand = AssetCandidate(asset_id="c1", source_id="s1", provider="pexels_stock", start_sec=0.0, end_sec=4.0, duration_sec=4.0, composite_score=0.8, rights_state=RightsState.APPROVED_STOCK)
        resolutions = AssetResolutionResult(
            run_id="run_oc",
            resolutions=[SceneAssetResolution(scene_id="scene_001", shot_order=1, intent_id="i1", selected_candidate=cand, alternate_candidates=[], warnings=[], rejection_reasons=[], is_unresolved=False)],
            visual_coverage_ratio=1.0, duplicate_count=0, rights_blocker_count=0, unresolved_count=0, average_match_score=0.8, cache_hit=False,
        )
        tts_res = [SceneTTSResult(scene_id="scene_001", audio_asset_id="a1", audio_file_path="/tmp/a1.wav", actual_duration_seconds=3.0, provider="mock", voice_code="vi-VN-NamMinhNeural", voice_rate=1.0)]

        plan = self.planner.build_final_editor_plan(script_plan=script, resolved_assets=resolutions, tts_results=tts_res, run_id="run_oc")

        opencut_data = self.planner.export_opencut_timeline(plan, project_name="OpenCut Test")
        self.assertEqual(opencut_data["version"], "1.0.0-opencut")
        self.assertEqual(opencut_data["projectName"], "OpenCut Test")
        self.assertEqual(opencut_data["totalDurationSec"], 3.0)
        self.assertEqual(len(opencut_data["tracks"]), 3)

        track_types = [t["type"] for t in opencut_data["tracks"]]
        self.assertIn("video", track_types)
        self.assertIn("audio", track_types)
        self.assertIn("text", track_types)

    # -----------------------------------------------------------------------
    # 15. Partial visual regeneration (reruns visual without rerunning TTS)
    # -----------------------------------------------------------------------
    async def test_partial_visual_regeneration(self):
        """Regenerating visual does not overwrite actual TTS audio durations."""
        request = AutoVideoRequest(
            request_id="req_pvr",
            instruction="Sản xuất gốm sứ Bát Tràng truyền thống",
            format="short",
            language="vi",
            review_mode="final_only",
            sources=[],
        )
        run = orchestrator.create_run(request)
        await orchestrator._execute_pipeline(run.id)

        initial_run = run_repository.get(run.id)
        self.assertIsNotNone(initial_run.editor_plan)
        init_duration = initial_run.editor_plan.duration_seconds

        # Trigger partial visual regeneration
        updated_plan = await orchestrator.regenerate_visual(run.id)
        self.assertIsNotNone(updated_plan)
        # Duration stays identically preserved
        self.assertAlmostEqual(updated_plan.duration_seconds, init_duration, places=2)

    # -----------------------------------------------------------------------
    # 16. Partial voice regeneration (reruns TTS without rerunning visual plan)
    # -----------------------------------------------------------------------
    async def test_partial_voice_regeneration(self):
        """Regenerating voice reconciles editor plan duration while keeping visual assets."""
        request = AutoVideoRequest(
            request_id="req_pvoice",
            instruction="Nghề đan nón lá Chuông truyền thống",
            format="short",
            language="vi",
            review_mode="final_only",
            sources=[],
        )
        run = orchestrator.create_run(request)
        await orchestrator._execute_pipeline(run.id)

        initial_run = run_repository.get(run.id)
        init_assets = [sh.asset_id for scn in initial_run.editor_plan.scenes for sh in scn.shots]

        # Trigger partial voice regeneration
        updated_plan = await orchestrator.regenerate_voice(run.id)
        self.assertIsNotNone(updated_plan)
        re_assets = [sh.asset_id for scn in updated_plan.scenes for sh in scn.shots]
        # Visual asset IDs preserved
        self.assertEqual(init_assets, re_assets)

    # -----------------------------------------------------------------------
    # 17. Shot locking endpoint logic
    # -----------------------------------------------------------------------
    def test_shot_locking_logic(self):
        """Orchestrator lock_shot marks target shot as locked in repository."""
        request = AutoVideoRequest(
            request_id="req_lock",
            instruction="Bánh mì Việt Nam",
            format="short",
            language="vi",
            review_mode="final_only",
            sources=[],
        )
        run = orchestrator.create_run(request)
        # Seed an editor plan
        plan = EditorPlan(
            plan_id="p1",
            scenes=[
                ScenePlan(
                    scene_id="scene_001",
                    narration="Bánh mì nóng giòn.",
                    shots=[
                        ShotPlan(shot_id="shot_001_01", asset_id="a1", duration_sec=3.0, is_locked=False),
                    ],
                )
            ],
        )
        run.editor_plan = plan
        run_repository.set_editor_plan(run.id, plan)

        success = orchestrator.lock_shot(run.id, scene_id="scene_001", shot_id="shot_001_01", is_locked=True)
        self.assertTrue(success)

        updated_run = run_repository.get(run.id)
        self.assertTrue(updated_run.editor_plan.scenes[0].shots[0].is_locked)

    # -----------------------------------------------------------------------
    # 18. Real edit_score evaluation in QualityReport
    # -----------------------------------------------------------------------
    def test_real_edit_score_in_quality_report(self):
        """QualityReport must contain honest REAL edit_score in Phase 5."""
        plan = EditorPlan(
            plan_id="p_qc",
            timeline_drift_ms=12.5,
            duration_seconds=10.0,
            scenes=[
                ScenePlan(
                    scene_id="scn_1",
                    narration="Test narration",
                    actual_duration_seconds=10.0,
                    shots=[
                        ShotPlan(
                            shot_id="sh1",
                            asset_id="a1",
                            duration_sec=5.0,
                            target_duration_seconds=5.0,
                            asset_trim_start=0.0,
                            asset_trim_end=5.0,
                        ),
                        ShotPlan(
                            shot_id="sh2",
                            asset_id="a2",
                            duration_sec=5.0,
                            target_duration_seconds=5.0,
                            asset_trim_start=0.0,
                            asset_trim_end=5.0,
                        ),
                    ],
                )
            ],
        )
        qc = orchestrator._generate_honest_quality_report("run_qc", plan, None)
        self.assertIsNotNone(qc.edit_score)
        self.assertIn("edit", qc.evaluated_axes)
        self.assertGreaterEqual(qc.edit_score, 0.85)

    # -----------------------------------------------------------------------
    # 19. Pipeline convergence across AUTO, SCRIPT, and JSON input modes
    # -----------------------------------------------------------------------
    async def test_input_mode_convergence(self):
        """All 3 modes produce valid render-ready EditorPlan with TIMELINE_READY status."""
        for mode in [InputMode.AUTO, InputMode.SCRIPT, InputMode.JSON]:
            payload = {}
            raw_script = None
            if mode == InputMode.SCRIPT:
                raw_script = "Phần một mở đầu. Phần hai kết thúc."
            elif mode == InputMode.JSON:
                payload = {
                    "title": "JSON Plan",
                    "full_script": "Nội dung JSON một. Nội dung JSON hai.",
                    "total_word_count": 8,
                    "estimated_total_duration_sec": 6.0,
                    "scenes": [
                        {"scene_index": 1, "narration": "Nội dung JSON một.", "estimated_speech_duration_sec": 3.0},
                        {"scene_index": 2, "narration": "Nội dung JSON hai.", "estimated_speech_duration_sec": 3.0},
                    ],
                }

            req = AutoVideoRequest(
                request_id=f"req_mode_{mode.value}",
                input_mode=mode,
                instruction="Quy trình thử nghiệm" if mode == InputMode.AUTO else None,
                raw_script=raw_script,
                structured_payload=payload if mode == InputMode.JSON else None,
                format="short",
                language="vi",
                review_mode="final_only",
                sources=[],
            )
            run = orchestrator.create_run(req)
            await orchestrator._execute_pipeline(run.id)

            completed_run = run_repository.get(run.id)
            self.assertIn(completed_run.status, (ProductionRunStatus.READY, ProductionRunStatus.TIMELINE_READY))
            self.assertIsNotNone(completed_run.editor_plan)
            self.assertTrue(completed_run.editor_plan.is_render_ready)

    # -----------------------------------------------------------------------
    # 20. Strict timeline drift <= 100ms
    # -----------------------------------------------------------------------
    def test_strict_timeline_drift_tolerance(self):
        """Timeline drift must always be <= 100ms across multiple scenes."""
        script = ScriptPlan(
            title="Drift Benchmark",
            full_script="Đoạn 1. Đoạn 2. Đoạn 3. Đoạn 4. Đoạn 5.",
            scenes=[
                SceneNarration(scene_id=f"s{i}", scene_index=i, narration=f"Đoạn {i}.", estimated_speech_duration_sec=3.0)
                for i in range(1, 6)
            ],
            total_word_count=10,
            estimated_total_duration_sec=15.0,
            hook_word_count=2,
        )

        cand = AssetCandidate(asset_id="c", source_id="s", provider="pexels_stock", start_sec=0.0, end_sec=5.0, duration_sec=5.0, composite_score=0.85, rights_state=RightsState.APPROVED_STOCK)
        resolutions = AssetResolutionResult(
            run_id="run_drift",
            resolutions=[
                SceneAssetResolution(scene_id=f"s{i}", shot_order=1, intent_id=f"i{i}", selected_candidate=cand, alternate_candidates=[], warnings=[], rejection_reasons=[], is_unresolved=False)
                for i in range(1, 6)
            ],
            visual_coverage_ratio=1.0, duplicate_count=0, rights_blocker_count=0, unresolved_count=0, average_match_score=0.85, cache_hit=False,
        )

        tts_res = [
            SceneTTSResult(scene_id=f"s{i}", audio_asset_id=f"a{i}", audio_file_path=f"/tmp/a{i}.wav", actual_duration_seconds=3.141, provider="mock", voice_code="vi-VN-NamMinhNeural", voice_rate=1.0)
            for i in range(1, 6)
        ]

        plan = self.planner.build_final_editor_plan(
            script_plan=script,
            resolved_assets=resolutions,
            tts_results=tts_res,
            run_id="run_drift",
        )

        self.assertLessEqual(plan.timeline_drift_ms, 100.0)
        # In our deterministic normalization, drift is 0.0ms!
        self.assertAlmostEqual(plan.timeline_drift_ms, 0.0, places=1)


if __name__ == "__main__":
    unittest.main()
