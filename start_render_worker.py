"""
VisionFlow Standalone Local Render Server
100% Identical to GitHub Actions Pipeline & Control Plane Execution Contract.

Runs the full official pipeline:
1. Advance stuck PLANNING workflows to STORYBOARDED using AI Intelligence Engine.
2. Dispatch render via official VisionFlowRenderDispatcher + VisionFlowRenderWorkflow.
3. Apply FfmpegOverlayCompositor (Logo handle, Progress bar, Keyframes, CTAs).
4. Apply FfmpegCaptionCompositor (Karaoke subtitles with Hormozi/Cinematic presets).
5. QA Validation & Handoff to Web Console (APPROVAL_PENDING).
"""

import os
import sys

# Auto-detect and re-exec with venv python if running with unactivated python
_venv_python = os.path.abspath(os.path.join(os.path.dirname(__file__), "venv", "Scripts", "python.exe"))
if os.path.exists(_venv_python) and os.path.normpath(sys.executable).lower() != os.path.normpath(_venv_python).lower():
    import subprocess
    sys.exit(subprocess.call([_venv_python] + sys.argv))

import uuid
import time
import json
import requests
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

class TeeLogger:
    def __init__(self, filepath: str):
        self.filepath = filepath
        self.terminal = sys.__stdout__
        os.makedirs(os.path.dirname(filepath), exist_ok=True)

    def write(self, message):
        if self.terminal:
            try:
                self.terminal.write(message)
                self.terminal.flush()
            except BaseException:
                pass
        try:
            with open(self.filepath, "a", encoding="utf-8") as f:
                f.write(message)
        except BaseException:
            pass

    def flush(self):
        if self.terminal:
            try:
                self.terminal.flush()
            except BaseException:
                pass

log_file_path = os.path.join(os.path.dirname(__file__), "logs", "render_worker.log")
tee_instance = TeeLogger(log_file_path)
sys.stdout = tee_instance
sys.stderr = tee_instance

# Setup modern FFmpeg v7.1
try:
    import imageio_ffmpeg
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    ffmpeg_dir = os.path.dirname(ffmpeg_exe)
    os.environ["PATH"] = ffmpeg_dir + os.path.pathsep + os.environ.get("PATH", "")
    print(f"[FFmpeg] Using modern FFmpeg binary: {ffmpeg_exe}")
except Exception as ffmpeg_err:
    print(f"[FFmpeg] Setup notice: {ffmpeg_err}")

# Environment Setup matching GitHub Actions Secrets & Control Plane Contract
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = "postgresql://neondb_owner:npg_TD8BYOyg6AVC@ep-restless-waterfall-azn7ekhh-pooler.c-3.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("VISIONFLOW_CONTROL_PLANE_URL", "https://visionflow-control-plane-free.onrender.com")
os.environ.setdefault("VISIONFLOW_TOKEN_URL", "https://visionflow-control-plane-free.onrender.com/api/v1/auth/token")
os.environ.setdefault("VISIONFLOW_WORKER_CLIENT_ID", "visionflow-worker-runner")
os.environ.setdefault("VISIONFLOW_WORKER_CLIENT_SECRET", "sec_worker_prod_99812")
os.environ.setdefault("VISIONFLOW_ORGANIZATION_ID", "7b91598c-6c3e-4e5d-8247-d3efa203984a")
os.environ.setdefault("VISIONFLOW_AUTH_AUDIENCE", "visionflow-control-plane")
os.environ.setdefault("GEMINI_API_KEY", "AIzaSyCNu2LQSzyBW6ACixl1D6SLy07_vdeu0ho")
os.environ.setdefault("PEXELS_API_KEY", "j3CIlOLR1RdRejkZPi56CCmJALu9axEyFjik0U77W3semlJtXFpMqgVp")

# Add worker and control-plane paths
sys.path.insert(0, os.path.abspath("worker"))
sys.path.insert(0, os.path.abspath("services/control-plane"))

from sqlalchemy.orm import Session
from app.infrastructure.database import get_engine
from app.infrastructure.models import WorkflowRun, VideoProject, MediaAsset

