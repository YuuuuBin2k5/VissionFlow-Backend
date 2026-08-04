"""
Reset workflows stuck in RENDERING (or ASSETS_READY) back to STORYBOARDED so that
the next render pass can re-attempt them cleanly.

Why this is needed:
  The free GitHub-Actions runner has a 45-minute budget. When a render job is
  dispatched (STORYBOARDED → ASSETS_READY → RENDERING) but the runner is killed
  mid-flight (OOM, timeout, ffmpeg crash, network timeout to R2/Pexels), the
  Control Plane DB records the last successfully committed state (RENDERING or
  ASSETS_READY). No new outbox event is emitted, so the next relay pass finds
  zero events and the workflow stays stuck forever.

  This script rolls the state back to STORYBOARDED by directly calling the
  Control Plane transitions API with a privileged worker token so the next
  relay/worker invocation can pick it up again.

Usage:
    # Reset ALL RENDERING-stuck workflows
    python services/control-plane/scripts/reset_stuck_rendering.py --all

    # Reset a specific workflow
    python services/control-plane/scripts/reset_stuck_rendering.py \\
        --workflow-run-id 1db3e73f-cd36-4355-8569-19f1528bb137

    # Preview only (no API calls)
    python services/control-plane/scripts/reset_stuck_rendering.py --all --dry-run

Env vars required (same as advance_stuck_workflow.py):
    DATABASE_URL                    — PostgreSQL connection string
    REDIS_URL                       — Redis connection string
    VISIONFLOW_CONTROL_PLANE_URL    — Control Plane base URL
    VISIONFLOW_WORKER_CLIENT_ID     — OIDC client ID
    VISIONFLOW_WORKER_CLIENT_SECRET — OIDC client secret
    VISIONFLOW_AUTH_AUDIENCE        — OIDC audience (default: visionflow-control-plane)
    VISIONFLOW_ORGANIZATION_ID      — Organization UUID
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path

import requests
from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.infrastructure.database import get_engine  # noqa: E402
from app.infrastructure.models import VideoProject, WorkflowRun  # noqa: E402
from app.infrastructure.redis_stream_publisher import RedisStreamSettings  # noqa: E402


# ---------------------------------------------------------------------------
# Minimal Control Plane HTTP client
# ---------------------------------------------------------------------------

class ControlPlaneClient:
    def __init__(self) -> None:
        self._base = os.environ["VISIONFLOW_CONTROL_PLANE_URL"].rstrip("/")
        self._org_id = os.environ["VISIONFLOW_ORGANIZATION_ID"]
        self._token_url = f"{self._base}/auth/token"
        self._client_id = os.environ["VISIONFLOW_WORKER_CLIENT_ID"]
        self._client_secret = os.environ["VISIONFLOW_WORKER_CLIENT_SECRET"]
        self._audience = os.environ.get("VISIONFLOW_AUTH_AUDIENCE", "visionflow-control-plane")
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    def _get_token(self) -> str:
        if self._token and time.monotonic() < self._token_expires_at:
            return self._token
        resp = requests.post(
            self._token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "audience": self._audience,
            },
            timeout=15,
        )
        resp.raise_for_status()
        payload = resp.json()
        self._token = payload["access_token"]
        self._token_expires_at = time.monotonic() + max(1, payload.get("expires_in", 300) - 60)
        return self._token

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "X-Request-ID": uuid.uuid4().hex,
        }

    def get_execution_context(self, workflow_run_id: str) -> dict:
        resp = requests.get(
            f"{self._base}/workflows/{workflow_run_id}/execution-context",
            params={"organization_id": self._org_id},
            headers=self._headers(),
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()

    def transition(self, workflow_run_id: str, expected_state: str, target_state: str, output_payload: dict) -> dict:
        resp = requests.post(
            f"{self._base}/workflows/{workflow_run_id}/transitions",
            json={
                "organization_id": self._org_id,
                "expected_state": expected_state,
                "target_state": target_state,
                "output_payload": output_payload,
            },
            headers=self._headers(),
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Redis re-queue helper
# ---------------------------------------------------------------------------

def requeue_to_redis(run: WorkflowRun, project: VideoProject, redis_client: Redis, stream: str) -> str:
    """Push a QUEUED event into Redis so the next worker pass picks it up."""
    fields = {
        "event_id": uuid.uuid4().hex,
        "event_type": "visionflow.workflow_run.state_changed.v1",
        "aggregate_type": "workflow_run",
        "aggregate_id": str(run.id),
        "trace_id": uuid.uuid4().hex,
        "payload": json.dumps({
            "workflow_run_id": str(run.id),
            "organization_id": str(project.organization_id),
            "from_state": "READY",
            "to_state": "QUEUED",
            "step_key": "queue",
            "intake": {
                "title": project.title,
                "brief": project.brief,
                "format_profile": project.format_profile,
                "timezone": project.timezone,
                "input_payload": run.input_payload,
                "prompt_manifest": run.prompt_manifest,
            },
        }, separators=(",", ":"), sort_keys=True),
    }
    msg_id = redis_client.xadd(stream, fields)
    return str(msg_id)


# ---------------------------------------------------------------------------
# Core reset logic
# ---------------------------------------------------------------------------

RECOVERABLE_STATES = ("RENDERING", "ASSETS_READY")

def reset_one(
    run: WorkflowRun,
    project: VideoProject,
    session: Session,
    client: ControlPlaneClient,
    redis_client: Redis | None,
    redis_stream: str,
    dry_run: bool,
) -> bool:
    current_state = run.state
    print(f"  Workflow : {run.id}")
    print(f"  Title    : {project.title[:70]}")
    print(f"  State    : {current_state}")

    if current_state not in RECOVERABLE_STATES:
        print(f"  SKIP: state '{current_state}' is not in recoverable states {RECOVERABLE_STATES}")
        return False

    if dry_run:
        print(f"  DRY RUN: would reset {current_state} → QUEUED")
        return True

    # Directly set DB state back to QUEUED so Control Plane API and Web UI see QUEUED
    try:
        run.state = "QUEUED"
        run.failure_code = None
        session.commit()
        print(f"  ✓ Direct DB reset {current_state} → QUEUED")
    except Exception as exc:
        session.rollback()
        print(f"  ERROR: Could not update DB state to QUEUED: {exc}")
        return False

    # Push to Redis Stream for worker consumption
    try:
        msg_id = requeue_to_redis(run, project, redis_client, redis_stream)
        print(f"  ✓ Re-queued to Redis → msg {msg_id}")
    except Exception as exc:
        print(f"  ERROR: Could not push to Redis: {exc}")
        return False

    return True


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reset RENDERING/ASSETS_READY/FAILED stuck workflows for re-attempt"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="Reset ALL recoverable-state workflows")
    group.add_argument("--workflow-run-id", help="UUID of a specific WorkflowRun to reset")
    parser.add_argument("--dry-run", action="store_true", help="Print plan without making any API/Redis calls")
    args = parser.parse_args()

    client = ControlPlaneClient()
    redis_settings = RedisStreamSettings.from_env()
    redis_client = Redis.from_url(redis_settings.url, decode_responses=True) if not args.dry_run else None

    with Session(get_engine()) as session:
        if args.all:
            rows = session.execute(
                select(WorkflowRun, VideoProject)
                .join(VideoProject, VideoProject.id == WorkflowRun.project_id)
                .where(WorkflowRun.state.in_(list(RECOVERABLE_STATES)))
            ).all()
        else:
            run_id = uuid.UUID(args.workflow_run_id)
            rows = session.execute(
                select(WorkflowRun, VideoProject)
                .join(VideoProject, VideoProject.id == WorkflowRun.project_id)
                .where(WorkflowRun.id == run_id)
            ).all()

        if not rows:
            print(f"No workflows in {RECOVERABLE_STATES} state found. Nothing to do.")
            return 0

        # ─── Lọc bỏ AI Dubbing jobs ─────────────────────────────────────────
        # Dubbing jobs KHÔNG đi qua Redis stream — chỉ được xử lý bởi
        # process_queued_jobs.py → DubbingStrategy. Không được reset chúng
        # vào QUEUED + push Redis hay sẽ bị double-process hoặc lặp vô hạn.
        standard_rows = []
        skipped_dub = 0
        for run, project in rows:
            title = str(project.title or "")
            manifest = run.prompt_manifest or {}
            payload_data = run.input_payload or {}
            render_mode = manifest.get("render_mode") or payload_data.get("render_mode")
            if title.startswith("[DUB]") or render_mode == "TRANSLATE_DUB":
                print(f"  SKIP (Dubbing job — handled by process_queued_jobs.py): {run.id} [{title[:60]}]")
                skipped_dub += 1
            else:
                standard_rows.append((run, project))

        if skipped_dub:
            print(f"Skipped {skipped_dub} AI Dubbing job(s) — use process_queued_jobs.py to render them.\n")

        if not standard_rows:
            print("No RENDERING/ASSETS_READY standard workflows to reset. Nothing to do.")
            return 0

        print(f"Found {len(standard_rows)} standard workflow(s) to reset:\n")
        success = 0
        for run, project in standard_rows:
            ok = reset_one(run, project, session, client, redis_client, redis_settings.stream, args.dry_run)
            if ok:
                success += 1
            print()

    print(f"Reset {success}/{len(rows)} workflows.")
    if success > 0 and not args.dry_run:
        print("\nNext step: re-trigger visionflow-render-free.yml with passes=3")
        print("The worker will pick up the re-queued events and re-run the full pipeline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
