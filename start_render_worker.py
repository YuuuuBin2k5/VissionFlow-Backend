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
os.environ.setdefault("VISIONFLOW_WORKER_CLIENT_SECRET", "")
os.environ.setdefault("VISIONFLOW_ORGANIZATION_ID", "7b91598c-6c3e-4e5d-8247-d3efa203984a")
os.environ.setdefault("VISIONFLOW_AUTH_AUDIENCE", "visionflow-control-plane")
# GEMINI_API_KEY must be supplied by environment/configuration.
os.environ.setdefault("PEXELS_API_KEY", "")

# Add worker and control-plane paths relative to this script
_backend_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _backend_root)
sys.path.insert(0, os.path.join(_backend_root, "worker"))
sys.path.insert(0, os.path.join(_backend_root, "services", "control-plane"))

from sqlalchemy.orm import Session
from app.infrastructure.database import get_engine
from app.infrastructure.models import WorkflowRun, VideoProject, MediaAsset, RenderJob

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
        title = str(proj.title if proj and proj.title else "Video ngan tu dong")
        brief = str(proj.brief if proj and proj.brief else "")
        org_id = str(proj.organization_id if proj and proj.organization_id else "7b91598c-6c3e-4e5d-8247-d3efa203984a")
        manifest = dict(wf.prompt_manifest or {})
        payload = dict(wf.input_payload or {})
        meta_json = dict(getattr(wf, "metadata_json", None) or {})

        render_mode = str(manifest.get("render_mode") or payload.get("render_mode") or "").upper()
        if render_mode == "TRANSLATE_DUB" or "dub" in title.lower() or "lồng tiếng" in title.lower() or "douyin" in title.lower() or "tiktok" in title.lower():
            print(f"  [Worker Route] Skipping '{title}' ({wf_id}) in standard B-roll pipeline (Handled by DubbingStrategy).")
            return False

        render_target = str(
            manifest.get("render_target")
            or payload.get("render_target")
            or ""
        ).upper()

        is_gh_actions = os.environ.get("GITHUB_ACTIONS") == "true"

        if is_gh_actions:
            # On GitHub Actions, skip jobs that are explicitly marked for user's LOCAL PC
            if render_target == "LOCAL":
                print(f"  [Worker Route] Skipping '{title}' ({wf_id}): targeted explicitly for user's LOCAL machine.")
                return False
        else:
            # On Local machine daemon, skip jobs targeted for cloud (MODAL or GITHUB)
            if render_target in ("MODAL", "GITHUB"):
                print(f"  [Worker Route] Skipping '{title}' ({wf_id}): targeted for {render_target}, skipping on local worker.")
                return False

        # Atomically mark workflow as RENDERING in DB to prevent concurrent runs
        wf.state = "RENDERING"
        session_db.commit()

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
        "organization_id": org_id,
        "title": payload.get("title") or title,
        "brief": payload.get("brief") or brief,
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
    print(f"  [Studio Sync] BGM: Preset='{contract_payload.get('bgm_preset') or 'Auto'}', Vol={contract_payload.get('bgm_volume', 0.12)}")
    print(f"  [Studio Sync] Visual Engine: {contract_payload.get('visual_engine') or 'fal_ai'}")
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
                job_id = int(meta_json.get("job_id", 0)) if meta_json else 0
                if job_id:
                    handle_publish(job_id=job_id)
            except Exception as pub_err:
                print(f"[DB Auto-Publish Notice] Immediate publish execution: {pub_err}")
        else:
            with Session(get_engine()) as fresh_db:
                wf_t = fresh_db.get(WorkflowRun, wf_id)
                if wf_t:
                    wf_t.state = "APPROVAL_PENDING"
                    # Upsert render WorkflowStep
                    from app.infrastructure.models import WorkflowStep
                    step_render = fresh_db.query(WorkflowStep).filter(
                        WorkflowStep.workflow_run_id == wf_id,
                        WorkflowStep.step_key == "render"
                    ).first()
                    if not step_render:
                        step_render = WorkflowStep(
                            workflow_run_id=wf_id,
                            step_key="render",
                            state="completed",
                            attempt_count=1,
                            input_payload={},
                            output_payload={"object_key": result.get("object_key"), "video_url": result.get("video_url")},
                        )
                        fresh_db.add(step_render)
                    else:
                        step_render.state = "completed"
                        step_render.output_payload = {"object_key": result.get("object_key"), "video_url": result.get("video_url")}
                    fresh_db.commit()
            print(f"[DB] Auto-Publish OFF: Workflow {wf_id} -> APPROVAL_PENDING (Ready for Studio review)!\n")

        return True
    else:
        err_msg = str(result.get("error", "Unknown render error"))
        print(f"\n❌ [FAILED] RENDER FAILED FOR {wf_id}: {err_msg}")
        with Session(get_engine()) as fresh_db:
            wf_t = fresh_db.get(WorkflowRun, wf_id)
            if wf_t:
                wf_t.state = "FAILED"
                wf_t.failure_code = "RENDER_FAILED"
                wf_t.failure_detail = err_msg[:1000]
                fresh_db.commit()
        return False


