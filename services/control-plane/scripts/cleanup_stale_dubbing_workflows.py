"""
Cleanup script: Xóa các AI Dubbing test workflow rác trong PostgreSQL.

Các workflow này bị tạo khi unit test / test thủ công gửi request
đến /dubbing/dispatch với source_url giả (https://v.douyin.com/xyz/, my_video.mp4...).
Chúng đang chiếm STORYBOARDED / QUEUED state và làm nhiễu Control Tower UI.

Usage (từ thư mục gốc backend):
    python services/control-plane/scripts/cleanup_stale_dubbing_workflows.py --dry-run
    python services/control-plane/scripts/cleanup_stale_dubbing_workflows.py --delete

Env vars required:
    DATABASE_URL — PostgreSQL connection string
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.infrastructure.database import get_engine  # noqa: E402
from app.infrastructure.models import MediaAsset, VideoProject, WorkflowRun  # noqa: E402

# Các URL giả từ unit tests
FAKE_URLS = {
    "https://v.douyin.com/xyz/",
    "https://v.douyin.com/abc123/",
    "my_video.mp4",
    "https://www.tiktok.com/@user/video/123",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Cleanup stale AI Dubbing test workflows from PostgreSQL")
    parser.add_argument("--dry-run", action="store_true", help="List workflows without deleting")
    parser.add_argument("--delete", action="store_true", help="Actually delete stale workflows")
    parser.add_argument("--all-dub", action="store_true", help="Delete ALL [DUB] workflows (use with caution!)")
    args = parser.parse_args()

    if not args.dry_run and not args.delete:
        print("Please specify --dry-run or --delete")
        return 1

    with Session(get_engine()) as session:
        rows = session.execute(
            select(WorkflowRun, VideoProject)
            .join(VideoProject, VideoProject.id == WorkflowRun.project_id)
            .where(WorkflowRun.state.in_(["QUEUED", "PLANNING", "SCRIPTED", "STORYBOARDED", "RENDERING"]))
        ).all()

        stale = []
        for run, proj in rows:
            title = str(proj.title or "")
            manifest = run.prompt_manifest or {}
            payload = run.input_payload or {}
            source_url = manifest.get("dub_source_url") or payload.get("dub_source_url") or ""
            source_path = manifest.get("dub_source_path") or payload.get("dub_source_path") or ""

            is_dubbing = title.startswith("[DUB]") or manifest.get("render_mode") == "TRANSLATE_DUB" or payload.get("render_mode") == "TRANSLATE_DUB"

            if not is_dubbing:
                continue

            is_fake = (
                args.all_dub
                or source_url in FAKE_URLS
                or source_path in FAKE_URLS
                or (source_url and "xyz" in source_url)
                or (source_url and "abc123" in source_url)
                or source_path == "my_video.mp4"
                or (source_url and "@user/video/123" in source_url)
            )

            if is_fake:
                stale.append((run, proj))

        if not stale:
            print("No stale dubbing workflows found.")
            return 0

        print(f"Found {len(stale)} stale dubbing workflow(s):")
        for run, proj in stale:
            title = str(proj.title or "")[:70]
            manifest = run.prompt_manifest or {}
            payload = run.input_payload or {}
            src = manifest.get("dub_source_url") or payload.get("dub_source_url") or manifest.get("dub_source_path") or payload.get("dub_source_path") or "?"
            print(f"  [{run.state}] {run.id} | {title} | src={src}")

        if args.dry_run:
            print("\n[DRY RUN] No changes made. Re-run with --delete to actually remove them.")
            return 0

        # Delete MediaAssets + WorkflowRuns + VideoProjects
        deleted_wf = 0
        deleted_proj = 0
        for run, proj in stale:
            # Delete MediaAssets linked to workflow_run
            session.execute(
                delete(MediaAsset).where(MediaAsset.workflow_run_id == run.id)
            )
            session.delete(run)
            deleted_wf += 1
            # Delete VideoProject if it has no other WorkflowRuns
            remaining = session.scalars(
                select(WorkflowRun).where(WorkflowRun.project_id == proj.id).limit(1)
            ).first()
            if not remaining:
                session.delete(proj)
                deleted_proj += 1

        session.commit()
        print(f"\nDeleted {deleted_wf} WorkflowRun(s) and {deleted_proj} VideoProject(s).")
        return 0


if __name__ == "__main__":
    sys.exit(main())
