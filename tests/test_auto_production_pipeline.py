"""
Integration test for VisionFlow Auto Production System (v1)
Tests InputNormalizer, Orchestrator, EditorPlan generation, and QualityReport evaluation.
"""

import asyncio
import sys
from pathlib import Path

# Add backend root to path
BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from production.config_loader import config_loader
from production.contracts import ProductionFormat, ProductionRunStatus, QualityStatus
from production.input_normalizer import InputNormalizer
from production.orchestrator import orchestrator
from production.repositories.run_repository import run_repository


def test_config_loader():
    print("[1/4] Testing Config Loader...")
    defaults = config_loader.production_defaults
    thresholds = config_loader.quality_thresholds
    assert defaults.get("version") == 1, "Failed to load production_defaults version"
    assert thresholds.get("version") == 1, "Failed to load quality_thresholds version"
    format_conf = config_loader.get_format_defaults("short")
    assert format_conf.get("aspect_ratio") == "9:16", "Short aspect ratio mismatch"
    print("  -> Config Loader OK!")


def test_input_normalizer():
    print("[2/4] Testing Input Normalizer...")
    raw_text = "Làm short 50-60 giây về quy trình sản xuất đũa tre truyền thống https://youtube.com/watch?v=123"
    request = InputNormalizer.normalize(raw_instruction=raw_text, requested_format="auto")
    assert request.format == ProductionFormat.SHORT, f"Expected short, got {request.format}"
    assert len(request.sources) == 1, "Failed to extract embedded URL source"
    assert request.target_duration_sec == 55.0, "Expected target_duration_sec = 55.0"
    print("  -> Input Normalizer OK!")


def test_orchestrator_execution():
    async def _run():
        print("[3/4] Testing Production Orchestrator Execution...")
        request = InputNormalizer.normalize(
            raw_instruction="Khám phá bí mật nghệ thuật rèn kiếm katana Nhật Bản",
            requested_format="short",
        )
        run = orchestrator.create_run(request)
        assert run.id.startswith("run_"), "Invalid run ID format"
        assert run.status == ProductionRunStatus.CREATED, "Run not created with CREATED status"

        # Execute pipeline
        await orchestrator._execute_pipeline(run.id)

        # Validate final state - In Phase 1.5, skeleton/stub pipeline MUST finish at FOUNDATION_READY, NOT READY
        finished_run = run_repository.get(run.id)
        assert finished_run is not None, "Run not found in repository"
        assert finished_run.status in (ProductionRunStatus.READY, ProductionRunStatus.TIMELINE_READY, ProductionRunStatus.FOUNDATION_READY), f"Expected READY, TIMELINE_READY or FOUNDATION_READY, got {finished_run.status}"
        assert finished_run.progress_pct == 100, f"Expected 100%, got {finished_run.progress_pct}%"
        assert finished_run.editor_plan is not None, "EditorPlan was not generated"
        assert len(finished_run.editor_plan.scenes) >= 3, f"Expected at least 3 scenes, got {len(finished_run.editor_plan.scenes)}"

        # Verify stages declare execution mode honestly
        valid_modes = [s for s in finished_run.stages if s.execution_mode in ("REAL", "STUB")]
        assert len(valid_modes) == len(finished_run.stages), "All stages must declare execution_mode ('REAL' or 'STUB')"
        real_stages = [s for s in finished_run.stages if s.execution_mode == "REAL"]
        assert len(real_stages) > 0, "Real stages must be present in execution"
        print("  -> Orchestrator Execution OK!")

        print("[4/4] Testing Quality System Report (Honest Evaluation)...")
        assert finished_run.quality_report is not None, "QualityReport was not generated"
        # Quality report: in Phase 6 real evaluators exist, otherwise NOT_EVALUATED
        from production.orchestrator import STAGE_REALITY_MAP
        if STAGE_REALITY_MAP.get("final_qc") == "REAL":
            assert finished_run.quality_report.overall_status in (QualityStatus.PASS, QualityStatus.WARN, QualityStatus.FAIL)
            assert len(finished_run.quality_report.axes) == 6
        else:
            assert finished_run.quality_report.overall_status == QualityStatus.NOT_EVALUATED
            assert finished_run.quality_report.score is None
            assert "No evaluators executed" in (finished_run.quality_report.evaluator_disclaimer or "")
        print("  -> Honest Quality System Report OK!")

    asyncio.run(_run())


if __name__ == "__main__":
    test_config_loader()
    test_input_normalizer()
    test_orchestrator_execution()
    print("\n[SUCCESS] ALL INTEGRATION TESTS PASSED SUCCESSFULLY!")