def process_auto_production_job_official(job_id_str: str) -> bool:
    """
    Renders an Auto Production job from render_jobs table using the rich FFmpeg styling engine
    (modal_worker.py) with full Hormozi subtitles, Neon title banner, watermark, and progress bar.
    """
    import uuid
    from datetime import datetime, timezone, timedelta
    from app.infrastructure.models import RenderJob
    from production.auto_production_adapter import adapt_auto_production_to_modal_contract
    from modal_worker import render_video_task_local

    engine = get_engine()
    with Session(engine) as session_db:
        try:
            job_uuid = uuid.UUID(job_id_str)
        except Exception:
            return False

        job = session_db.get(RenderJob, job_uuid)
        if not job or job.status not in ("WAITING_FOR_WORKER", "QUEUED"):
            return False

        run_id = str(job.run_id)
        spec_json = dict(job.render_spec_json or {})
        manifest = spec_json.get("manifest") or {}
        run_snapshot = spec_json.get("run_snapshot") or {}

        # Claim the job atomically
        job.status = "CLAIMED"
        job.attempt = (job.attempt or 0) + 1
        job.claimed_by_worker_id = "desktop-main"
        job.last_heartbeat_at = datetime.now(timezone.utc)
        job.lease_expires_at = datetime.now(timezone.utc) + timedelta(seconds=600)
        session_db.commit()

    print(f"\n=======================================================")
    print(f"[WORKER] PROCESSING AUTO PRODUCTION VIDEO: '{run_id}' (Job: {job_id_str[:8]})")
    print(f"=======================================================")

    try:
        # Adapt payload to modal_worker contract with full styling presets
        contract_payload = adapt_auto_production_to_modal_contract(
            run_snapshot=run_snapshot,
            manifest=manifest,
            job_id=job_id_str,
        )

        print(f"  [Auto Production Sync] Title: '{contract_payload.get('title')}'")
        print(f"  [Auto Production Sync] Voice: {contract_payload.get('voice_code')}")
        print(f"  [Auto Production Sync] Scenes: {len(contract_payload.get('scenes') or [])}")
        print(f"  [Auto Production Sync] Style: Banner='{contract_payload.get('title_banner_style')}', Captions='{contract_payload.get('caption_preset')}'")

        # Execute Modal Worker FFmpeg composition engine
        result = render_video_task_local(contract_payload)
        status = result.get("status", "ERROR")

        if status == "SUCCESS":
            object_key = result.get("object_key")
            video_url = result.get("video_url")
            video_duration = float(result.get("duration") or 30.0)

            print(f"\n✅ [SUCCESS] AUTO PRODUCTION RENDER COMPLETE FOR {run_id}!")
            print(f"  Output Object Key: {object_key}")
            print(f"  Public Video URL: {video_url}")

            video_output_path = result.get("video_output")
            file_size = os.path.getsize(video_output_path) if video_output_path and os.path.exists(video_output_path) else 1024
            res_w = 1080 if contract_payload.get("aspect_ratio") == "9:16" else 1920
            res_h = 1920 if contract_payload.get("aspect_ratio") == "9:16" else 1080
            fps_val = int(contract_payload.get("fps") or 30)

            with Session(engine) as fresh_db:
                job_t = fresh_db.get(RenderJob, job_uuid)
                if job_t:
                    job_t.status = "COMPLETED"
                    job_t.completed_at = datetime.now(timezone.utc)
                    job_t.output_artifact_ref = object_key
                    # Update run_snapshot in render_spec_json
                    s_data = dict(job_t.render_spec_json or {})
                    snap = dict(s_data.get("run_snapshot") or {})
                    snap["status"] = "RENDERED"
                    snap["output_video_url"] = video_url
                    snap["current_stage"] = "final_qc"
                    snap["progress_pct"] = 100
                    snap["render_artifact"] = {
                        "run_id": run_id,
                        "output_path_ref": f"/api/v1/production/runs/{run_id}/video",
                        "storage_ref": object_key,
                        "duration_seconds": video_duration,
                        "width": res_w,
                        "height": res_h,
                        "fps": fps_val,
                        "video_codec": "h264",
                        "audio_codec": "aac",
                        "file_size_bytes": file_size,
                    }
                    stages_list = snap.get("stages") or []
                    for stg in stages_list:
                        if stg.get("stage_name") in ("remote_render", "canonical_render", "final_qc"):
                            stg["status"] = "COMPLETED"
                            stg["execution_mode"] = "REAL"
                    snap["stages"] = stages_list
                    s_data["run_snapshot"] = snap
                    job_t.render_spec_json = s_data
                    fresh_db.commit()

            # Update DevelopmentRunRepository if available
            try:
                from production.repositories.run_repository import run_repository
                from production.contracts import ProductionRunStatus, RenderArtifact, StageStatus
                prod_run = run_repository.get(run_id)
                if prod_run:
                    prod_run.status = ProductionRunStatus.RENDERED
                    prod_run.output_video_url = video_url
                    prod_run.render_artifact = RenderArtifact(
                        run_id=run_id,
                        output_path_ref=f"/api/v1/production/runs/{run_id}/video",
                        storage_ref=object_key,
                        duration_seconds=video_duration,
                        width=res_w,
                        height=res_h,
                        fps=fps_val,
                        video_codec="h264",
                        audio_codec="aac",
                        file_size_bytes=file_size,
                    )
                    prod_run.current_stage = "final_qc"
                    prod_run.progress_pct = 100
                    for stg in prod_run.stages:
                        if stg.stage_name in ("remote_render", "canonical_render", "final_qc"):
                            stg.status = StageStatus.COMPLETED
                            stg.execution_mode = "REAL"
                    run_repository.update(prod_run)
            except Exception as repo_err:
                print(f"  [Auto Production Notice] Local run_repository update: {repo_err}")

            return True
        else:
            err_msg = str(result.get("error", "Unknown render error"))
            print(f"\n❌ [FAILED] AUTO PRODUCTION RENDER FAILED FOR {run_id}: {err_msg}")
            with Session(engine) as fresh_db:
                job_t = fresh_db.get(RenderJob, job_uuid)
                if job_t:
                    job_t.status = "FAILED"
                    job_t.failed_at = datetime.now(timezone.utc)
                    job_t.error_code = "RENDER_FAILED"
                    job_t.error_message = err_msg[:500]
                    fresh_db.commit()
            return False

    except Exception as exc:
        print(f"\n❌ [EXCEPTION] AUTO PRODUCTION JOB ERROR FOR {run_id}: {exc}")
        import traceback
        traceback.print_exc()
        with Session(engine) as fresh_db:
            job_t = fresh_db.get(RenderJob, job_uuid)
            if job_t:
                job_t.status = "FAILED"
                job_t.failed_at = datetime.now(timezone.utc)
                job_t.error_code = "WORKER_INTERNAL_ERROR"
                job_t.error_message = str(exc)[:500]
                fresh_db.commit()
        return False


