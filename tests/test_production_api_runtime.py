"""
API Runtime Test Suite for VisionFlow Auto Production System (Spec v1) - Section 9
Verifies:
- POST /api/v1/auto-production/runs (201 Created & 422 for invalid request)
- GET  /api/v1/auto-production/runs/{id} (200 OK & 404 for non-existent)
- GET  /api/v1/auto-production/runs/{id}/stages (200 OK with List[ProductionStageRun])
- GET  /api/v1/auto-production/runs/{id}/editor-plan (200 OK with EditorPlan schema)
- GET  /api/v1/auto-production/runs/{id}/quality-report (200 OK with QualityReport schema)
- POST /api/v1/auto-production/runs/{id}/retry (200 OK & 422 for unknown stage)
- POST /api/v1/auto-production/runs/{id}/invalidate (200 OK & 422 for invalid reason)
- No 500 Unhandled Exceptions across all calls.
"""

import sys
from pathlib import Path
import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

CONTROL_PLANE = BACKEND_ROOT / "services" / "control-plane"
if str(CONTROL_PLANE) not in sys.path:
    sys.path.insert(0, str(CONTROL_PLANE))

from fastapi.testclient import TestClient
from app.main import app
from production.contracts import ProductionRunStatus, QualityStatus
from production.orchestrator import ORDERED_STAGES, orchestrator

client = TestClient(app)



def test_api_runtime_full_suite():
    print("\n[API RUNTIME TEST] 1. Test POST /runs with invalid input -> 422")
    invalid_resp = client.post("/api/v1/auto-production/runs", json={})
    assert invalid_resp.status_code == 422, f"Expected 422 for empty request, got {invalid_resp.status_code}"
    print("  -> Correctly rejected with 422.")

    print("\n[API RUNTIME TEST] 2. Test POST /runs with valid input -> 201 Created")
    create_resp = client.post(
        "/api/v1/auto-production/runs",
        json={
            "instruction": "Quy trình chế tác đồng hồ Thụy Sĩ đỉnh cao",
            "format": "short",
            "language": "vi",
            "review_mode": "final_only",
        },
    )
    assert create_resp.status_code == 201, f"Expected 201 Created, got {create_resp.status_code}: {create_resp.text}"
    run_data = create_resp.json()
    run_id = run_data["id"]
    assert run_id.startswith("run_"), f"Invalid run_id format: {run_id}"
    assert run_data["status"] in [s.value for s in ProductionRunStatus]
    print(f"  -> Successfully created run {run_id} (Status 201).")

    print("\n[API RUNTIME TEST] 3. Test GET /runs/{run_id} -> 200 OK")
    get_resp = client.get(f"/api/v1/auto-production/runs/{run_id}")
    assert get_resp.status_code == 200, f"Expected 200, got {get_resp.status_code}"
    retrieved_data = get_resp.json()
    assert retrieved_data["id"] == run_id
    assert "status" in retrieved_data
    assert "progress_pct" in retrieved_data
    print("  -> GET run succeeded with valid contract.")

    print("\n[API RUNTIME TEST] 4. Test GET /runs/unknown_id -> 404 Not Found")
    not_found_resp = client.get("/api/v1/auto-production/runs/non_existent_run_999")
    assert not_found_resp.status_code == 404, f"Expected 404, got {not_found_resp.status_code}"
    print("  -> Non-existent run returned 404.")

    print("\n[API RUNTIME TEST] 5. Test GET /runs/{run_id}/stages -> 200 OK")
    stages_resp = client.get(f"/api/v1/auto-production/runs/{run_id}/stages")
    assert stages_resp.status_code == 200, f"Expected 200, got {stages_resp.status_code}"
    stages_data = stages_resp.json()
    assert isinstance(stages_data, list), "Stages must be a list"
    assert len(stages_data) == len(ORDERED_STAGES), f"Expected {len(ORDERED_STAGES)} stages, got {len(stages_data)}"
    # Check execution_mode
    for stg in stages_data:
        assert "stage_name" in stg
        assert "execution_mode" in stg
        assert stg["execution_mode"] in ["REAL", "STUB", "CACHED"]
    print(f"  -> GET stages succeeded ({len(stages_data)} stages verified).")

    # Run pipeline to completion deterministically in test environment
    import asyncio
    asyncio.run(orchestrator._execute_pipeline(run_id))

    print("\n[API RUNTIME TEST] 6. Test GET /runs/{run_id}/editor-plan -> 200 OK")
    plan_resp = client.get(f"/api/v1/auto-production/runs/{run_id}/editor-plan")
    assert plan_resp.status_code == 200, f"Expected 200, got {plan_resp.status_code}: {plan_resp.text}"
    plan_data = plan_resp.json()


    assert "plan_id" in plan_data
    assert "scenes" in plan_data
    assert len(plan_data["scenes"]) >= 2
    for scn in plan_data["scenes"]:
        assert "scene_id" in scn
        assert "narration" in scn
        assert "shots" in scn
    print("  -> GET editor-plan succeeded with valid scenes structure.")

    print("\n[API RUNTIME TEST] 7. Test GET /runs/{run_id}/quality-report -> 200 OK")
    qc_resp = client.get(f"/api/v1/auto-production/runs/{run_id}/quality-report")
    assert qc_resp.status_code == 200, f"Expected 200, got {qc_resp.status_code}"
    qc_data = qc_resp.json()
    assert qc_data["overall_status"] in [QualityStatus.NOT_EVALUATED.value, QualityStatus.PASS.value, QualityStatus.WARN.value]
    assert "report_id" in qc_data
    assert "axes" in qc_data
    print("  -> GET quality-report succeeded with valid contract.")

    print("\n[API RUNTIME TEST] 8. Test POST /runs/{run_id}/retry -> 200 OK & 422 for invalid stage")
    # Invalid stage
    retry_bad = client.post(f"/api/v1/auto-production/runs/{run_id}/retry", json={"stage_name": "invalid_magic_stage"})
    assert retry_bad.status_code == 422, f"Expected 422 for bad stage, got {retry_bad.status_code}"

    # Valid retry
    retry_ok = client.post(f"/api/v1/auto-production/runs/{run_id}/retry", json={"stage_name": "script_generation"})
    assert retry_ok.status_code == 200, f"Expected 200, got {retry_ok.status_code}"
    print("  -> Retry endpoint passed (422 bad stage, 200 valid stage).")

    print("\n[API RUNTIME TEST] 9. Test POST /runs/{run_id}/invalidate -> 200 OK & 422 for invalid reason")
    # Invalid reason
    inv_bad = client.post(f"/api/v1/auto-production/runs/{run_id}/invalidate", json={"reason": "random_fake_reason"})
    assert inv_bad.status_code == 422, f"Expected 422 for bad reason, got {inv_bad.status_code}"

    # Valid invalidation
    inv_ok = client.post(f"/api/v1/auto-production/runs/{run_id}/invalidate", json={"reason": "visuals_changed"})
    assert inv_ok.status_code == 200, f"Expected 200, got {inv_ok.status_code}"
    inv_data = inv_ok.json()
    assert "invalidated_stages" in inv_data
    assert "visual_planning" in inv_data["invalidated_stages"]
    print("  -> Invalidate endpoint passed (422 bad reason, 200 valid reason).")

    print("\n[SUCCESS] ALL FASTAPI AUTO-PRODUCTION RUNTIME ROUTES PASSED (NO 500 ERRORS)!")


if __name__ == "__main__":
    test_api_runtime_full_suite()
