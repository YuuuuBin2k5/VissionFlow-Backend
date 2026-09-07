"""
Integration Tests for Phase 3 - Orchestrator Pipeline Execution & Dependency Invalidation
Tests:
- End-to-end execution through Stages 7 (research_story), 8 (script_generation), 9 (script_quality_gate).
- Verification of REAL execution mode and payload schema persistence.
- EditorPlan grounded in canonical ScriptPlan scenes.
- Dependency invalidation logic on 'script_changed'.
"""

import pytest

from production.contracts import (
    AutoVideoRequest,
    ProductionRun,
    ProductionRunStatus,
    QualityStatus,
    SourceInput,
    StageStatus,
)
from production.orchestrator import STAGE_REALITY_MAP, ProductionOrchestrator
from production.repositories.run_repository import DevelopmentRunRepository


@pytest.fixture
def clean_repo():
    repo = DevelopmentRunRepository()
    repo.clear_all()
    return repo


@pytest.mark.anyio
async def test_orchestrator_phase3_stages_real_execution(clean_repo):
    orchestrator = ProductionOrchestrator()

    # Verify reality map for Phase 3 stages
    assert STAGE_REALITY_MAP["research_story"] == "REAL"
    assert STAGE_REALITY_MAP["script_generation"] == "REAL"
    assert STAGE_REALITY_MAP["script_quality_gate"] == "REAL"

    # Create run
    req = AutoVideoRequest(
        request_id="req_test_01",
        instruction="Làm video ngắn khám phá kỹ thuật mộng gỗ Kigumi truyền thống",
        sources=[
            SourceInput(
                source_id="src_mock_01",
                url="tests/fixtures/sample_test_video.mp4",
                rights_ack=True,
            )
        ],
        target_duration_sec=45.0,
        language="vi",
    )
    run = orchestrator.create_run(req)
    assert run.id is not None

    # Execute pipeline asynchronously
    await orchestrator._execute_pipeline(run.id)

    # Fetch updated run
    updated_run = clean_repo.get(run.id)
    assert updated_run is not None
    assert updated_run.status in (ProductionRunStatus.READY, ProductionRunStatus.TIMELINE_READY, ProductionRunStatus.FOUNDATION_READY)
    assert updated_run.progress_pct == 100

    # Verify Phase 3 artifacts exist on the run model
    assert updated_run.fact_pack is not None
    assert len(updated_run.fact_pack.claims) >= 3
    assert updated_run.fact_pack.topic != ""

    assert updated_run.story_plan is not None
    assert len(updated_run.story_plan.beats) >= 4
    assert updated_run.story_plan.target_duration_sec == 45.0

    assert updated_run.script_plan is not None
    assert len(updated_run.script_plan.scenes) == len(updated_run.story_plan.beats)
    # Check canonical consistency
    expected_full_script = " ".join(s.narration for s in updated_run.script_plan.scenes)
    assert updated_run.script_plan.full_script == expected_full_script

    assert updated_run.script_gate_report is not None
    assert updated_run.script_gate_report.status in (QualityStatus.PASS, QualityStatus.WARN)
    assert updated_run.script_gate_report.blocker_count == 0

    # Verify Stage Runs
    stage_map = {s.stage_name: s for s in updated_run.stages}
    assert stage_map["research_story"].status == StageStatus.COMPLETED
    assert stage_map["research_story"].execution_mode == "REAL"
    assert "fact_pack" in stage_map["research_story"].output_json

    assert stage_map["script_generation"].status == StageStatus.COMPLETED
    assert stage_map["script_generation"].execution_mode == "REAL"
    assert "full_script" in stage_map["script_generation"].output_json

    assert stage_map["script_quality_gate"].status == StageStatus.COMPLETED
    assert stage_map["script_quality_gate"].execution_mode == "REAL"
    assert "status" in stage_map["script_quality_gate"].output_json

    # Verify EditorPlan is grounded in ScriptPlan scenes
    assert updated_run.editor_plan is not None
    assert len(updated_run.editor_plan.scenes) == len(updated_run.script_plan.scenes)
    for idx, scn_plan in enumerate(updated_run.editor_plan.scenes):
        assert scn_plan.narration == updated_run.script_plan.scenes[idx].narration


def test_orchestrator_script_changed_invalidation(clean_repo):
    orchestrator = ProductionOrchestrator()

    req = AutoVideoRequest(
        request_id="req_test_02",
        instruction="Video test invalidation",
        target_duration_sec=30.0,
    )
    run = orchestrator.create_run(req)

    # Invalidate for script change
    invalidated = orchestrator.invalidate_for_change(run.id, "script_changed")

    expected_invalidated = [
        "script_quality_gate",
        "visual_planning",
        "asset_resolution",
        "editor_planning",
        "tts_timing",
        "timeline_compose",
        "final_qc",
    ]
    assert invalidated == expected_invalidated

    # Verify the stages were reset to PENDING in the repository
    reloaded = clean_repo.get(run.id)
    for stg in reloaded.stages:
        if stg.stage_name in expected_invalidated:
            assert stg.status == StageStatus.PENDING
            assert stg.is_cached is False
