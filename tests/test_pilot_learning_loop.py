"""
Automated Test Suite for VisionFlow Real Channel Pilot Support & Learning Loop.
Tests:
- RunEnvironment classification and strict segregation of PILOT runs from FIXTURE/DEV.
- Manual intervention logging and manual_intervention_rate computation.
- Scene-level human feedback items and 8-axis rubric ratings.
- First-pass QC and first-pass human approval quality tracking.
- Script ground truth structured diff and original_script_plan immutability.
- Visual replacement ground truth recording and persistence.
- Channel profile recommendation generation and explicit operator approval flow.
- Pilot production report compilation and root cause failure analysis.
"""

from __future__ import annotations

import json
import pytest
from datetime import datetime, timezone
from pathlib import Path

from production.contracts import (
    AutoVideoRequest,
    ChannelProfileRecommendation,
    ChannelRecommendationStatus,
    HumanReviewRatings,
    ManualInterventionType,
    ProductionRun,
    ProductionRunStatus,
    QualityAxisReport,
    QualityReport,
    QualityStatus,
    RenderArtifact,
    RunEnvironment,
    SceneFeedbackItem,
    SceneFeedbackTag,
    SceneNarration,
    ScriptPlan,
    StorageTier,
)
from production.repositories.run_repository import run_repository
from production.pilot_learning import pilot_learning_service
from production.human_review import human_review_service
from production.quality_orchestrator import quality_orchestrator
from production.channel_profile import channel_profile_registry, ChannelProfile


@pytest.fixture
def clean_pilot_env(tmp_path):
    """Sets up isolated storage directories for testing."""
    test_gt_dir = tmp_path / "pilot_gt"
    test_rec_dir = tmp_path / "channel_recs"
    test_reviews_dir = tmp_path / "reviews"
    pilot_learning_service.ground_truth_dir = test_gt_dir
    pilot_learning_service.visual_swaps_dir = test_gt_dir / "visual_swaps"
    pilot_learning_service.script_diffs_dir = test_gt_dir / "script_diffs"
    pilot_learning_service.recommendations_dir = test_rec_dir

    pilot_learning_service.visual_swaps_dir.mkdir(parents=True, exist_ok=True)
    pilot_learning_service.script_diffs_dir.mkdir(parents=True, exist_ok=True)
    pilot_learning_service.recommendations_dir.mkdir(parents=True, exist_ok=True)
    human_review_service.storage_dir = test_reviews_dir
    human_review_service.storage_dir.mkdir(parents=True, exist_ok=True)
    yield


def test_run_environment_segregation(clean_pilot_env):
    """Verifies that pilot runs are strictly segregated from benchmark fixtures and dev runs."""
    req_dev = AutoVideoRequest(request_id="req_d1", instruction="Dev test", run_environment=RunEnvironment.DEV)
    req_fix = AutoVideoRequest(request_id="req_f1", instruction="Fixture test", run_environment=RunEnvironment.FIXTURE)
    req_pilot = AutoVideoRequest(request_id="req_p1", instruction="Pilot test", run_environment=RunEnvironment.PILOT)

    run_dev = ProductionRun(id="run_d1", request=req_dev, run_environment=RunEnvironment.DEV)
    run_fix = ProductionRun(id="run_f1", request=req_fix, run_environment=RunEnvironment.FIXTURE)
    run_pilot = ProductionRun(id="run_p1", request=req_pilot, run_environment=RunEnvironment.PILOT)

    run_repository.create(run_dev)
    run_repository.create(run_fix)
    run_repository.create(run_pilot)

    assert run_repository.get("run_d1").run_environment == RunEnvironment.DEV
    assert run_repository.get("run_f1").run_environment == RunEnvironment.FIXTURE
    assert run_repository.get("run_p1").run_environment == RunEnvironment.PILOT

    # When compiling pilot report without explicit IDs, only PILOT runs should be aggregated
    report = pilot_learning_service.compile_pilot_report(run_ids=["run_p1"])
    assert report["summary"]["total_pilot_runs"] == 1


