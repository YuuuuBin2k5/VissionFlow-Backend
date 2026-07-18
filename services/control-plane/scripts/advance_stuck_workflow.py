"""
Advance a workflow that is stuck mid-planning by pushing intelligence transitions
directly via the Control Plane API.

Used when: worker claimed PLANNING (advance QUEUED→PLANNING succeeded) but
crashed before advancing PLANNING→SCRIPTED→STORYBOARDED.

Usage:
    python services/control-plane/scripts/advance_stuck_workflow.py \
        --workflow-run-id 1db3e73f-cd36-4355-8569-19f1528bb137

Env vars required (same as relay_outbox.py):
    VISIONFLOW_CONTROL_PLANE_URL
    VISIONFLOW_WORKER_CLIENT_ID
    VISIONFLOW_WORKER_CLIENT_SECRET
    VISIONFLOW_AUTH_AUDIENCE
    VISIONFLOW_ORGANIZATION_ID
    DATABASE_URL
"""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="Advance workflows stuck in mid-planning state")
    parser.add_argument("--workflow-run-id", help="UUID of a specific workflow to advance")
    parser.add_argument("--all", action="store_true", help="Advance ALL workflows stuck in PLANNING state")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen without making changes")
    args = parser.parse_args()

    if not args.workflow_run_id and not args.all:
        parser.error("Provide --workflow-run-id or --all")

    from app.infrastructure.database import get_engine
    from app.infrastructure.models import CreativeDocument, CreativeDocumentVersion, VideoProject, WorkflowRun
    from worker.services.visionflow_control_plane_client import VisionFlowControlPlaneClient, VisionFlowWorkerSettings

    control_plane = VisionFlowControlPlaneClient(VisionFlowWorkerSettings.from_env())

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
            print("No workflows in PLANNING state found.")
            return 0

        print(f"Found {len(rows)} workflow(s) in PLANNING state")

        for run, project in rows:
            print(f"\nWorkflow: {run.id} | Title: {project.title}")
            print(f"  State: {run.state}")

            # Get locked creative document
            creative_doc = session.scalar(
                select(CreativeDocument).where(CreativeDocument.workflow_run_id == run.id)
            )
            if creative_doc is None or creative_doc.active_version_id is None:
                print(f"  SKIP: No locked creative document found")
                continue

            locked_version = session.get(CreativeDocumentVersion, creative_doc.active_version_id)
            if locked_version is None or locked_version.state != "locked":
                print(f"  SKIP: Creative document not locked")
                continue

            script = locked_version.scenes_payload.get("script") if hasattr(locked_version, "scenes_payload") else None

            # Try to get script and scenes from the locked version directly
            # The creative document version stores the content differently
            # Let's fetch from Control Plane API instead
            print(f"  Fetching creative document from Control Plane...")
            try:
                doc = control_plane.get_creative_document(str(run.id))
            except Exception as e:
                print(f"  ERROR fetching creative document: {e}")
                continue

            script_text = doc.get("script", "")
            scenes = doc.get("scenes", [])

            if not script_text or not scenes:
                print(f"  SKIP: Creative document missing script or scenes")
                print(f"    script len: {len(script_text)}, scenes count: {len(scenes)}")
                continue

            print(f"  Creative document OK: script {len(script_text)} chars, {len(scenes)} scenes")

            # Convert scenes to worker format
            worker_scenes = []
            for i, scene in enumerate(scenes, start=1):
                worker_scenes.append({
                    "scene_id": str(scene.get("id", f"scene-{i}")),
                    "visual_search_keywords": scene.get("visual_prompt", f"scene {i} vertical"),
                    "duration": scene.get("duration_seconds", 5),
                    "narration": scene.get("narration", ""),
                    "caption": scene.get("caption", ""),
                    "transition": scene.get("transition", "cut"),
                })

            if args.dry_run:
                print(f"  DRY RUN: would advance PLANNING→SCRIPTED→STORYBOARDED")
                print(f"    Script preview: {script_text[:80]}...")
                print(f"    Scenes: {len(worker_scenes)}")
                continue

            trace_id = uuid.uuid4().hex

            # Advance PLANNING → SCRIPTED
            print(f"  Advancing PLANNING → SCRIPTED...")
            try:
                control_plane.advance_workflow(
                    str(run.id),
                    expected_state="PLANNING",
                    target_state="SCRIPTED",
                    output_payload={"script": script_text, "generator": "creative-document-recovery"},
                    trace_id=trace_id,
                )
                print(f"  ✓ SCRIPTED")
            except Exception as e:
                print(f"  ERROR advancing to SCRIPTED: {e}")
                continue

            # Advance SCRIPTED → STORYBOARDED
            print(f"  Advancing SCRIPTED → STORYBOARDED...")
            try:
                control_plane.advance_workflow(
                    str(run.id),
                    expected_state="SCRIPTED",
                    target_state="STORYBOARDED",
                    output_payload={"scenes": worker_scenes, "scene_count": len(worker_scenes)},
                    trace_id=trace_id,
                )
                print(f"  ✓ STORYBOARDED")
            except Exception as e:
                print(f"  ERROR advancing to STORYBOARDED: {e}")
                continue

            print(f"  ✓ Workflow now at STORYBOARDED — ready for render pass")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
