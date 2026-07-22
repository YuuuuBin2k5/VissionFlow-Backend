"""
Manual re-queue script: push QUEUED state_changed events to Redis
for workflows that are stuck (event was already acked but processing failed).

Usage:
    # Re-queue a specific workflow
    python services/control-plane/scripts/requeue_workflow.py \
        --workflow-run-id 1db3e73f-cd36-4355-8569-19f1528bb137

    # Auto re-queue ALL workflows currently stuck in QUEUED state
    python services/control-plane/scripts/requeue_workflow.py --all

Env vars required:
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
from app.infrastructure.models import VideoProject, WorkflowRun  # noqa: E402
from app.infrastructure.redis_stream_publisher import RedisStreamSettings  # noqa: E402


def requeue_one(run: WorkflowRun, project: VideoProject, redis_client: Redis, stream: str, dry_run: bool) -> bool:
    """Push one QUEUED or STORYBOARDED workflow event back into Redis. Returns True on success."""
    if not project.brief or not str(project.brief).strip():
        print(f"  SKIP {run.id}: brief is empty")
        return False

    is_storyboarded = (run.state == "STORYBOARDED")
    event_id = uuid.uuid4()
    payload = {
        "workflow_run_id": str(run.id),
        "organization_id": str(project.organization_id),
        "from_state": "SCRIPTED" if is_storyboarded else "READY",
        "to_state": "STORYBOARDED" if is_storyboarded else "QUEUED",
        "step_key": "storyboard" if is_storyboarded else "queue",
        "intake": {
            "title": project.title,
            "brief": project.brief,
            "format_profile": project.format_profile,
            "timezone": project.timezone,
            "input_payload": run.input_payload,
            "prompt_manifest": run.prompt_manifest,
        },
    }

    fields = {
        "event_id": str(event_id),
        "event_type": "visionflow.workflow_run.state_changed.v1",
        "aggregate_type": "workflow_run",
        "aggregate_id": str(run.id),
        "trace_id": uuid.uuid4().hex,
        "payload": json.dumps(payload, separators=(",", ":"), sort_keys=True),
    }

    if dry_run:
        print(f"  DRY RUN: would push event for {run.id} [{run.state}] ({project.title[:50]})")
        return True

    msg_id = redis_client.xadd(stream, fields)
    print(f"  OK: pushed {run.id} [{run.state}] ({project.title[:50]}) -> Redis msg {msg_id}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Re-queue stuck QUEUED/STORYBOARDED workflows into Redis stream")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--workflow-run-id", help="UUID of a specific WorkflowRun to re-queue")
    group.add_argument("--all", action="store_true", help="Re-queue ALL workflows currently in QUEUED or STORYBOARDED state")
    parser.add_argument("--dry-run", action="store_true", help="Print payload without pushing to Redis")
    args = parser.parse_args()

    redis_settings = RedisStreamSettings.from_env()
    redis_client = Redis.from_url(redis_settings.url, decode_responses=True) if not args.dry_run else None

    with Session(get_engine()) as session:
        if args.all:
            # Find all workflows stuck in QUEUED or STORYBOARDED
            rows = session.execute(
                select(WorkflowRun, VideoProject)
                .join(VideoProject, VideoProject.id == WorkflowRun.project_id)
                .where(WorkflowRun.state.in_(["QUEUED", "STORYBOARDED"]))
            ).all()

            if not rows:
                print("No workflows in QUEUED or STORYBOARDED state. Nothing to do.")
                return 0

            print(f"Found {len(rows)} QUEUED workflow(s) to re-queue:")
            success = 0
            for run, project in rows:
                ok = requeue_one(run, project, redis_client, redis_settings.stream, args.dry_run)
                if ok:
                    success += 1

            print(f"\nRe-queued {success}/{len(rows)} workflows.")
            if success > 0 and not args.dry_run:
                print("Now run consume_visionflow_events.py --once to process them.")
        else:
            # Single workflow
            workflow_run_id = uuid.UUID(args.workflow_run_id)
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

            print(f"WorkflowRun: {run.id} | State: {run.state} | Title: {project.title}")

            if run.state not in ("QUEUED", "STORYBOARDED"):
                print(f"ERROR: Workflow is '{run.state}', not QUEUED or STORYBOARDED. Aborting.")
                return 1

            ok = requeue_one(run, project, redis_client, redis_settings.stream, args.dry_run)
            return 0 if ok else 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