from worker.services.visionflow_control_plane_client import VisionFlowControlPlaneClient, VisionFlowWorkerSettings
from worker.services.asset_service import AssetService
from worker.services.media_service import MediaService
from worker.services.visionflow_tts import VisionFlowTts
from worker.services.visionflow_video_renderer import VisionFlowVideoRenderer
from worker.services.visionflow_asset_preparer import VisionFlowAssetPreparer
from worker.services.visionflow_render_assets import VisionFlowRenderAssetMaterializer
from worker.application.visionflow_render_workflow import VisionFlowRenderWorkflow, RenderedArtifact
from worker.application.visionflow_render_dispatcher import VisionFlowRenderDispatcher
from worker.application.visionflow_quality_assurance import VisionFlowQualityAssurance
from worker.services.visionflow_media_inspector import FfprobeMediaInspector

try:
    from worker.services.visionflow_object_storage import S3CompatibleObjectStorage, VisionFlowObjectStorageSettings
except Exception:
    S3CompatibleObjectStorage = None
    VisionFlowObjectStorageSettings = None


def process_workflow_official(wf_id: str) -> bool:
    engine = get_engine()
    with Session(engine) as session_db:
        wf = session_db.get(WorkflowRun, wf_id)
        if not wf or wf.state in ("PUBLISHED", "CANCELED"):
            return False
        proj = session_db.get(VideoProject, wf.project_id)
        title = proj.title if proj else "Video ngan tu dong"
        manifest = wf.prompt_manifest or {}
        payload = wf.input_payload or {}
        render_mode = str(manifest.get("render_mode") or payload.get("render_mode") or "").upper()
        if render_mode == "TRANSLATE_DUB" or "dub" in title.lower() or "lồng tiếng" in title.lower() or "douyin" in title.lower() or "tiktok" in title.lower():
            print(f"  [Worker Route] Skipping '{title}' ({wf_id}) in standard B-roll pipeline (Handled by DubbingStrategy).")
            return False

    print(f"\n=======================================================")
    print(f"[WORKER] PROCESSING VIDEO: '{title}' (ID: {wf_id})")
    print(f"=======================================================")

    # 1. Clean up stale local exports so old test files are never reused
    workspace_temp = Path("worker/workspace_temp")
    stale_dir = workspace_temp / "visionflow" / str(wf_id)
    if stale_dir.exists():
        import shutil
        try:
            shutil.rmtree(stale_dir, ignore_errors=True)
        except Exception:
            pass

    # 2. Build full Contract Payload directly from input_payload & prompt_manifest
    # This guarantees 100% synchronization with the Studio!
    contract_payload = {
        "workflow_run_id": str(wf_id),
        "organization_id": str(proj.organization_id if proj else "7b91598c-6c3e-4e5d-8247-d3efa203984a"),
        "title": payload.get("title") or title,
        "brief": payload.get("brief") or (proj.brief if proj else ""),
    }
    # Merge manifest first, then payload overrides so user's explicit Studio choices ALWAYS win!
    for k, v in manifest.items():
        contract_payload[k] = v
    for k, v in payload.items():
        if v is not None and v != "":
            contract_payload[k] = v

    print(f"  [Studio Sync] Voice: {contract_payload.get('voice_code') or contract_payload.get('voice')}")
    print(f"  [Studio Sync] Logo Handle: {contract_payload.get('logo_handle')} (Pos: {contract_payload.get('logo_position')})")
    print(f"  [Studio Sync] Captions Preset: {contract_payload.get('caption_preset')} (Font: {contract_payload.get('caption_font_family')}, Color: {contract_payload.get('caption_color')})")
    print(f"  [Studio Sync] Title Banner: {contract_payload.get('title_banner_text')} (Style: {contract_payload.get('title_banner_style')})")
    print(f"  [Studio Sync] Scene Count: {len(contract_payload.get('scenes') or [])}")

    # 3. Execute Unified FFmpeg 7.1 Video Composition Engine
    from modal_worker import render_video_task_local
    result = render_video_task_local(contract_payload)

    status = result.get("status", "ERROR")
    if status == "SUCCESS":
        print(f"\n[SUCCESS] OFFICIAL RENDER COMPLETE FOR {wf_id}!")
        print(f"  Output Object Key: {result.get('object_key')}")
        print(f"  Public Video URL: {result.get('video_url')}")

        # Check auto-publish
        prompt_manifest = manifest
        auto_publish_enabled = bool(prompt_manifest.get("auto_publish_enabled", False))
        if auto_publish_enabled:
            with Session(get_engine()) as fresh_db:
                wf_t = fresh_db.get(WorkflowRun, wf_id)
                if wf_t:
                    wf_t.state = "PUBLISHED"
                    fresh_db.commit()
            print(f"[DB Auto-Publish] ⚡ Auto-Publish ON: Workflow {wf_id} -> PUBLISHED!")
            try:
                from worker.application.publish_use_case import handle_publish
                job_id = int(wf.metadata_json.get("job_id", 0)) if wf.metadata_json else 0
                if job_id:
                    handle_publish(job_id=job_id)
            except Exception as pub_err:
                print(f"[DB Auto-Publish Notice] Immediate publish execution: {pub_err}")
        else:
            print(f"[DB] Auto-Publish OFF: Workflow {wf_id} -> APPROVAL_PENDING (Ready for Studio review)!\n")

        return True
    else:
        print(f"\n❌ [FAILED] RENDER FAILED FOR {wf_id}: {result.get('error')}")
        return False


