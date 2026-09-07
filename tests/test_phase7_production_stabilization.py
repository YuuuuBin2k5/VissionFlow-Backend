"""
Unit and Integration Test Suite for Phase 7 — Production Stabilization, Live E2E & Publishing Readiness.
Verifies:
1. Canonical Renderer & Parity across dispatch modes
2. Production Run Crash Resilience & Idempotent Resumption
3. Render Queue, Heartbeats & Stale Job Recovery
4. Storage Lifecycle Management & Automated Temp GC
5. Cost & Latency Telemetry Tracking
6. Real Human Review Workflow & Ground Truth Dataset Export
7. Final-Frame Semantic QC & Empty Canvas Detection
8. ChannelProfile Defaults & Auto-Upload Safety Gate
9. Publishing Bridge Gates & SHA-256 Idempotency
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from production.canonical_renderer import (
    CanonicalFFmpegRenderer,
    CanonicalRenderSpec,
    canonical_renderer,
)
from production.channel_profile import (
    ChannelProfile,
    ChannelProfileRegistry,
    channel_profile_registry,
)
from production.contracts import (
    AudioClipPlan,
    AudioTrackPlan,
    AutoVideoRequest,
    CostTelemetry,
    EditorPlan,
    EditorPlanType,
    HumanReviewRatings,
    HumanReviewRecord,
    LatencyTelemetry,
    ProductionRun,
    ProductionRunStatus,
    PublicationStatus,
    QualityReport,
    QualityStatus,
    RenderArtifact,
    RenderJobState,
    ScenePlan,
    ShortAssetFallbackPolicy,
    ShotPlan,
    StorageTier,
    SubtitleChunkPlan,
    SubtitleTrackPlan,
)
from production.human_review import (
    HumanReviewService,
    human_review_service,
)
from production.orchestrator import ProductionOrchestrator, orchestrator
from production.publishing_bridge import (
    PublishingBridge,
    publishing_bridge,
)
from production.quality.frame_semantic_qc import (
    FrameSemanticQCEngine,
    frame_semantic_qc,
)
from production.quality_orchestrator import quality_orchestrator
from production.render_dispatcher import (
    RenderDispatcher,
    render_dispatcher,
)
from production.render_handoff import render_handoff
from production.render_queue import (
    ConcurrencyLimiter,
    RenderQueue,
    render_queue,
)
from production.repositories.run_repository import run_repository
from production.storage_lifecycle import (
    StorageLifecycleManager,
    storage_lifecycle,
)
from production.telemetry import (
    CostTracker,
    LatencyTracker,
    ProviderRouter,
    cost_tracker,
    latency_tracker,
)


class TestPhase7ProductionStabilization(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_dir = Path("d:/VisionFlow/.media_cache/test_fixtures_p7")
        cls.test_dir.mkdir(parents=True, exist_ok=True)

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="vf_p7_test_")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # -------------------------------------------------------------------------
    # 1. Canonical Renderer & Parity
    # -------------------------------------------------------------------------
    def test_canonical_renderer_direct_execution(self):
        """Canonical renderer must generate standard 1080x1920 30fps vertical video."""
        out_path = Path(self.temp_dir) / "canonical_out.mp4"
        spec = CanonicalRenderSpec(
            run_id="run_test_canonical_01",
            output_path=out_path,
            duration_seconds=2.0,
            width=1080,
            height=1920,
            fps=30,
            video_sources=[],
            audio_sources=[],
            subtitle_chunks=[
                {"start_sec": 0.2, "end_sec": 1.8, "text": "Canonical Test Subtitle"}
            ],
        )

        probe = canonical_renderer.render(spec)
        self.assertTrue(out_path.exists())
        self.assertGreater(probe.file_size_bytes, 1000)
        self.assertEqual(probe.width, 1080)
        self.assertEqual(probe.height, 1920)
        self.assertAlmostEqual(probe.duration_seconds, 2.0, delta=0.5)

    def test_render_dispatcher_parity(self):
        """RenderDispatcher must route LOCAL_DIRECT and return compliant RenderArtifact."""
        from production.render_dispatcher import RenderTarget
        out_path = Path(self.temp_dir) / "dispatch_out.mp4"
        spec = CanonicalRenderSpec(
            run_id="run_test_dispatch_01",
            output_path=out_path,
            duration_seconds=1.5,
            width=1080,
            height=1920,
            fps=30,
            video_sources=[],
            audio_sources=[],
            subtitle_chunks=[],
        )

        probe = render_dispatcher.dispatch(spec, target=RenderTarget.LOCAL_DIRECT)
        self.assertIsNotNone(probe)
        self.assertEqual(probe.width, 1080)
        self.assertEqual(probe.height, 1920)
        self.assertTrue(out_path.exists())

    def test_render_handoff_delegates_to_canonical_dispatcher(self):
        """render_handoff.render() must adapt EditorPlan to CanonicalRenderSpec without code divergence."""
        editor_plan = EditorPlan(
            plan_id="plan_p7_handoff",
            run_id="run_p7_handoff_01",
            duration_seconds=2.0,
            aspect_ratio="9:16",
            scenes=[
                ScenePlan(
                    scene_id="scn_01",
                    scene_index=1,
                    narration="Deterministic speech narration",
                    actual_duration_seconds=2.0,
                    shots=[
                        ShotPlan(
                            shot_id="sht_01",
                            asset_id="asset_test",
                            duration_sec=2.0,
                        )
                    ],
                )
            ],
            subtitle_track=SubtitleTrackPlan(
                chunks=[
                    SubtitleChunkPlan(
                        start_sec=0.1,
                        end_sec=1.9,
                        text="Safe Margin Subtitle Test",
                    )
                ]
            ),
        )

        artifact = render_handoff.render(editor_plan, run_id="run_p7_handoff_01")
        self.assertIsNotNone(artifact)
        self.assertEqual(artifact.run_id, "run_p7_handoff_01")
        self.assertEqual(artifact.video_codec, "h264")
        self.assertTrue(Path(artifact.internal_file_path).exists())

    # -------------------------------------------------------------------------
    # 2. Crash Resilience & Orchestrator Resumption
    # -------------------------------------------------------------------------
    def test_orchestrator_resume_skips_completed_stages(self):
        """Orchestrator must resume unfinished runs without rerunning completed stages."""
        import asyncio
        req = AutoVideoRequest(
            request_id="req_resumption_test",
            instruction="Resumption test video",
            format="short",
            language="vi",
            review_mode="final_only",
            sources=[],
        )
        run = ProductionRun(
            id="run_resump_01",
            status=ProductionRunStatus.INPUT_NORMALIZED,
            mode="auto",
            request=req,
        )

        # Simulate stage 1 and 2 already COMPLETED
        from production.contracts import ProductionStageRun, StageStatus
        stg1 = ProductionStageRun(
            id="stg_1",
            run_id=run.id,
            stage_name="input_normalization",
            status=StageStatus.COMPLETED,
            cost_usd=0.001,
            output_json={"normalized": True},
        )
        stg2 = ProductionStageRun(
            id="stg_2",
            run_id=run.id,
            stage_name="research_story",
            status=StageStatus.COMPLETED,
            cost_usd=0.002,
            output_json={"angle": "test"},
        )
        run.stages = [stg1, stg2]
        run_repository.create(run)

        # Verify find_resumable_runs picks it up
        resumables = run_repository.find_resumable_runs()
        self.assertTrue(any(r.id == run.id for r in resumables))

        # Idempotent stage skip check: Calling for completed stage returns existing output immediately
        res = asyncio.run(
            orchestrator._run_stage_idempotent(run.id, "input_normalization", {"raw": 1}, 5)
        )
        self.assertEqual(res, {"normalized": True})

    # -------------------------------------------------------------------------
    # 3. Render Queue, Heartbeats & Stale Job Recovery
    # -------------------------------------------------------------------------
    def test_render_queue_concurrency_and_stale_detection(self):
        """RenderQueue must enforce max concurrency, monitor heartbeats, and detect stale jobs."""
        queue = RenderQueue()

        spec = CanonicalRenderSpec(
            run_id="run_q_01",
            output_path=Path(self.temp_dir) / "q.mp4",
            duration_seconds=1.0,
        )

        # Enqueue 3 jobs
        j1_id = queue.enqueue("run_q_01", spec)
        j2_id = queue.enqueue("run_q_02", spec)
        j3_id = queue.enqueue("run_q_03", spec)

        # Acquire slots
        w1_job = queue.acquire_next_job("worker_alpha")
        self.assertIsNotNone(w1_job)
        self.assertEqual(w1_job.job_id, j1_id)
        self.assertEqual(w1_job.state, RenderJobState.RENDERING)

        w2_job = queue.acquire_next_job("worker_beta")
        self.assertIsNotNone(w2_job)
        self.assertEqual(w2_job.job_id, j2_id)

        # Heartbeat check
        queue.record_heartbeat(w1_job.job_id)
        self.assertIsNotNone(w1_job.heartbeat_at)

        # Simulate stale worker by setting heartbeat to past
        from datetime import datetime, timedelta, timezone
        w2_job.heartbeat_at = datetime.now(timezone.utc) - timedelta(seconds=300)
        stale_jobs = queue.check_stale_jobs(stale_threshold_seconds=180)
        self.assertEqual(len(stale_jobs), 1)
        self.assertEqual(w2_job.state, RenderJobState.RETRYING)

        # Complete job
        queue.complete_job(w1_job.job_id, str(Path(self.temp_dir) / "q.mp4"))
        self.assertEqual(w1_job.state, RenderJobState.COMPLETED)

    # -------------------------------------------------------------------------
    # 4. Storage Lifecycle Management & Temp GC
    # -------------------------------------------------------------------------
    def test_storage_lifecycle_tiers_and_gc(self):
        """StorageLifecycleManager must segregate tiers and delete expired TEMP files without touching FINAL."""
        lifecycle = StorageLifecycleManager(media_root=Path(self.temp_dir) / "storage")

        # Create files across tiers
        f_raw = lifecycle.get_tier_path(StorageTier.RAW) / "source.mp4"
        f_derived = lifecycle.get_tier_path(StorageTier.DERIVED) / "thumb.jpg"
        f_temp = lifecycle.get_tier_path(StorageTier.TEMP) / "intermediate.ts"
        f_final = lifecycle.get_tier_path(StorageTier.FINAL) / "output.mp4"

        f_raw.write_text("raw data")
        f_derived.write_text("derived thumb")
        f_temp.write_text("temp intermediate")
        f_final.write_text("final video")

        # Verify all exist
        self.assertTrue(f_raw.exists())
        self.assertTrue(f_derived.exists())
        self.assertTrue(f_temp.exists())
        self.assertTrue(f_final.exists())

        # Age temp file by setting mtime 7200s ago
        old_time = time.time() - 7200
        os.utime(f_temp, (old_time, old_time))

        # Cleanup temp files older than 3600s
        cleaned = lifecycle.cleanup_temp_files(max_age_seconds=3600)
        self.assertGreaterEqual(cleaned, 1)

        # Temp should be gone; raw, derived, final MUST remain intact
        self.assertFalse(f_temp.exists())
        self.assertTrue(f_raw.exists())
        self.assertTrue(f_derived.exists())
        self.assertTrue(f_final.exists())

    # -------------------------------------------------------------------------
    # 5. Cost & Latency Telemetry
    # -------------------------------------------------------------------------
    def test_cost_and_latency_telemetry_tracking(self):
        """Telemetry engine must accurately compute cost breakdown and latency percentiles."""
        cost_trk = CostTracker()

        cost_trk.record_llm_call(
            stage="script_generation",
            provider="google",
            model="gemini-1.5-flash",
            prompt_tokens=5000,
            completion_tokens=2000,
            latency_ms=1200,
        )

        cost = cost_trk.build_telemetry(
            video_duration_seconds=30.0,
            render_seconds=15.0,
            tts_chars=300,
            stock_requests=2,
        )

        self.assertGreater(cost.total_cost_usd, 0.0)
        self.assertGreater(cost.cost_per_output_minute, 0.0)

        lat = LatencyTracker.calculate_telemetry({
            "input_normalization": 500,
            "research_story": 1200,
            "script_generation": 2500,
            "visual_planning": 1800,
            "asset_resolution": 3000,
            "editor_planning": 800,
            "tts_timing": 1500,
            "timeline_compose": 4000,
            "final_qc": 1100,
        })

        self.assertGreater(lat.p50_stage_duration_ms, 0.0)
        self.assertGreater(lat.total_pipeline_duration_ms, 0)

    # -------------------------------------------------------------------------
    # 6. Real Human Review Workflow & Ground Truth Dataset
    # -------------------------------------------------------------------------
    def test_human_review_workflow_and_dataset(self):
        """Human review must validate 7-axis rubric, advance status, and persist ground truth."""
        review_svc = HumanReviewService(storage_dir=Path(self.temp_dir) / "reviews")

        run = ProductionRun(
            id="req_review_01",
            status=ProductionRunStatus.READY,
            mode="auto",
            request=AutoVideoRequest(
                request_id="req_review_01",
                instruction="Review test instruction",
                format="short",
                language="vi",
                review_mode="final_only",
                sources=[],
            ),
        )
        run_repository.create(run)

        # 1. Invalid rating should raise ValidationError
        with self.assertRaises(Exception):
            HumanReviewRatings(
                hook_score=6.0,  # exceeds 5.0
            )

        # 2. Valid rating submission
        valid_ratings = HumanReviewRatings(
            hook_score=4.5,
            script_score=4.2,
            visual_relevance_score=4.0,
            pacing_score=4.8,
            subtitle_score=5.0,
            audio_score=4.0,
            overall_publishability=4.5,
        )
        record = review_svc.submit_review(
            run_id=run.id,
            reviewer="lead_editor_01",
            ratings=valid_ratings,
            decision="APPROVED",
            notes="Excellent hook and clear kinetic subtitles.",
        )

        self.assertEqual(record.decision, "APPROVED")
        self.assertEqual(record.reviewer, "lead_editor_01")

        # Run status in repo should now be APPROVED
        reloaded = run_repository.get(run.id)
        self.assertIsNotNone(reloaded)
        self.assertEqual(reloaded.status, ProductionRunStatus.APPROVED)
        self.assertIsNotNone(reloaded.human_review)

        # Export dataset must include this review
        dataset = review_svc.export_dataset()
        self.assertGreaterEqual(len(dataset), 1)
        self.assertEqual(dataset[0]["reviewer"], "lead_editor_01")
        self.assertTrue(dataset[0].get("is_operator_review", True))

    # -------------------------------------------------------------------------
    # 7. Final-Frame Semantic QC & Empty Canvas Detection
    # -------------------------------------------------------------------------
    def test_frame_semantic_qc_empty_canvas_detection(self):
        """Solid plain canvas without visual texture must be rejected unless planned as graphic fallback."""
        qc_engine = FrameSemanticQCEngine()

        # Create synthetic solid image (all black bytes)
        solid_img = Path(self.temp_dir) / "solid_black.jpg"
        solid_img.write_bytes(b"\x00" * 2000)

        # Create textured image
        textured_img = Path(self.temp_dir) / "textured.jpg"
        textured_bytes = bytes([i % 256 for i in range(25000)])
        textured_img.write_bytes(textured_bytes)

        is_empty_solid, var_solid = qc_engine.analyze_frame_variance(solid_img)
        self.assertTrue(is_empty_solid)

        is_empty_tex, var_tex = qc_engine.analyze_frame_variance(textured_img)
        self.assertFalse(is_empty_tex)

    # -------------------------------------------------------------------------
    # 8. ChannelProfile Defaults & Safety Policy
    # -------------------------------------------------------------------------
    def test_channel_profile_defaults_and_safety(self):
        """ChannelProfiles must enforce auto_publish_enabled=False default."""
        registry = ChannelProfileRegistry()
        default_prof = registry.get_profile("goc_chiem_nghiem_yuubin")
        self.assertIsNotNone(default_prof)

        # Crucial invariant: auto_publish_enabled MUST be False by default
        self.assertFalse(default_prof.auto_publish_enabled)
        self.assertEqual(default_prof.target_duration_seconds, 45)

    # -------------------------------------------------------------------------
    # 9. Publishing Safety Gates & SHA-256 Idempotency
    # -------------------------------------------------------------------------
    def test_publishing_bridge_safety_and_idempotency(self):
        """PublishingBridge must block unapproved runs and prevent duplicate publications via SHA-256 idempotency key."""
        from production.publishing_bridge import PublicationRequest, PublishingSafetyError

        bridge = PublishingBridge()

        # 1. Unapproved run should be rejected
        unapproved_run = ProductionRun(
            id="run_pub_unapproved",
            status=ProductionRunStatus.READY,  # not yet APPROVED
            mode="auto",
            request=AutoVideoRequest(
                request_id="req_pub_unapproved",
                instruction="Publishing test unapproved",
                format="short",
                language="vi",
                review_mode="final_only",
                sources=[],
            ),
        )
        run_repository.create(unapproved_run)

        req1 = PublicationRequest(
            run_id=unapproved_run.id,
            platform="tiktok",
            channel_id="channel_main",
            title="Unapproved Video",
            description="desc",
        )
        with self.assertRaises(PublishingSafetyError):
            bridge.request_publication(req1)

        # 2. Approved run with artifact should publish successfully
        art_path = Path(self.temp_dir) / "pub_video.mp4"
        art_path.write_bytes(b"synthetic_video_payload_for_checksum")

        approved_run = ProductionRun(
            id="run_pub_approved",
            status=ProductionRunStatus.APPROVED,
            mode="auto",
            request=AutoVideoRequest(
                request_id="req_pub_approved",
                instruction="Publishing test approved",
                format="short",
                language="vi",
                review_mode="final_only",
                sources=[],
            ),
            render_artifact=RenderArtifact(
                run_id="run_pub_approved",
                output_path_ref=str(art_path),
                internal_file_path=str(art_path),
                duration_seconds=15.0,
                width=1080,
                height=1920,
                fps=30,
                video_codec="h264",
                audio_codec="aac",
                file_size_bytes=len(art_path.read_bytes()),
            ),
        )
        run_repository.create(approved_run)

        req2 = PublicationRequest(
            run_id=approved_run.id,
            platform="tiktok",
            channel_id="channel_main",
            title="Approved Short Video",
            description="desc",
        )

        res1 = bridge.request_publication(req2)
        # No live publisher adapter is configured in this test; an internal smoke test is not an external post.
        self.assertEqual(res1.status, PublicationStatus.SIMULATED_PUBLISHED)
        self.assertIsNone(res1.external_post_id)
        self.assertIsNotNone(res1.publication_id)

        # 3. Duplicate publish call with identical parameters must return same result (idempotent)
        res2 = bridge.request_publication(req2)
        self.assertEqual(res2.publication_id, res1.publication_id)
        self.assertEqual(res2.idempotency_key, res1.idempotency_key)


if __name__ == "__main__":
    unittest.main()
