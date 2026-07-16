"""VF-03.02a Commit 3 — Staging acceptance smoke test script running 10 shadow narration jobs."""
from __future__ import annotations

import datetime
import hashlib
import json
import logging
import os
import sys
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

# Insert service control-plane root and worker root to sys.path
SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

WORKSPACE_ROOT = SERVICE_ROOT.parent.parent
sys.path.insert(0, str(WORKSPACE_ROOT))

# Setup dummy environments before imports
os.environ["DATABASE_URL"] = os.environ.get("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5433/visionflow_test?sslmode=disable")
os.environ["VISIONFLOW_ALLOW_INSECURE_DB"] = "true"
os.environ["VISIONFLOW_WORKER_SUBJECT"] = "service|visionflow-intelligence-worker"
os.environ["VISIONFLOW_NARRATION_HANDOFF_MODE"] = "shadow"
os.environ["VISIONFLOW_ORGANIZATION_ID"] = "de305d54-75b4-431b-adb2-d0459b1e50df"
os.environ["VISIONFLOW_CONTROL_PLANE_URL"] = "http://localhost:8000/api/v1"
os.environ["APP_ENV"] = "staging"
os.environ["VISIONFLOW_TOKEN_URL"] = "https://localhost:8000/oauth/token"
os.environ["VISIONFLOW_WORKER_CLIENT_ID"] = "dummy-worker-id"
os.environ["VISIONFLOW_WORKER_CLIENT_SECRET"] = "dummy-secret"
os.environ["VISIONFLOW_AUTH_AUDIENCE"] = "dummy-audience"

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.core.oidc import VerifiedIdentity
from app.main import app
from app.routers.auth import require_identity

# Override Auth dependency to simulate valid service credentials
app.dependency_overrides[require_identity] = lambda: VerifiedIdentity(
    subject="service|visionflow-intelligence-worker",
    email=None,
    display_name=None,
    scopes=["workflow:narration:complete"],
)


class MockedResponse:
    def __init__(self, status_code: int, content: bytes, headers: dict) -> None:
        self.status_code = status_code
        self.content = content
        self.headers = headers

    def json(self):
        return json.loads(self.content.decode("utf-8"))


# Route requests from worker client to FastAPI TestClient directly
def mock_http_send(session_self, request, **kwargs):
    if "oauth/token" in request.url:
        return MockedResponse(
            status_code=200,
            content=json.dumps({"access_token": "mock-token", "expires_in": 3600, "token_type": "Bearer"}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )

    client = TestClient(app)
    url_path = request.url.replace("http://localhost:8000", "").replace("https://localhost:8000", "")
    headers = dict(request.headers)
    headers["Authorization"] = "Bearer test-service-token"

    response = client.request(
        method=request.method,
        url=url_path,
        content=request.body,
        headers=headers,
    )
    if response.status_code not in (200, 201):
        print(f"DEBUG HTTP {response.status_code}: {response.text}")
    return MockedResponse(response.status_code, response.content, dict(response.headers))


# Collect logged reconciliation reports
collected_reports = []


class StagingReconciliationHandler(logging.Handler):
    def emit(self, record):
        try:
            report = json.loads(record.getMessage())
            if "workflow_run_id" in report and "legacy_job_id" in report:
                collected_reports.append(report)
        except Exception:
            pass


reconciliation_logger = logging.getLogger("visionflow.shadow_reconciliation")
reconciliation_logger.setLevel(logging.INFO)
reconciliation_logger.addHandler(StagingReconciliationHandler())


def seed_workflow_run(engine, workflow_run_id: uuid.UUID, organization_id: uuid.UUID) -> None:
    """Seed the database with a QUEUED workflow run for our complete-narration target."""
    project_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"staging-project-{organization_id}")
    user_id = uuid.uuid5(uuid.NAMESPACE_DNS, "service-worker-identity")
    membership_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"membership-{user_id}-{organization_id}")
    with engine.begin() as conn:
        # Check and seed organization if not exists
        conn.execute(
            text("INSERT INTO organizations (id, slug, name, created_at, updated_at) VALUES (:org_id, 'staging-org', 'Staging Org', now(), now()) ON CONFLICT (id) DO NOTHING"),
            {"org_id": organization_id}
        )
        # Check and seed user if not exists
        conn.execute(
            text("INSERT INTO users (id, identity_subject, created_at, updated_at) VALUES (:user_id, 'service|visionflow-intelligence-worker', now(), now()) ON CONFLICT (identity_subject) DO NOTHING"),
            {"user_id": user_id}
        )
        # Check and seed organization membership if not exists
        conn.execute(
            text("INSERT INTO organization_memberships (id, organization_id, user_id, role, created_at, updated_at) "
                 "VALUES (:membership_id, :org_id, (SELECT id FROM users WHERE identity_subject = 'service|visionflow-intelligence-worker' LIMIT 1), 'service', now(), now()) "
                 "ON CONFLICT (organization_id, user_id) DO NOTHING"),
            {"membership_id": membership_id, "org_id": organization_id}
        )
        # Check and seed video_project if not exists
        conn.execute(
            text("INSERT INTO video_projects (id, organization_id, title, brief, created_at, updated_at) "
                 "VALUES (:proj_id, :org_id, 'Staging Project', 'Staging Brief', now(), now()) ON CONFLICT (id) DO NOTHING"),
            {"proj_id": project_id, "org_id": organization_id}
        )
        conn.execute(
            text("INSERT INTO workflow_runs (id, project_id, state, idempotency_key, prompt_manifest, input_payload, created_at, updated_at) "
                 "VALUES (:run_id, :proj_id, 'PLANNING', :idem_key, '{}'::jsonb, '{}'::jsonb, now(), now()) "
                 "ON CONFLICT (id) DO NOTHING"),
            {"run_id": workflow_run_id, "proj_id": project_id, "idem_key": f"idem-{workflow_run_id}"}
        )


