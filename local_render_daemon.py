"""
VisionFlow Local Render Engine & 24/7 Autonomous Daemon
Continuously listens for QUEUED workflow runs from Neon PostgreSQL database,
executes the full video composition pipeline (FFmpeg 7.1 + Edge TTS + BGM Auto-Ducking + SFX + ASS Captions),
uploads final 1080x1920 60fps MP4 & 3D Cover to Cloudflare R2, and transitions workflow run to APPROVAL_PENDING.
"""

import os
import sys
import time
import json
import uuid
import psycopg2
import psycopg2.extras

# Setup UTF-8 Encoding
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Ensure backend root is on sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from modal_worker import render_video_task

DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://neondb_owner:npg_mHw3FfgN7DQO@ep-morning-dawn-azmmaco1-pooler.c-3.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
)

def get_db_connection():
    return psycopg2.connect(DB_URL)

def poll_and_render_one_job():
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # 1. Look for QUEUED jobs
        cur.execute("""
            SELECT id, project_id, state, input_payload, prompt_manifest, created_at
            FROM workflow_runs
            WHERE state = 'QUEUED'
            ORDER BY created_at ASC
            LIMIT 1
            FOR UPDATE SKIP LOCKED
        """)
        job = cur.fetchone()

        if not job:
            cur.close()
            conn.close()
            return False

        wf_id = str(job['id'])
        org_id = "7b91598c-6c3e-4e5d-8247-d3efa203984a"
        
        print("\n" + "=" * 70, flush=True)
        print(f"⚡ [Local Render Daemon] Picked up QUEUED job: {wf_id}", flush=True)
        print("=" * 70, flush=True)

        # Update state to PROCESSING
        cur.execute("""
            UPDATE workflow_runs
            SET state = 'PROCESSING', updated_at = NOW()
            WHERE id = %s
        """, (wf_id,))
        conn.commit()
        cur.close()
        conn.close()
        conn = None

        # Build payload by merging input_payload & prompt_manifest
        inp = job.get('input_payload') or {}
        pm = job.get('prompt_manifest') or {}
        if isinstance(inp, str):
            try:
                inp = json.loads(inp)
            except Exception:
                inp = {}
        if isinstance(pm, str):
            try:
                pm = json.loads(pm)
            except Exception:
                pm = {}

        payload = {}
        if isinstance(pm, dict):
            payload.update(pm)
        if isinstance(inp, dict):
            payload.update(inp)

        payload['workflow_run_id'] = wf_id
        payload['organization_id'] = org_id

        # 2. Execute local render task
        print(f"🎬 [Local Render Daemon] Starting FFmpeg 7.1 Composition for {wf_id}...", flush=True)
        if hasattr(render_video_task, 'local'):
            result = render_video_task.local(payload)
        else:
            result = render_video_task(payload)

        status = result.get("status", "ERROR")
        if status == "SUCCESS":
            print(f"✅ [Local Render Daemon] Successfully completed render for {wf_id}!", flush=True)
            print(f"🔗 Playable Video: {result.get('video_url', '')}", flush=True)
        else:
            print(f"❌ [Local Render Daemon] Render failed for {wf_id}: {result.get('error', 'Unknown')}", flush=True)

        return True

    except Exception as e:
        print(f"⚠️ [Local Render Daemon] Error polling/processing job: {e}", flush=True)
        if conn:
            try:
                conn.close()
            except Exception:
                pass
        return False

def run_daemon():
    print("=" * 70, flush=True)
    print("🚀 VisionFlow Autonomous Local Render Daemon Started!", flush=True)
    print("📡 Connected to Neon DB. Listening for render jobs 24/7...", flush=True)
    print("   Press Ctrl+C to stop.", flush=True)
    print("=" * 70, flush=True)

    while True:
        try:
            had_job = poll_and_render_one_job()
            if not had_job:
                time.sleep(3)
        except KeyboardInterrupt:
            print("\n🛑 Local Render Daemon stopped by user.", flush=True)
            break
        except Exception as loop_err:
            print(f"⚠️ Worker loop exception: {loop_err}", flush=True)
            time.sleep(5)

if __name__ == '__main__':
    run_daemon()