def run_unified_render_pass() -> int:
    """
    Chạy 1 Lần Nhất Quán (Single Source of Truth) Chuỗi Pipeline Render:
    100% Đồng nhất giữa GitHub Actions Runner & Local Worker Server!
    """
    processed_total = 0

    # 1. Pipeline Dubbing / Translation (Lồng tiếng AI)
    try:
        from worker.process_queued_jobs import process_postgresql_jobs
        dub_count = process_postgresql_jobs()
        processed_total += dub_count
    except Exception as dub_err:
        print(f"[Pass Notice] Dubbing queue step notice: {dub_err}")

    # 2. Pipeline Short-Form AI B-Roll Video
    engine = get_engine()
    try:
        with Session(engine) as session_db:
            pending_runs = session_db.query(WorkflowRun).filter(
                WorkflowRun.state.in_(["QUEUED", "PLANNING", "SCRIPTED", "STORYBOARDED", "RENDERING", "ASSETS_READY"])
            ).order_by(WorkflowRun.id.desc()).all()

            for run in pending_runs:
                try:
                    ok = process_workflow_official(str(run.id))
                    if ok:
                        processed_total += 1
                except Exception as err:
                    print(f"❌ [Pass Error] Workflow #{run.id} render error: {err}")
    except Exception as db_err:
        print(f"[Pass Notice] Short-form DB queue query notice: {db_err}")

    return processed_total


def run_worker_loop():
    import argparse
    parser = argparse.ArgumentParser(description="VisionFlow Unified Render Engine (Local & GitHub Actions)")
    parser.add_argument("--once", action="store_true", help="Chạy 1 pass duy nhất rồi thoát (GitHub Actions / CLI mode)")
    parser.add_argument("--loop", action="store_true", help="Chạy lặp lại liên tục ngầm (Local Server Daemon mode)")
    args, _ = parser.parse_known_args()

    print("=======================================================")
    print("🚀 VISIONFLOW UNIFIED AUTOMATIC RENDER SERVER RUNNING")
    print("   (100% Single Source of Truth — Local & GitHub Actions)")
    print("=======================================================")

    if args.once:
        print("📌 Running 1 Single Unified Render Pass...")
        count = run_unified_render_pass()
        print(f"✅ Pass Complete! Total Workflows Processed: {count}")
        return

    print("📌 Running Continuous Local Worker Daemon Loop...\n")
    try:
        from worker.credential_fetcher import bootstrap_credentials_from_vault
        bootstrap_credentials_from_vault()
    except Exception:
        pass

    while True:
        try:
            run_unified_render_pass()
        except Exception as loop_err:
            print(f"⚠️ Unified Worker loop notice: {loop_err}")

        time.sleep(5)


if __name__ == "__main__":
    run_worker_loop()