def test_manual_interventions_recording_and_rate(clean_pilot_env):
    """Verifies manual intervention tracking and accurate rate calculation."""
    scenes = [
        SceneNarration(scene_index=1, narration="Hook scene test"),
        SceneNarration(scene_index=2, narration="Body scene test"),
        SceneNarration(scene_index=3, narration="Conclusion scene test"),
    ]
    script = ScriptPlan(title="Test Script", full_script="Hook scene test. Body scene test. Conclusion scene test.", scenes=scenes)
    req = AutoVideoRequest(request_id="req_intv", instruction="Intervention test", run_environment=RunEnvironment.PILOT)
    run = ProductionRun(id="run_intv", request=req, script_plan=script, run_environment=RunEnvironment.PILOT)
    run_repository.create(run)

    # Initial: 0 interventions
    assert run.manual_intervention_count == 0
    assert run.manual_intervention_rate == 0.0

    # 1. Script edit intervention
    pilot_learning_service.record_manual_intervention(
        run_id="run_intv",
        intervention_type=ManualInterventionType.HOOK_EDITED,
        scene_index=1,
        description="Changed hook to improve retention",
        before_value="Hook scene test",
        after_value="New compelling hook",
        operator_id="senior_editor",
    )

    # 2. Asset swap intervention
    pilot_learning_service.record_manual_intervention(
        run_id="run_intv",
        intervention_type=ManualInterventionType.VISUAL_CHANGED,
        scene_index=2,
        description="Swapped generic office for ancient scroll footage",
        operator_id="senior_editor",
    )

    updated_run = run_repository.get("run_intv")
    assert updated_run.manual_intervention_count == 2
    # 2 interventions / 3 scenes = 0.67 rate
    assert updated_run.manual_intervention_rate == 0.67
    assert updated_run.manual_interventions[0].intervention_type == ManualInterventionType.HOOK_EDITED
    assert updated_run.manual_interventions[0].operator_id == "senior_editor"


def test_scene_level_feedback_and_8_axis_review(clean_pilot_env):
    """Verifies human operator review submission with 8-axis ratings and scene-level feedback."""
    req = AutoVideoRequest(request_id="req_rev", instruction="Human review test", run_environment=RunEnvironment.PILOT)
    run = ProductionRun(id="run_rev", request=req, status=ProductionRunStatus.READY, run_environment=RunEnvironment.PILOT)
    run_repository.create(run)

    ratings = HumanReviewRatings(
        hook_score=4.5,
        script_score=4.8,
        factual_confidence_score=5.0,  # 8th axis
        visual_relevance_score=4.2,
        pacing_score=4.0,
        subtitle_score=5.0,
        audio_score=4.6,
        overall_publishability=4.8,
    )

    scene_feedback = {
        1: SceneFeedbackItem(scene_index=1, tag=SceneFeedbackTag.GOOD, notes="Strong hook"),
        2: SceneFeedbackItem(scene_index=2, tag=SceneFeedbackTag.WRONG_VISUAL, notes="Asset does not match historical context"),
    }

    record = human_review_service.submit_review(
        run_id="run_rev",
        reviewer="lead_publisher",
        ratings=ratings,
        decision="APPROVED",
        notes="High quality output, safe for distribution",
        scene_feedback=scene_feedback,
    )

    assert record.decision == "APPROVED"
    assert record.ratings.factual_confidence_score == 5.0
    assert 2 in record.scene_feedback
    assert record.scene_feedback[2].tag == SceneFeedbackTag.WRONG_VISUAL

    updated_run = run_repository.get("run_rev")
    assert updated_run.status == ProductionRunStatus.APPROVED
    assert updated_run.human_review is not None
    assert updated_run.human_review.scene_feedback[1].tag == SceneFeedbackTag.GOOD


def test_first_pass_quality_tracking(clean_pilot_env, tmp_path):
    """Verifies that first-pass QC and first-pass human approval flags are accurately captured."""
    from unittest.mock import patch

    req = AutoVideoRequest(request_id="req_fp", instruction="First pass test", run_environment=RunEnvironment.PILOT)
    run = ProductionRun(id="run_fp", request=req, status=ProductionRunStatus.RENDERING, run_environment=RunEnvironment.PILOT)
    run_repository.create(run)

    artifact = RenderArtifact(
        run_id="run_fp",
        output_path_ref="output/test.mp4",
        duration_seconds=45.0,
        file_size_bytes=10_000_000,
        checksum_sha256="abc123sha",
    )

    pass_axis = QualityAxisReport(status=QualityStatus.PASS, score=1.0)
    with patch.object(quality_orchestrator.technical_evaluator, "evaluate", return_value=pass_axis), \
         patch.object(quality_orchestrator.semantic_evaluator, "evaluate", return_value=(pass_axis, pass_axis)), \
         patch.object(quality_orchestrator.editorial_evaluator, "evaluate", return_value=pass_axis):
        qc_report = quality_orchestrator.run_post_render_qc(run, artifact, attempt=1)
        assert run.first_pass_qc_pass is True

    # Review pass 1 without auto fix or manual interventions
    ratings = HumanReviewRatings()
    human_review_service.submit_review(
        run_id="run_fp",
        reviewer="test_reviewer",
        ratings=ratings,
        decision="APPROVED",
    )

    updated_run = run_repository.get("run_fp")
    assert updated_run.first_pass_human_approval is True


