"""
Process Queued Jobs — Support both PostgreSQL (Control Plane) and MySQL (Legacy)
================================================================================
Tự động tìm kiếm các job lồng tiếng AI hoặc công việc render đang chờ trong DB
và tiến hành render tự động trên GitHub Actions runner.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))


def process_postgresql_jobs() -> int:
    """Quét PostgreSQL (Control Plane DB) tìm các WorkflowRun thuộc loại AI Dubbing cần render."""
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("[ProcessQueuedJobs] DATABASE_URL not configured.")
        return 0

    try:
        from sqlalchemy import create_engine, select
        from sqlalchemy.orm import Session
        # Import models từ control-plane
        cp_path = WORKSPACE_ROOT / "services" / "control-plane"
        if str(cp_path) not in sys.path:
            sys.path.insert(0, str(cp_path))
        from app.infrastructure.models import VideoProject, WorkflowRun
    except Exception as err:
        print(f"[ProcessQueuedJobs] SQLAlchemy/Models import error: {err}")
        return 0

    try:
        engine = create_engine(db_url)
        with Session(engine) as session:
            rows = session.execute(
                select(WorkflowRun, VideoProject)
                .join(VideoProject, VideoProject.id == WorkflowRun.project_id)
                .where(WorkflowRun.state.in_(["QUEUED", "STORYBOARDED", "RENDERING"]))
            ).all()

            dubbing_runs = []
            for wf, proj in rows:
                manifest = wf.prompt_manifest or {}
                payload = wf.input_payload or {}
                render_mode = manifest.get("render_mode") or payload.get("render_mode")
                title = proj.title or ""
                if render_mode == "TRANSLATE_DUB" or title.startswith("[DUB]") or "dub" in title.lower():
                    dubbing_runs.append((wf, proj))

            if not dubbing_runs:
                print("[ProcessQueuedJobs] No pending Dubbing workflows found in PostgreSQL.")
                return 0

            print(f"[ProcessQueuedJobs] Found {len(dubbing_runs)} pending Dubbing workflow(s) in PostgreSQL:")
            for wf, proj in dubbing_runs:
                print(f"  - WorkflowRun #{wf.id}: {proj.title} (State: {wf.state})")

            from worker.application.render_strategies.dubbing_strategy import DubbingStrategy
            from worker.domain.render_contract import RenderContract, RenderMode

            strategy = DubbingStrategy()
            processed_count = 0

            for wf, proj in dubbing_runs:
                wf_id_str = str(wf.id)
                print(f"\n[ProcessQueuedJobs] === STARTING DUBBING RENDER FOR WORKFLOW #{wf_id_str} ===")
                manifest = wf.prompt_manifest or {}
                payload = wf.input_payload or {}
                job_dict = {
                    "id": wf_id_str,
                    "video_title_idea": proj.title,
                    "scenes_layout_json": json.dumps({**payload, **manifest}),
                }
                contract = RenderContract(
                    job_id=wf_id_str,
                    render_mode=RenderMode.TRANSLATE_DUB,
                    stop_stage=None,
                )

                try:
                    output_path = asyncio.run(strategy.execute(job_dict, contract))
                    print(f"[ProcessQueuedJobs] ✅ Workflow #{wf_id_str} completed -> {output_path}")
                    processed_count += 1
                except Exception as run_err:
                    print(f"[ProcessQueuedJobs Error] ❌ Workflow #{wf_id_str} failed: {run_err}")

            return processed_count
    except Exception as exc:
        print(f"[ProcessQueuedJobs PostgreSQL Error] {exc}")
        return 0


def process_mysql_jobs() -> int:
    """Scanning legacy MySQL video_pipeline_jobs table (Fallback)."""
    try:
        from worker.infrastructure.database import get_db_connection
        from worker.application.render_use_case import handle_render
        conn = get_db_connection()
    except Exception as e:
        print(f"[ProcessQueuedJobs] MySQL Connection skipped/unavailable: {e}")
        return 0

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, style_preset, video_title_idea
                FROM video_pipeline_jobs
                WHERE pipeline_state = 'QUEUED'
                ORDER BY id ASC
                LIMIT 10
                """
            )
            jobs = cursor.fetchall()
        conn.close()

        if not jobs:
            print("[ProcessQueuedJobs] No QUEUED jobs found in MySQL video_pipeline_jobs.")
            return 0

        print(f"[ProcessQueuedJobs] Found {len(jobs)} QUEUED job(s) in MySQL:")
        processed = 0
        for job in jobs:
            job_id = job["id"]
            print(f"\n[ProcessQueuedJobs] === STARTING MYSQL RENDER FOR JOB #{job_id} ===")
            try:
                asyncio.run(handle_render(job_id))
                print(f"[ProcessQueuedJobs] ✅ MySQL Job #{job_id} completed successfully.")
                processed += 1
            except Exception as err:
                print(f"[ProcessQueuedJobs Error] ❌ MySQL Job #{job_id} failed: {err}")
        return processed
    except Exception as exc:
        print(f"[ProcessQueuedJobs MySQL Error] {exc}")
        return 0


def process_all_queued_jobs() -> None:
    print("=== Scanning for Queued Render Jobs ===")
    pg_count = process_postgresql_jobs()
    my_count = process_mysql_jobs()
    print(f"=== Completed Queued Jobs Pass (PostgreSQL: {pg_count}, MySQL: {my_count}) ===")


if __name__ == "__main__":
    process_all_queued_jobs()