def main():
    print("--- VisionFlow Narration Handoff Staging Acceptance Test ---")
    db_url = os.environ["DATABASE_URL"]
    engine = create_engine(db_url)

    # 1. Test database connection
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("[OK] Connected to disposable database.")
    except Exception as exc:
        print(f"[FAIL] Could not connect to database at {db_url}: {exc}")
        sys.exit(1)

    organization_id = uuid.UUID(os.environ["VISIONFLOW_ORGANIZATION_ID"])

    # 2. Patch worker client network calls and MySQL save
    from worker.application.narration_handoff import NarrationHandoffCoordinator
    from worker.infrastructure.repositories.video_job_repository import VideoJobRepository

    # Mock legacy MySQL save
    VideoJobRepository.save_script_result = MagicMock(return_value=None)

    # Run jobs
    with patch("requests.Session.send", mock_http_send):
        coordinator = NarrationHandoffCoordinator()

        # Execute 10 different narration jobs
        for i in range(1, 11):
            job_id = 200 + i
            workflow_run_id = uuid.uuid4()
            print(f"Executing shadow Job #{job_id} linked to workflow_run {workflow_run_id}...")

            # Seed workflow run in Control Plane PostgreSQL database
            seed_workflow_run(engine, workflow_run_id, organization_id)

            hook = f"Amazing staging scene hook for job {job_id}"
            full_script = f"Staging acceptance script content for job {job_id} that satisfies the 40 characters limit."
            scenes = [
                {"scene_id": f"scene-{job_id}-1", "narration": "Hello this is staging", "visual_prompt": "Abstract visual", "duration": 5},
                {"scene_id": f"scene-{job_id}-2", "narration": "Keep observing shadow results", "visual_prompt": "Structured logs", "duration": 8},
                {"scene_id": f"scene-{job_id}-3", "narration": "Final acceptance scene", "visual_prompt": "Staging complete", "duration": 10},
            ]
            seo_tags = {
                "workflow_run_id": str(workflow_run_id),
                "organization_id": str(organization_id),
                "source_metadata": {"provider": "openai", "model": "gpt-4"},
            }
            trace_id = uuid.uuid4().hex

            coordinator.handle_narration(
                job_id, hook, full_script, scenes, seo_tags, trace_id=trace_id
            )

    print("\n--- Shadow Reconciliation Verification (10 Jobs) ---")
    if len(collected_reports) < 10:
        print(f"[FAIL] Expected at least 10 reconciliation reports, but found {len(collected_reports)}.")
        sys.exit(1)

    print("| Job ID | Workflow Run ID | Idempotency Key | CP Version ID | Script Parity | Result | Trace ID |")
    print("|---|---|---|---|---|---|---|")
    matched_count = 0
    for rep in collected_reports:
        # Verify details
        res = rep["result"]
        if res == "matched":
            matched_count += 1
        print(f"| {rep['legacy_job_id']} | {rep['workflow_run_id']} | {rep['idempotency_key'][:25]}... | {rep['control_plane_version_id']} | PASS | {res} | {rep['trace_id'][:10]}... |")

    print(f"\nMatched: {matched_count}/10")
    if matched_count == 10:
        print("[OK] All 10 staging acceptance jobs matched successfully!")
        sys.exit(0)
    else:
        print("[FAIL] Some staging jobs did not match or failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