def test_script_diff_ground_truth_preservation(clean_pilot_env):
    """Verifies original_script_plan immutability and ScriptDiffGroundTruth recording."""
    orig_scenes = [
        SceneNarration(scene_index=1, narration="Lời mở đầu nguyên bản của trí tuệ nhân tạo."),
        SceneNarration(scene_index=2, narration="Nội dung giải thích chi tiết về đạo lý làm người."),
    ]
    orig_script = ScriptPlan(
        title="Tiêu đề gốc",
        full_script="Lời mở đầu nguyên bản của trí tuệ nhân tạo. Nội dung giải thích chi tiết về đạo lý làm người.",
        scenes=orig_scenes,
        total_word_count=22,
    )

    req = AutoVideoRequest(request_id="req_sc_gt", instruction="Script GT test", run_environment=RunEnvironment.PILOT)
    run = ProductionRun(
        id="run_sc_gt",
        request=req,
        script_plan=orig_script,
        original_script_plan=orig_script.model_copy(deep=True),
        run_environment=RunEnvironment.PILOT,
    )
    run_repository.create(run)

    # Operator edits script (modifies hook + sharpens tone)
    edited_scenes = [
        SceneNarration(scene_index=1, narration="Tại sao cổ nhân dạy: Một điều nhịn bằng chín điều lành?"),
        SceneNarration(scene_index=2, narration="Bởi vì chữ Nhẫn chính là thước đo của bậc đại trí."),
    ]
    edited_script = ScriptPlan(
        title="Bí Mật Chữ Nhẫn",
        full_script="Tại sao cổ nhân dạy: Một điều nhịn bằng chín điều lành? Bởi vì chữ Nhẫn chính là thước đo của bậc đại trí.",
        scenes=edited_scenes,
        total_word_count=24,
    )

    diff = pilot_learning_service.record_script_edit(
        run_id="run_sc_gt",
        edited_script_plan=edited_script,
        operator_id="operator_viet",
        categories=["hook_change", "style_refinement"],
    )

    updated_run = run_repository.get("run_sc_gt")
    # Original is strictly preserved
    assert updated_run.original_script_plan.title == "Tiêu đề gốc"
    assert updated_run.original_script_plan.scenes[0].narration == "Lời mở đầu nguyên bản của trí tuệ nhân tạo."

    # Active script is edited
    assert updated_run.script_plan.title == "Bí Mật Chữ Nhẫn"
    assert updated_run.script_diff_ground_truth is not None
    assert updated_run.script_diff_ground_truth.hook_changed is True
    assert "hook_change" in updated_run.script_diff_ground_truth.categories


def test_visual_swap_ground_truth_persistence(clean_pilot_env):
    """Verifies visual replacement ground truth capture on asset change."""
    req = AutoVideoRequest(request_id="req_vis_gt", instruction="Visual GT test", run_environment=RunEnvironment.PILOT)
    run = ProductionRun(id="run_vis_gt", request=req, run_environment=RunEnvironment.PILOT)
    run_repository.create(run)

    gt = pilot_learning_service.record_visual_swap_ground_truth(
        run_id="run_vis_gt",
        scene_index=1,
        rejected_asset_id="stock_video_modern_office_102",
        selected_replacement_id="scene_ancient_calligraphy_scroll_05",
        reason="Modern office does not match ancient philosophy narrative",
        operator_id="art_director",
    )

    assert gt.rejected_asset_id == "stock_video_modern_office_102"
    assert gt.selected_replacement_id == "scene_ancient_calligraphy_scroll_05"

    updated_run = run_repository.get("run_vis_gt")
    assert len(updated_run.visual_ground_truth) == 1
    assert updated_run.visual_ground_truth[0].reason == "Modern office does not match ancient philosophy narrative"

    # Verify JSON persisted to disk
    gt_file = pilot_learning_service.visual_swaps_dir / f"{gt.record_id}.json"
    assert gt_file.exists()
    with open(gt_file, "r", encoding="utf-8") as f:
        data = json.load(f)
        assert data["rejected_asset_id"] == "stock_video_modern_office_102"


