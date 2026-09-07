"""
Unit and Integration Test Suite for Phase 6 — Final QC, Render Validation & Auto-Fix.
Verifies Technical QC, Semantic QC, Editorial QC, 6-Axis Quality Report,
Blocker Gates, Auto-Fix Loop, and State Transitions.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from production.contracts import (
    AudioClipPlan,
    AudioTrackPlan,
    ClaimItem,
    EditorPlan,
    EditorPlanType,
    FactPack,
    ProductionRun,
    ProductionRunStatus,
    QualityReport,
    QualityStatus,
    RenderArtifact,
    ScenePlan,
    ShortAssetFallbackPolicy,
    ShotPlan,
    SubtitleAlignmentMode,
    SubtitleChunkPlan,
    SubtitleTrackPlan,
    VisualIntent,
    VisualPlan,
)
from production.quality.auto_fix import auto_fix
from production.quality.editorial_qc import editorial_qc
from production.quality.semantic_qc import semantic_qc
from production.quality.technical_qc import technical_qc
from production.quality_orchestrator import quality_orchestrator
from production.render_handoff import render_handoff


class TestPhase6RenderQC(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_dir = Path("d:/VisionFlow/.media_cache/test_fixtures")
        cls.test_dir.mkdir(parents=True, exist_ok=True)

        # Create sample synthetic test video using render_handoff if not present
        cls.sample_plan = EditorPlan(
            plan_id="plan_test_p6_01",
            run_id="run_p6_sample_01",
            script_version="1.0",
            plan_type=EditorPlanType.FINAL.value,
            duration_seconds=3.0,
            aspect_ratio="9:16",
            timeline_drift_ms=0.0,
            scenes=[
                ScenePlan(
                    scene_id="scene_001",
                    scene_index=1,
                    narration="Kiểm thử chất lượng render video.",
                    actual_duration_seconds=3.0,
                    timeline_start=0.0,
                    timeline_end=3.0,
                    shots=[
                        ShotPlan(
                            shot_id="shot_01",
                            shot_index=1,
                            asset_id="ast_sample_1",
                            timeline_start=0.0,
                            timeline_end=3.0,
                            duration_sec=3.0,
                            visual_role="HOOK",
                            motion_effect="static_hold",
                            transition_out="fade_to_black",
                        )
                    ],
                )
            ],
            audio_track=AudioTrackPlan(
                voice_clips=[
                    AudioClipPlan(
                        clip_id="c_aud_1",
                        scene_id="scene_001",
                        audio_asset_id="aud_1",
                        timeline_start=0.0,
                        timeline_end=3.0,
                        duration_sec=3.0,
                    )
                ]
            ),
            subtitle_track=SubtitleTrackPlan(
                chunks=[
                    SubtitleChunkPlan(
                        chunk_id="chk_1",
                        text="Kiểm thử chất lượng render",
                        start_sec=0.0,
                        end_sec=3.0,
                        duration_sec=3.0,
                        alignment_mode=SubtitleAlignmentMode.WORD_BOUNDARY,
                    )
                ]
            ),
            is_render_ready=True,
        )

        cls.artifact = render_handoff.render(cls.sample_plan, run_id="run_p6_sample_01")

    # 1. Technical QC: File existence and non-zero size
    def test_technical_qc_file_integrity(self):
        report = technical_qc.evaluate(self.artifact, self.sample_plan)
        self.assertIn(report.status, (QualityStatus.PASS, QualityStatus.WARN))
        self.assertGreater(self.artifact.file_size_bytes, 10_000)
        self.assertTrue(any("Output file verified" in e for e in report.evidence))

    # 2. Technical QC: Stream & Codec Validation
    def test_technical_qc_streams_and_codecs(self):
        report = technical_qc.evaluate(self.artifact, self.sample_plan)
        self.assertEqual(self.artifact.width, 1080)
        self.assertEqual(self.artifact.height, 1920)
        self.assertEqual(self.artifact.video_codec, "h264")
        self.assertEqual(self.artifact.audio_codec, "aac")
        self.assertTrue(any("Video Stream: 1080x1920" in e for e in report.evidence))
        self.assertTrue(any("Audio Stream:" in e for e in report.evidence))

    # 3. Final Timing Authority: Duration drift within threshold
    def test_final_timing_drift_within_threshold(self):
        report = technical_qc.evaluate(self.artifact, self.sample_plan)
        drift = abs(self.artifact.duration_seconds - self.sample_plan.duration_seconds) * 1000.0
        self.assertLessEqual(drift, 100.0, "Rendered video duration drift must be <= 100ms")
        self.assertTrue(any("Duration:" in e for e in report.evidence))

    # 4. Black Frame Detection & Intentional Fade Outro Exclusion
    def test_black_frame_intentional_fade_exclusion(self):
        """Intentional fade-to-black at ending must NOT trigger accidental black frame blocker."""
        report = technical_qc.evaluate(self.artifact, self.sample_plan)
        # Should not have black frame blockers because last shot transition is fade_to_black
        black_blockers = [b for b in report.blockers if "black frame" in b.lower()]
        self.assertEqual(len(black_blockers), 0, "Deliberate fade-to-black should not be blocked")

    # 5. Freeze Detection vs Deliberate Ken Burns / Still Hold
    def test_freeze_detection_vs_deliberate_still_hold(self):
        """Shots marked with static_hold or ken_burns must not be flagged as accidental freezes."""
        report = technical_qc.evaluate(self.artifact, self.sample_plan)
        freeze_blockers = [b for b in report.blockers if "freeze" in b.lower()]
        self.assertEqual(len(freeze_blockers), 0)

    # 6. Subtitle Safe Zone & Line Length Check
    def test_subtitle_safe_zone_validation(self):
        # Create plan with long subtitle
        bad_sub_plan = self.sample_plan.model_copy(deep=True)
        bad_sub_plan.subtitle_track.chunks.append(
            SubtitleChunkPlan(
                text="Đây là một dòng phụ đề có độ dài vượt quá giới hạn an toàn ba mươi sáu ký tự trên màn hình",
                start_sec=0.0,
                end_sec=3.0,
                duration_sec=3.0,
            )
        )
        report = technical_qc.evaluate(self.artifact, bad_sub_plan)
        self.assertTrue(any("exceeds readable line length" in w for w in report.warnings))

    # 7. Subtitle Alignment Mode Explicit Declaration
    def test_subtitle_alignment_mode_explicit(self):
        chunk = self.sample_plan.subtitle_track.chunks[0]
        self.assertEqual(chunk.alignment_mode, SubtitleAlignmentMode.WORD_BOUNDARY)
        # Verify fallback mode
        fallback_chunk = SubtitleChunkPlan(
            text="Phân cụm dự phòng",
            start_sec=0.0,
            end_sec=2.0,
            duration_sec=2.0,
        )
        self.assertEqual(fallback_chunk.alignment_mode, SubtitleAlignmentMode.PROPORTIONAL_FALLBACK)

    # 8. Short Asset Fallback Policy
    def test_short_asset_fallback_order(self):
        shot = ShotPlan(
            shot_id="sh_short",
            asset_id="ast_short",
            duration_sec=5.0,
        )
        # Asset duration 2.0s < 5.0s, no alternates -> Ken Burns on still
        policy, meta = render_handoff.resolve_short_asset_policy(
            shot=shot,
            target_duration=5.0,
            asset_media_duration=2.0,
            alternate_candidates=[],
        )
        self.assertIn(policy, (ShortAssetFallbackPolicy.KEN_BURNS_ON_STILL, ShortAssetFallbackPolicy.PERMITTED_LOOP))
        self.assertIn("target_duration", meta)

    # 9. Semantic QC: Wrong entity / action detection
    def test_semantic_qc_wrong_entity_or_action(self):
        bad_shot = ShotPlan(
            shot_id="sh_bad",
            asset_id="ast_bad",
            visual_role="PROCESS",
            match_score=0.30,  # Below 0.40 threshold
            visual_prompt="car traffic on highway",
        )
        mismatch_plan = EditorPlan(
            plan_id="plan_mismatch",
            scenes=[
                ScenePlan(
                    scene_id="scn_1",
                    narration="Nghệ nhân rèn kiếm thủ công.",
                    actual_duration_seconds=3.0,
                    shots=[bad_shot],
                )
            ],
            duration_seconds=3.0,
        )
        visual_axis, _ = semantic_qc.evaluate(
            artifact=self.artifact,
            editor_plan=mismatch_plan,
        )
        self.assertEqual(visual_axis.status, QualityStatus.FAIL)
        self.assertTrue(any("Severe visual mismatch" in b for b in visual_axis.blockers))

    # 10. Semantic QC: Ungrounded Absolute Claim Detection
    def test_semantic_qc_ungrounded_claims(self):
        from production.contracts import ScriptPlan, SceneNarration
        script = ScriptPlan(
            title="Kiểm thử sự thật",
            full_script="Đây là công nghệ số 1 thế giới chắc chắn 100% không thể sai.",
            scenes=[
                SceneNarration(
                    scene_id="scn_1",
                    scene_index=1,
                    narration="Đây là công nghệ số 1 thế giới chắc chắn 100%.",
                    fact_refs=["fact_fake_999"],
                )
            ],
        )
        _, content_axis = semantic_qc.evaluate(
            artifact=self.artifact,
            script_plan=script,
            fact_pack=FactPack(topic="Công nghệ", claims=[]),
        )
        self.assertEqual(content_axis.status, QualityStatus.FAIL)
        self.assertTrue(any("Ungrounded absolute claim" in b or "references unknown claim" in b for b in content_axis.blockers))

    # 11. Editorial QC: Hook & Cut Density Evaluation
    def test_editorial_qc_craft_evaluation(self):
        report = editorial_qc.evaluate(self.artifact, self.sample_plan)
        self.assertIn(report.status, (QualityStatus.PASS, QualityStatus.WARN))
        self.assertIsNotNone(report.score)
        self.assertTrue(any("Cut Pacing:" in e for e in report.evidence))
        self.assertTrue(any("Hook Evaluation:" in e for e in report.evidence))

    # 12. 6-Axis Quality Report Activation & Blocker Gates
    def test_quality_orchestrator_6_axis_and_blockers(self):
        from production.contracts import AutoVideoRequest
        run = ProductionRun(
            id="run_p6_test_eval",
            request=AutoVideoRequest(request_id="req_p6", instruction="Chế tác kiếm Katana"),
            editor_plan=self.sample_plan,
        )
        report = quality_orchestrator.run_post_render_qc(run, self.artifact)

        # 6 axes must be present
        self.assertIn("technical", report.axes)
        self.assertIn("visual", report.axes)
        self.assertIn("content", report.axes)
        self.assertIn("edit", report.axes)
        self.assertIn("rights", report.axes)
        self.assertIn("story", report.axes)

        # Run status transitions to READY if no blockers
        if len(report.blockers) == 0:
            self.assertEqual(run.status, ProductionRunStatus.READY)

    # 13. Rights Blocker Overrides Composite Score
    def test_rights_blocker_overrides_score(self):
        from production.contracts import AssetCandidate, AssetResolutionResult, SceneAssetResolution, AutoVideoRequest, RightsState
        blocked_asset = AssetCandidate(
            asset_id="ast_dmca",
            source_id="src_dmca",
            provider="unknown",
            media_url="/video.mp4",
            rights_state=RightsState.BLOCKED,
        )
        run = ProductionRun(
            id="run_p6_rights_fail",
            request=AutoVideoRequest(request_id="req_p6", instruction="Video test"),
            editor_plan=self.sample_plan,
            resolved_assets=AssetResolutionResult(
                run_id="run_p6_rights_fail",
                resolutions=[
                    SceneAssetResolution(
                        scene_id="scn_1",
                        intent_id="int_1",
                        selected_candidate=blocked_asset,
                    )
                ],
                rights_blocker_count=1,
            ),
        )
        report = quality_orchestrator.run_post_render_qc(run, self.artifact)
        self.assertEqual(report.overall_status, QualityStatus.FAIL)
        self.assertIn(run.status, (ProductionRunStatus.BLOCKED_RIGHTS, ProductionRunStatus.NEEDS_REVIEW))

    # 14. Auto-Fix Engine: Subtitle Overflow Repair
    def test_auto_fix_subtitle_overflow(self):
        from production.contracts import AutoVideoRequest
        run = ProductionRun(
            id="run_p6_autofix",
            request=AutoVideoRequest(request_id="req_p6", instruction="Video test"),
            editor_plan=self.sample_plan.model_copy(deep=True),
        )
        run.editor_plan.subtitle_track.chunks = [
            SubtitleChunkPlan(
                text="Câu thoại phụ đề này quá dài so với giới hạn an toàn ba mươi sáu ký tự trên màn hình",
                start_sec=0.0,
                end_sec=4.0,
                duration_sec=4.0,
            )
        ]
        q_rep = QualityReport(
            report_id="qc_test",
            run_id="run_p6_autofix",
            stage_name="final_qc",
            warnings=["subtitle chunk exceeds readable line length (78 chars)"],
        )
        self.assertTrue(auto_fix.can_auto_fix(q_rep, attempt_count=1))
        ok, desc, stages = auto_fix.attempt_auto_fix(run, q_rep, attempt_number=1)
        self.assertTrue(ok)
        self.assertIn("editor_planning", stages)
        # Chunks were split
        self.assertEqual(len(run.editor_plan.subtitle_track.chunks), 2)

    # 15. Auto-Fix Engine: Bounded Retry Loop
    def test_auto_fix_bounded_attempts(self):
        q_rep = QualityReport(
            report_id="qc_test",
            run_id="run_bound",
            stage_name="final_qc",
            warnings=["repeated footage detected"],
        )
        # Attempt 1: allowed
        self.assertTrue(auto_fix.can_auto_fix(q_rep, attempt_count=1))
        # Attempt 2: at limit
        self.assertFalse(auto_fix.can_auto_fix(q_rep, attempt_count=2))


if __name__ == "__main__":
    unittest.main()
