"""
Manual re-queue script: push a new QUEUED state_changed event to Redis
for a workflow that is stuck (event was already acked but processing failed).

Usage:
    python services/control-plane/scripts/requeue_workflow.py \
        --workflow-run-id 1db3e73f-cd36-4355-8569-19f1528bb137

Env vars required (same as relay_outbox.py):
    DATABASE_URL   — PostgreSQL connection string
    REDIS_URL      — Redis connection string
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.infrastructure.database import get_engine  # noqa: E402
from app.infrastructure.models import OutboxEvent, VideoProject, WorkflowRun  # noqa: E402
from app.infrastructure.redis_stream_publisher import RedisStreamSettings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Re-queue a stuck QUEUED workflow into Redis stream")
    parser.add_argument("--workflow-run-id", required=True, help="UUID of the WorkflowRun to re-queue")
    parser.add_argument("--dry-run", action="store_true", help="Print payload without pushing to Redis")
    args = parser.parse_args()

    workflow_run_id = uuid.UUID(args.workflow_run_id)

    with Session(get_engine()) as session:
        run = session.scalar(
            select(WorkflowRun)
            .join(VideoProject, VideoProject.id == WorkflowRun.project_id)
            .where(WorkflowRun.id == workflow_run_id)
        )
        if run is None:
            print(f"ERROR: WorkflowRun {workflow_run_id} not found")
            return 1

        project = session.get(VideoProject, run.project_id)
        if project is None:
            print(f"ERROR: VideoProject for workflow {workflow_run_id} not found")
            return 1

        print(f"WorkflowRun: {run.id}")
        print(f"State: {run.state}")
        print(f"Title: {project.title}")
        print(f"Brief preview: {str(project.brief)[:80]}...")

        if run.state != "QUEUED":
            print(f"WARNING: Workflow is in state '{run.state}', not QUEUED.")
            print("Only re-queue workflows that are stuck in QUEUED state.")
            if run.state in ("PLANNING", "SCRIPTED", "STORYBOARDED", "ASSETS_READY", "RENDERING"):
                print("Workflow is already being processed — do not re-queue.")
                return 1

        # Build event payload — same structure as workflow_progression_repository
        event_id = uuid.uuid4()
        payload = {
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
        }

        # Validate brief is present
        if not payload["intake"]["brief"] or not str(payload["intake"]["brief"]).strip():
            print("ERROR: Brief is empty — cannot re-queue. Check project.brief in database.")
            return 1

        fields = {
            "event_id": str(event_id),
            "event_type": "visionflow.workflow_run.state_changed.v1",
            "aggregate_type": "workflow_run",
            "aggregate_id": str(run.id),
            "trace_id": uuid.uuid4().hex,
            "payload": json.dumps(payload, separators=(",", ":"), sort_keys=True),
        }

        print("\n--- Event payload ---")
        print(json.dumps(payload, indent=2, default=str))
        print("---------------------\n")

        if args.dry_run:
            print("DRY RUN — not pushing to Redis.")
            return 0

        redis_settings = RedisStreamSettings.from_env()
        client = Redis.from_url(redis_settings.url, decode_responses=True)
        msg_id = client.xadd(redis_settings.stream, fields)
        print(f"SUCCESS: Pushed event to Redis stream '{redis_settings.stream}'")
        print(f"Message ID: {msg_id}")
        print(f"Event ID: {event_id}")
        print("\nNow run consume_visionflow_events.py --once to process it.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
