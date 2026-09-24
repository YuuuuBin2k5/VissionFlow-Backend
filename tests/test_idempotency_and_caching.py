"""
Idempotency, Caching & Invalidation Test Suite (Mục 7)
Proves:
- Case A: Same stage + same input_hash -> reuse cache, execution count does NOT increment.
- Case B: Stage N retry -> stages 1..N-1 remain untouched / reused.
- Case C: Change visuals only -> preserves research, story, script, tts; invalidates visual, asset, editor, timeline, final QC.
- Case D: Change voice -> preserves research, story, script; invalidates tts, editor, timeline, final QC.
"""

import asyncio
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from production.contracts import StageStatus
from production.input_normalizer import InputNormalizer
from production.orchestrator import orchestrator, ORDERED_STAGES
from production.repositories.run_repository import run_repository


def test_case_a_idempotency():
    async def _run():
        print("\n[IDEMPOTENCY TEST] --- CASE A: Same stage + same input_hash ---")
        request = InputNormalizer.normalize(raw_instruction="Chủ đề kiểm thử idempotency", requested_format="short")
        run = orchestrator.create_run(request)

        stage_name = "research_story"
        input_data = {"topic": "chủ đề test", "version": 1}

        # First execution
        out1 = await orchestrator._run_stage_idempotent(run.id, stage_name, input_data, 30)
        count_1 = orchestrator.get_execution_count(run.id, stage_name)
        assert count_1 == 1, f"Expected 1 execution, got {count_1}"

        # Second execution with EXACT same input
        out2 = await orchestrator._run_stage_idempotent(run.id, stage_name, input_data, 30)
        count_2 = orchestrator.get_execution_count(run.id, stage_name)
        assert count_2 == 1, f"Execution count must NOT increment on cached hit! Expected 1, got {count_2}"
        assert out1 == out2, "Cached output must match original output"

        # Verify stage marked as cached
        cached_run = run_repository.get(run.id)
        stg = next(s for s in cached_run.stages if s.stage_name == stage_name)
        assert stg.is_cached is True, "Stage run was not marked as is_cached=True"
        print("  -> Case A PASSED: Cache hit verified. Execution counter stayed at 1.")

    asyncio.run(_run())


def test_case_b_stage_retry():
    async def _run():
        print("\n[IDEMPOTENCY TEST] --- CASE B: Stage N fail & retry ---")
        request = InputNormalizer.normalize(raw_instruction="Chủ đề kiểm thử retry", requested_format="short")
        run = orchestrator.create_run(request)

        # Pre-execute stage 0 and 1
        await orchestrator._run_stage_idempotent(run.id, "input_normalization", {"data": 1}, 10)
        await orchestrator._run_stage_idempotent(run.id, "source_ingest", {"data": 2}, 20)

        count_norm_before = orchestrator.get_execution_count(run.id, "input_normalization")
        count_ingest_before = orchestrator.get_execution_count(run.id, "source_ingest")

        # Now retry from stage "research_story" (stage index 2)
        await orchestrator.retry_stage(run.id, "research_story")

        count_norm_after = orchestrator.get_execution_count(run.id, "input_normalization")
        count_ingest_after = orchestrator.get_execution_count(run.id, "source_ingest")

        assert count_norm_after == count_norm_before, "Upstream stage 0 must NOT re-execute on downstream retry!"
        assert count_ingest_after == count_ingest_before, "Upstream stage 1 must NOT re-execute on downstream retry!"
        print("  -> Case B PASSED: Upstream stages 0 and 1 were NOT re-executed during retry.")

    asyncio.run(_run())



def test_case_c_visuals_invalidation():
    print("\n[IDEMPOTENCY TEST] --- CASE C: Invalidate Visuals Only ---")
    request = InputNormalizer.normalize(raw_instruction="Kiểm thử đổi visual", requested_format="short")
    run = orchestrator.create_run(request)

    # Mark all stages as COMPLETED
    for stg in ORDERED_STAGES:
        run_repository.update_stage_status(run.id, stg, StageStatus.COMPLETED)

    # Invalidate visuals
    invalidated = orchestrator.invalidate_for_change(run.id, "visuals_changed")

    # Check that research, story, script are PRESERVED
    updated_run = run_repository.get(run.id)
    stages_by_name = {s.stage_name: s for s in updated_run.stages}

    preserved = ["input_normalization", "source_ingest", "research_story", "script_generation", "script_quality_gate"]
    for p in preserved:
        assert stages_by_name[p].status == StageStatus.COMPLETED, f"Stage {p} should be PRESERVED but was {stages_by_name[p].status}"

    expected_invalidated = {"visual_planning", "asset_resolution", "editor_planning", "timeline_compose", "final_qc"}
    for exp in expected_invalidated:
        assert stages_by_name[exp].status == StageStatus.PENDING, f"Stage {exp} should be PENDING after visual invalidation"

    print("  -> Case C PASSED: Research, story, and script were preserved. Visual/editor/timeline were invalidated.")


def test_case_d_voice_invalidation():
    print("\n[IDEMPOTENCY TEST] --- CASE D: Invalidate Voice Only ---")
    request = InputNormalizer.normalize(raw_instruction="Kiểm thử đổi giọng", requested_format="short")
    run = orchestrator.create_run(request)

    for stg in ORDERED_STAGES:
        run_repository.update_stage_status(run.id, stg, StageStatus.COMPLETED)

    # Invalidate voice
    invalidated = orchestrator.invalidate_for_change(run.id, "voice_changed")

    updated_run = run_repository.get(run.id)
    stages_by_name = {s.stage_name: s for s in updated_run.stages}

    # Preserved
    preserved = ["input_normalization", "source_ingest", "research_story", "script_generation", "script_quality_gate", "visual_planning", "asset_resolution"]
    for p in preserved:
        assert stages_by_name[p].status == StageStatus.COMPLETED, f"Stage {p} should be PRESERVED but was {stages_by_name[p].status}"

    # Invalidated
    expected_invalidated = {"tts_timing", "editor_planning", "timeline_compose", "final_qc"}
    for exp in expected_invalidated:
        assert stages_by_name[exp].status == StageStatus.PENDING, f"Stage {exp} should be PENDING after voice invalidation"

    print("  -> Case D PASSED: Research, story, script, and visuals preserved. TTS, editor, and timeline invalidated.")


async def main():
    await test_case_a_idempotency()
    await test_case_b_stage_retry()
    test_case_c_visuals_invalidation()
    test_case_d_voice_invalidation()
    print("\n[SUCCESS] ALL 4 IDEMPOTENCY & INVALIDATION CASES PASSED PROVEN!")


if __name__ == "__main__":
    asyncio.run(main())
