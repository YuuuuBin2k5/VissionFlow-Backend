"""
Advance workflows stuck in PLANNING state by calling Control Plane API directly.

Used when: worker claimed PLANNING (QUEUED→PLANNING OK) but crashed before
advancing PLANNING→SCRIPTED→STORYBOARDED.

Usage:
    python services/control-plane/scripts/advance_stuck_workflow.py --all
    python services/control-plane/scripts/advance_stuck_workflow.py \
        --workflow-run-id 1db3e73f-cd36-4355-8569-19f1528bb137

Env vars required:
    DATABASE_URL                    — PostgreSQL connection string
    VISIONFLOW_CONTROL_PLANE_URL    — Control Plane base URL
    VISIONFLOW_WORKER_CLIENT_ID     — OIDC client ID
    VISIONFLOW_WORKER_CLIENT_SECRET — OIDC client secret
    VISIONFLOW_AUTH_AUDIENCE        — OIDC audience
    VISIONFLOW_ORGANIZATION_ID      — Organization UUID
"""

from __future__ import annotations

import argparse
import os
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import time
import uuid
from pathlib import Path

import requests

# Only needs control-plane app for DB access
SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from app.infrastructure.database import get_engine  # noqa: E402
from app.infrastructure.models import VideoProject, WorkflowRun  # noqa: E402


# ---------------------------------------------------------------------------
# Minimal Control Plane HTTP client (no worker module dependency)
# ---------------------------------------------------------------------------

class ControlPlaneClient:
    def __init__(self) -> None:
        self._base = os.environ["VISIONFLOW_CONTROL_PLANE_URL"].rstrip("/")
        self._org_id = os.environ["VISIONFLOW_ORGANIZATION_ID"]
        self._token_url = f"{self._base}/api/v1/auth/token" if "/api/v1" not in self._base else f"{self._base}/auth/token"
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

    def get_creative_document(self, workflow_run_id: str) -> dict:
        resp = requests.get(
            f"{self._base}/workflows/{workflow_run_id}/creative-document",
            params={"organization_id": self._org_id},
            headers=self._headers(),
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()

    def advance_workflow(self, workflow_run_id: str, expected_state: str, target_state: str, output_payload: dict) -> dict:
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
# Main logic
# ---------------------------------------------------------------------------

def advance_one(run: WorkflowRun, project: VideoProject, client: ControlPlaneClient, dry_run: bool) -> bool:
    print(f"  Workflow: {run.id} | Title: {project.title}")

    print(f"  Fetching creative document...")
    try:
        doc = client.get_creative_document(str(run.id))
    except Exception as e:
        print(f"  SKIP: Cannot fetch creative document: {e}")
        return False

    if doc.get("state") != "locked":
        print(f"  SKIP: Creative document state is '{doc.get('state')}', not locked")
        return False

    script_text = doc.get("script", "")
    scenes = doc.get("scenes", [])

    if not script_text or not scenes:
        print(f"  SKIP: Missing script ({len(script_text)} chars) or scenes ({len(scenes)})")
        return False

    print(f"  Creative document OK: {len(script_text)} chars script, {len(scenes)} scenes")

    # Convert scenes to worker format
    worker_scenes = []
    for i, scene in enumerate(scenes, start=1):
        worker_scenes.append({
            "scene_id": str(scene.get("id", f"scene-{i}")),
            "visual_search_keywords": scene.get("visual_prompt", f"cinematic vertical shot {i}"),
            "duration": scene.get("duration_seconds", 5),
            "narration": scene.get("narration", ""),
            "caption": scene.get("caption") or "",
            "transition": scene.get("transition", "cut"),
        })

    if dry_run:
        print(f"  DRY RUN: would advance PLANNING→SCRIPTED→STORYBOARDED")
        return True

    trace_id = uuid.uuid4().hex

    print(f"  Advancing PLANNING → SCRIPTED...")
    try:
        client.advance_workflow(
            str(run.id),
            expected_state="PLANNING",
            target_state="SCRIPTED",
            output_payload={"script": script_text, "generator": "creative-document-recovery"},
        )
        print(f"  ✓ SCRIPTED")
    except Exception as e:
        print(f"  ERROR advancing to SCRIPTED: {e}")
        return False

    print(f"  Advancing SCRIPTED → STORYBOARDED...")
    try:
        client.advance_workflow(
            str(run.id),
            expected_state="SCRIPTED",
            target_state="STORYBOARDED",
            output_payload={"scenes": worker_scenes, "scene_count": len(worker_scenes)},
        )
        print(f"  ✓ STORYBOARDED — ready for render pass")
    except Exception as e:
        print(f"  ERROR advancing to STORYBOARDED: {e}")
        return False

    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Advance PLANNING-stuck workflows to STORYBOARDED")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--workflow-run-id", help="UUID of specific workflow")
    group.add_argument("--all", action="store_true", help="Process ALL PLANNING-stuck workflows")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    client = ControlPlaneClient()

    with Session(get_engine()) as session:
        if args.all:
            rows = session.execute(
                select(WorkflowRun, VideoProject)
                .join(VideoProject, VideoProject.id == WorkflowRun.project_id)
                .where(WorkflowRun.state == "PLANNING")
            ).all()
        else:
            run_id = uuid.UUID(args.workflow_run_id)
            rows = session.execute(
                select(WorkflowRun, VideoProject)
                .join(VideoProject, VideoProject.id == WorkflowRun.project_id)
                .where(WorkflowRun.id == run_id)
            ).all()

        if not rows:
            print("No PLANNING-stuck workflows found. Nothing to do.")
            return 0

        print(f"Found {len(rows)} PLANNING-stuck workflow(s)")
        success = 0
        for run, project in rows:
            ok = advance_one(run, project, client, args.dry_run)
            if ok:
                success += 1

        print(f"\nAdvanced {success}/{len(rows)} workflows to STORYBOARDED.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