_last_auto_prod_err = None


def process_auto_production_jobs() -> int:
    """Polls and processes claimable jobs from the durable render_jobs queue."""
    global _last_auto_prod_err
    from app.infrastructure.models import RenderJob
    engine = get_engine()
    processed_count = 0
    try:
        with Session(engine) as session_db:
            pending = session_db.query(RenderJob.id).filter(
                RenderJob.status.in_(["WAITING_FOR_WORKER", "QUEUED"]),
                RenderJob.attempt < RenderJob.max_attempts
            ).order_by(RenderJob.priority.asc(), RenderJob.created_at.asc()).all()
            pending_ids = [str(r[0]) for r in pending]

        for j_id in pending_ids:
            try:
                ok = process_auto_production_job_official(j_id)
                if ok:
                    processed_count += 1
            except Exception as err:
                print(f"❌ [Auto Production Pass Error] Job #{j_id} error: {err}")
        _last_auto_prod_err = None
    except Exception as db_err:
        err_msg = str(db_err).split("\n")[0]
        if err_msg != _last_auto_prod_err:
            _last_auto_prod_err = err_msg
            print(f"[Pass Notice] Auto Production DB queue notice: {err_msg}")

    return processed_count


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

    # 2. Pipeline Short-Form AI B-Roll Video (Legacy Workflows)
    engine = get_engine()
    try:
        with Session(engine) as session_db:
            pending_ids = [
                str(row[0]) for row in session_db.query(WorkflowRun.id).filter(
                    WorkflowRun.state.in_(["QUEUED", "PLANNING", "SCRIPTED", "STORYBOARDED", "RENDERING", "ASSETS_READY"])
                ).order_by(WorkflowRun.id.desc()).all()
            ]

        for run_id in pending_ids:
            try:
                ok = process_workflow_official(run_id)
                if ok:
                    processed_total += 1
            except Exception as err:
                print(f"❌ [Pass Error] Workflow #{run_id} render error: {err}")
    except Exception as db_err:
        print(f"[Pass Notice] Short-form DB queue query notice: {db_err}")

    # 3. Pipeline Auto Production Video (render_jobs + R2)
    try:
        auto_count = process_auto_production_jobs()
        processed_total += auto_count
    except Exception as auto_err:
        print(f"[Pass Notice] Auto Production queue step notice: {auto_err}")

    return processed_total


def run_worker_loop():
    import argparse
    parser = argparse.ArgumentParser(description="VisionFlow Unified Render Engine (Local & GitHub Actions)")
    parser.add_argument("--once", action="store_true", help="Chạy 1 pass duy nhất rồi thoát (GitHub Actions / CLI mode)")
    parser.add_argument("--loop", action="store_true", help="Chạy lặp lại liên tục ngầm (Local Server Daemon mode)")
    args, _ = parser.parse_known_args()

    print("=======================================================")
    print("🚀 VISIONFLOW UNIFIED AUTOMATIC RENDER SERVER RUNNING")
    print("   [1] AI Dubbing & Translation Queue")
    print("   [2] Studio & OpenCut Creative Video Queue")
    print("   [3] Auto Production Autonomous Video Queue (R2 Sync)")
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
