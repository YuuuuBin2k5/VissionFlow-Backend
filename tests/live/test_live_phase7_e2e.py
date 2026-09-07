"""
Live End-to-End Production & Publishing Readiness Test (Phase 7 - Section 28 & 29).
Marked with @pytest.mark.live and @pytest.mark.live_e2e.
Runs the complete production pipeline from script/source -> canonical render -> frame QC -> human review -> publishing queue.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from pathlib import Path

import pytest

from production.canonical_renderer import canonical_renderer
from production.contracts import (
    AutoVideoRequest,
    EditorPlan,
    HumanReviewRatings,
    ProductionRun,
    ProductionRunStatus,
    PublicationStatus,
    RenderArtifact,
    ScenePlan,
    ShotPlan,
    SubtitleChunkPlan,
    SubtitleTrackPlan,
)
from production.human_review import human_review_service
from production.publishing_bridge import PublicationRequest, publishing_bridge
from production.quality.frame_semantic_qc import frame_semantic_qc
from production.quality_orchestrator import quality_orchestrator
from production.render_handoff import render_handoff
from production.repositories.run_repository import run_repository


@pytest.mark.live
@pytest.mark.live_e2e
class TestLivePhase7E2E:
    @classmethod
    def setup_class(cls):
        cls.test_dir = Path(tempfile.mkdtemp(prefix="vf_live_p7_"))

    @classmethod
    def teardown_class(cls):
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_live_canonical_render_qc_review_publish_cycle(self):
        """
        Executes a full live cycle:
        1. Compile deterministic EditorPlan
        2. Render real MP4 vertical video via Canonical FFmpeg stack
        3. Extract keyframes and perform Frame Semantic & Empty Canvas QC
        4. Execute Multimodal Post-Render Quality Orchestrator (6 axes)
        5. Submit human review operator approval
        6. Verify Publishing Bridge idempotency and safety gate
        """
        run_id = f"live_run_p7_{int(Path(self.test_dir).stat().st_ctime)}"

        # 1. Prepare Plan with valid safe zone subtitles
        editor_plan = EditorPlan(
            plan_id=f"plan_{run_id}",
            run_id=run_id,
            duration_seconds=3.0,
            aspect_ratio="9:16",
            scenes=[
                ScenePlan(
                    scene_id="scn_01",
                    scene_index=1,
                    narration="Live E2E production stabilization test scene.",
                    actual_duration_seconds=3.0,
                    shots=[
                        ShotPlan(
                            shot_id="sht_01",
                            asset_id="asset_live_bg",
                            duration_sec=3.0,
                            is_graphic_fallback=True,  # Allowed graphic card fallback
                        )
                    ],
                )
            ],
            subtitle_track=SubtitleTrackPlan(
                chunks=[
                    SubtitleChunkPlan(
                        start_sec=0.2,
                        end_sec=2.8,
                        text="Safe Zone TikTok Live Test",
                    )
                ]
            ),
        )

        run = ProductionRun(
            id=run_id,
            status=ProductionRunStatus.RENDERING,
            mode="auto",
            request=AutoVideoRequest(
                request_id=f"req_{run_id}",
                instruction="Produce live E2E benchmark short",
                format="short",
                language="vi",
                review_mode="final_only",
                sources=[],
            ),
            editor_plan=editor_plan,
        )
        run_repository.create(run)

        # 2. Render actual MP4 via canonical pipeline
        artifact = render_handoff.render(editor_plan, run_id=run_id)
        assert artifact is not None
        assert Path(artifact.internal_file_path).exists()
        assert artifact.file_size_bytes > 5000
        assert artifact.width == 1080
        assert artifact.height == 1920

        run.render_artifact = artifact
        run.status = ProductionRunStatus.RENDERED
        run_repository.update(run)

        # 3. Final-Frame Semantic QC inspection
        frame_report = frame_semantic_qc.evaluate(
            Path(artifact.internal_file_path),
            editor_plan,
            temp_dir=self.test_dir / "qc_frames",
        )
        assert frame_report.total_frames_sampled >= 1
        assert frame_report.is_pass

        # 4. Quality Orchestrator 6-axis execution
        qc_report = quality_orchestrator.run_post_render_qc(run, artifact)
        assert qc_report is not None
        assert qc_report.blocker_count == 0
        assert run.status == ProductionRunStatus.READY

        # 5. Human Operator Review Gate
        review_ratings = HumanReviewRatings(
            hook_score=4.8,
            script_score=4.5,
            visual_relevance_score=4.2,
            pacing_score=4.7,
            subtitle_score=5.0,
            audio_score=4.5,
            overall_publishability=4.8,
        )
        record = human_review_service.submit_review(
            run_id=run.id,
            reviewer="qa_director_live",
            ratings=review_ratings,
            decision="APPROVED",
            notes="Live E2E verified with clean audio and vertical safe layout.",
        )
        assert record.decision == "APPROVED"

        reloaded = run_repository.get(run.id)
        assert reloaded.status == ProductionRunStatus.APPROVED

        # 6. Publishing Bridge Execution
        pub_req = PublicationRequest(
            run_id=run.id,
            platform="tiktok",
            channel_id="channel_goc_chiem_nghiem",
            title="Live E2E Production Short",
            description="Automated production test #visionflow",
        )
        pub_result = publishing_bridge.request_publication(pub_req)
        assert pub_result.status == PublicationStatus.PUBLISHED
        assert pub_result.publication_id.startswith("pub_")

        # Verify duplicate attempt is idempotently handled
        dup_result = publishing_bridge.request_publication(pub_req)
        assert dup_result.publication_id == pub_result.publication_id
        assert dup_result.idempotency_key == pub_result.idempotency_key