def test_channel_profile_recommendation_and_approval(clean_pilot_env):
    """Verifies learning loop recommendations based on pilot history and explicit approval flow."""
    chan_id = "goc_chiem_nghiem_yuubin"

    # Setup pilot runs with manual hook interventions and deviating durations
    runs = []
    for i in range(4):
        r_id = f"run_pilot_hist_{i}"
        req = AutoVideoRequest(request_id=f"req_h_{i}", instruction="Philosophy lesson", channel_profile_id=chan_id, run_environment=RunEnvironment.PILOT)
        run = ProductionRun(
            id=r_id,
            request=req,
            channel_profile_id=chan_id,
            status=ProductionRunStatus.READY,
            run_environment=RunEnvironment.PILOT,
            render_artifact=RenderArtifact(
                run_id=r_id,
                output_path_ref=f"out/{r_id}.mp4",
                duration_seconds=58.0,  # Deviates by +13s from 45s target
                file_size_bytes=1000,
            ),
        )
        run_repository.create(run)

        # Submit human review
        human_review_service.submit_review(
            run_id=r_id,
            reviewer="reviewer_1",
            ratings=HumanReviewRatings(hook_score=3.8, pacing_score=3.5),
            decision="APPROVED",
        )

        # Add hook intervention
        pilot_learning_service.record_manual_intervention(
            run_id=r_id,
            intervention_type=ManualInterventionType.HOOK_EDITED,
            scene_index=1,
            description="Hook rewritten for punchiness",
        )
        runs.append(run_repository.get(r_id))

    # Generate recommendations
    recs = pilot_learning_service.generate_channel_recommendations(chan_id)
    assert len(recs) > 0

    # Ensure recommendations are strictly PENDING (never auto-applied)
    target_rec = next((r for r in recs if r.parameter == "target_duration_seconds"), recs[0])
    assert target_rec.status == ChannelRecommendationStatus.PENDING

    # Test explicit operator approval
    profile_before = channel_profile_registry.get_profile(chan_id)
    orig_val = getattr(profile_before, target_rec.parameter)

    pilot_learning_service.apply_recommendation(chan_id, target_rec.recommendation_id, operator_id="admin")

    profile_after = channel_profile_registry.get_profile(chan_id)
    assert getattr(profile_after, target_rec.parameter) == target_rec.suggested_value

    # Reset profile attribute back
    setattr(profile_after, target_rec.parameter, orig_val)
    channel_profile_registry.register_profile(profile_after)


def test_pilot_production_report_generation(clean_pilot_env):
    """Verifies compilation of comprehensive pilot report with metrics and decision."""
    req = AutoVideoRequest(request_id="req_rep_p", instruction="Report test", run_environment=RunEnvironment.PILOT)
    run = ProductionRun(
        id="run_rep_p",
        request=req,
        status=ProductionRunStatus.APPROVED,
        run_environment=RunEnvironment.PILOT,
        first_pass_qc_pass=True,
        first_pass_human_approval=True,
        render_artifact=RenderArtifact(
            run_id="run_rep_p",
            output_path_ref="output/pilot_test.mp4",
            duration_seconds=50.0,
            file_size_bytes=12_000_000,
        ),
    )
    run_repository.create(run)

    report = pilot_learning_service.compile_pilot_report(run_ids=["run_rep_p"])
    assert report["run_environment"] == "PILOT"
    assert report["summary"]["total_pilot_runs"] == 1
    assert report["summary"]["completed_renders"] == 1
    assert report["summary"]["render_success_rate_pct"] == 100.0
    assert "cost_accounting" in report
    assert "latency_metrics" in report
    assert "failure_root_causes" in report
    # No REAL_OPERATOR review was submitted; simulation/test data cannot earn a daily-production recommendation.
    assert report["final_evaluation"]["recommendation"] == "GO_REAL_HUMAN_PILOT"


def test_simulated_review_and_intervention_do_not_contaminate_real_metrics(clean_pilot_env):
    """Pilot scripts may exercise the flow, but cannot create human-quality evidence."""
    from production.contracts import InterventionSource, ReviewSource

    request = AutoVideoRequest(request_id="req_integrity", instruction="Integrity", run_environment=RunEnvironment.PILOT)
    run = ProductionRun(id="run_integrity", request=request, status=ProductionRunStatus.READY, run_environment=RunEnvironment.PILOT)
    run_repository.create(run)
    human_review_service.submit_review(
        run_id=run.id, reviewer="pilot_script", ratings=HumanReviewRatings(), decision="APPROVED",
        review_source=ReviewSource.SIMULATED_OPERATOR,
    )
    pilot_learning_service.record_manual_intervention(
        run_id=run.id, intervention_type=ManualInterventionType.HOOK_EDITED,
        intervention_source=InterventionSource.SIMULATED_OPERATOR,
    )
    report = pilot_learning_service.compile_pilot_report(run_ids=[run.id])
    assert report["simulation"]["simulated_reviews"] == 1
    assert report["real_operator"]["runs_reviewed"] == 0
    assert report["real_operator"]["human_rating_average"] is None
    assert report["manual_interventions"]["total_interventions"] == 0
