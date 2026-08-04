import sys
import os
import asyncio
from pathlib import Path

# Make repository root importable
WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from worker.infrastructure.database import get_db_connection
from worker.application.render_use_case import handle_render


def process_all_queued_jobs() -> None:
    """Scan video_pipeline_jobs for QUEUED tasks (e.g. AI Dubbing jobs) and execute handle_render."""
    try:
        conn = get_db_connection()
    except Exception as e:
        print(f"[ProcessQueuedJobs] DB Connection skipped/unavailable: {e}")
        return

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
            print("[ProcessQueuedJobs] No QUEUED jobs found in video_pipeline_jobs.")
            return

        print(f"[ProcessQueuedJobs] Found {len(jobs)} QUEUED job(s) in video_pipeline_jobs:")
        for job in jobs:
            print(f"  - Job #{job['id']}: {job.get('video_title_idea')} (Style: {job.get('style_preset')})")

        for job in jobs:
            job_id = job["id"]
            print(f"\n[ProcessQueuedJobs] === STARTING RENDER FOR JOB #{job_id} ===")
            try:
                asyncio.run(handle_render(job_id))
                print(f"[ProcessQueuedJobs] ✅ Job #{job_id} completed successfully.")
            except Exception as err:
                print(f"[ProcessQueuedJobs Error] ❌ Job #{job_id} failed: {err}")
    except Exception as exc:
        print(f"[ProcessQueuedJobs Error] {exc}")


if __name__ == "__main__":
    process_all_queued_jobs()
