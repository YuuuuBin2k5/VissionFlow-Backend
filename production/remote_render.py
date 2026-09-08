"""Durable handoff and idempotent post-render continuation, owned by the backend."""
from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from production.artifact_storage import get_artifact_storage
from production.contracts import ProductionRun, ProductionRunStatus, RenderArtifact
from production.remote_manifest import PortableRenderManifest, sha256_file

logger = logging.getLogger(__name__)


def remote_render_enabled() -> bool:
    return (os.getenv("VISIONFLOW_RENDER_POLICY", "").upper() in {"LOCAL_ONLY", "LOCAL_PREFERRED"}
            or os.getenv("VISIONFLOW_RENDER_TARGET", "").upper() == "REMOTE_PERSONAL_WORKER")


def build_portable_manifest(spec, job_id, storage) -> PortableRenderManifest:
    """Upload every local renderer dependency; transport never inherits local paths."""
    artifacts = []
    with tempfile.TemporaryDirectory(prefix="visionflow-handoff-") as temporary:
        def upload(source, role):
            source = str(source)
            path = Path(source)
            if source.startswith(("https://", "http://")):
                # Input provider URLs are ingested here, never forwarded to workers.
                import requests
                from production.source_ingest import validate_remote_url_safety
                validate_remote_url_safety(source)
                from urllib.parse import urlsplit
                path = Path(temporary) / (uuid.uuid4().hex + Path(urlsplit(source).path).suffix)
                with requests.Session() as client:
                    client.trust_env = False
                    with client.get(source, stream=True, timeout=(15, 120), allow_redirects=False) as response:
                        if response.status_code != 200:
                            logger.error("REMOTE_RENDER_INPUT_NOT_PORTABLE: HTTP download failed for %s: status %d", source, response.status_code)
                            raise ValueError(f"REMOTE_RENDER_INPUT_NOT_PORTABLE: download failed for {source} (status {response.status_code})")
                        size = 0
                        with path.open("wb") as output:
                            for chunk in response.iter_content(1024 * 1024):
                                size += len(chunk)
                                if size > 2 * 1024**3:
                                    logger.error("REMOTE_RENDER_INPUT_NOT_PORTABLE: source %s exceeded 2GB limit", source)
                                    raise ValueError("REMOTE_RENDER_INPUT_NOT_PORTABLE: file size exceeds 2GB")
                                output.write(chunk)
            if not path.is_file() or path.stat().st_size == 0:
                logger.error("REMOTE_RENDER_INPUT_NOT_PORTABLE: file not found or empty: %s (role: %s)", path, role)
                raise ValueError(f"REMOTE_RENDER_INPUT_NOT_PORTABLE: {role} asset {path} not found or empty")
            mime = {".wav": "audio/wav", ".ass": "text/x-ssa", ".m4a": "audio/mp4"}.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0]
            digest = sha256_file(path)
            aid = f"asset_{len(artifacts)}_{digest[:12]}"
            ref = f"visionflow/production/inputs/{digest}{path.suffix.lower()}"
            item = {"artifact_id": aid, "role": "IMAGE" if role == "VIDEO" and (mime or "").startswith("image/") else role,
                    "storage_ref": ref, "checksum_sha256": digest, "size_bytes": path.stat().st_size, "mime_type": mime}
            from production.remote_manifest import PortableArtifact
            PortableArtifact.model_validate(item)
            storage.put_file(ref, path, mime)
            artifacts.append(item)
            return aid

        render_spec = {
            "duration_seconds": spec.duration_seconds, "width": spec.width, "height": spec.height, "fps": spec.fps,
            "video_sources": [{"artifact_id": upload(v["file_path"], "VIDEO"), "duration": v["duration"]} for v in spec.video_sources],
            "audio_sources": [upload(a, "TTS") for a in spec.audio_sources],
            "bgm_artifact_id": upload(spec.bgm_path, "MUSIC") if spec.bgm_path else None,
            "subtitles_artifact_id": upload(spec.subtitles_ass_path, "SUBTITLE") if spec.subtitles_ass_path else None,
            "bgm_volume": spec.bgm_volume, "subtitle_chunks": spec.subtitle_chunks,
            "branding_color": spec.branding_color, "is_graphic_fallback": spec.is_graphic_fallback,
            "enable_ken_burns": spec.enable_ken_burns,
        }
    return PortableRenderManifest(job_id=job_id, run_id=spec.run_id, render_spec=render_spec, artifacts=artifacts)


def enqueue_remote_render(run: ProductionRun, *, session=None, storage=None, spec=None):
    from app.infrastructure.database import get_engine
    from app.infrastructure.render_job_repository import get_render_job_repository
    from production.render_handoff import render_handoff
    from production.repositories.run_repository import run_repository

    storage = storage or get_artifact_storage()
    plan_type = getattr(run.editor_plan, "plan_type", None)
    if isinstance(plan_type, str):
        plan_type_val = plan_type.upper()
    elif hasattr(plan_type, "value"):
        plan_type_val = str(plan_type.value).upper()
    else:
        plan_type_val = str(plan_type).upper() if plan_type is not None else ""

    valid_final_types = {"FINAL", "FINAL_EDITOR_PLAN", "FINAL_PLAN", "COMPLETED"}
    if run.editor_plan is None or plan_type_val not in valid_final_types:
        logger.error(
            "REMOTE_RENDER_INPUT_NOT_PORTABLE: editor_plan is %s, plan_type=%r",
            "missing" if run.editor_plan is None else "present",
            plan_type,
        )
        raise ValueError("REMOTE_RENDER_INPUT_NOT_PORTABLE")
    spec = spec or render_handoff.build_spec(run.editor_plan, run.id, strict_inputs=True)
    manifest = build_portable_manifest(spec, uuid.uuid4(), storage)
    portable = manifest.persisted()
    digest_data = {k: v for k, v in portable.items() if k != "job_id"}
    input_hash = hashlib.sha256(json.dumps(digest_data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    run.status = ProductionRunStatus.WAITING_FOR_RENDER_WORKER
    run.current_stage = "remote_render"
    run.provider_execution["render"] = "REMOTE_PERSONAL_WORKER"
    snapshot = run.model_dump(mode="json")
    def persist(db):
        return get_render_job_repository(db).create_job(
            job_id=manifest.job_id, run_id=run.id, spec={"manifest": portable, "run_snapshot": snapshot},
            input_hash=input_hash, idempotency_key=f"remote:{run.id}:{input_hash[:32]}",
        )
    if session is None:
        with Session(get_engine(), expire_on_commit=False) as db:
            job = persist(db)
    else:
        job = persist(session)
    run_repository.update(run)
    return job


def load_remote_run(run_id: str, session=None) -> ProductionRun | None:
    from app.infrastructure.database import get_engine
    from app.infrastructure.models import RenderJob
    def load(db):
        job = db.scalar(select(RenderJob).where(RenderJob.run_id == run_id).order_by(RenderJob.created_at.desc()).limit(1))
        if job is None or "run_snapshot" not in job.render_spec_json:
            return None
        run = ProductionRun.model_validate(job.render_spec_json["run_snapshot"])
        states = {"WAITING_FOR_WORKER": "WAITING_FOR_RENDER_WORKER", "QUEUED": "WAITING_FOR_RENDER_WORKER",
                  "RETRYING": "WAITING_FOR_RENDER_WORKER", "CLAIMED": "DOWNLOADING_RENDER_ASSETS",
                  "DOWNLOADING": "DOWNLOADING_RENDER_ASSETS", "RENDERING": "RENDERING", "UPLOADING": "UPLOADING_RENDER",
                  "FAILED": "RENDER_FAILED"}
        if job.status in states and run.status != ProductionRunStatus.CANCELLED:
            run.status = ProductionRunStatus(states[job.status])
        if job.status == "FAILED":
            run.error_message = job.error_code
        return run
    if session is not None:
        return load(session)
    with Session(get_engine()) as db:
        return load(db)


def cancel_remote_render(run_id: str) -> None:
    from app.infrastructure.database import get_engine
    from app.infrastructure.models import RenderJob
    with Session(get_engine()) as session:
        jobs = session.scalars(select(RenderJob).where(RenderJob.run_id == run_id,
            RenderJob.status.notin_(["COMPLETED", "FAILED"])).with_for_update()).all()
        for job in jobs:
            data = dict(job.render_spec_json)
            snapshot = dict(data["run_snapshot"])
            snapshot["status"] = "CANCELLED"
            data["run_snapshot"] = snapshot
            job.render_spec_json = data
            job.status = "FAILED"
            job.retryable = False
            job.error_code = "RUN_CANCELLED"
            job.failed_at = datetime.now(timezone.utc)
            job.lease_expires_at = None
        session.commit()


def complete_remote_render(session, job, payload, storage):
    """Caller holds attempt-fenced row lock. QC and snapshot commit exactly once.

    Failed transactions are replayable; QC has no upstream/render side effects.
    Never trust worker probe values or object metadata instead of actual bytes.
    """
    from production.canonical_renderer import CanonicalFFmpegRenderer
    from production.quality_orchestrator import quality_orchestrator
    data = dict(job.render_spec_json)
    if job.status == "COMPLETED":
        old = data.get("completion", {})
        if old.get("checksum_sha256") != payload.checksum_sha256 or old.get("storage_ref") != payload.storage_ref:
            raise ValueError("OUTPUT_COMPLETION_CONFLICT")
        session.commit()
        return old
    upload = data.get("authorized_upload", {})
    if any(upload.get(key) != getattr(payload, key) for key in ("storage_ref", "checksum_sha256", "file_size_bytes")) or upload.get("attempt") != job.attempt:
        raise ValueError("OUTPUT_NOT_AUTHORIZED")
    if not storage.object_exists(payload.storage_ref):
        raise ValueError("OUTPUT_NOT_FOUND")
    metadata = storage.metadata(payload.storage_ref)
    if int(metadata.get("ContentLength", 0)) != payload.file_size_bytes:
        raise ValueError("OUTPUT_SIZE_MISMATCH")
    if metadata.get("Metadata", {}).get("sha256") != payload.checksum_sha256:
        raise ValueError("OUTPUT_CHECKSUM_MISMATCH")
    manifest = PortableRenderManifest.model_validate(data["manifest"])
    with tempfile.TemporaryDirectory(prefix="visionflow-final-qc-") as temporary:
        path = Path(temporary) / "final.mp4"
        storage.download_to(payload.storage_ref, path)
        if path.stat().st_size != payload.file_size_bytes or sha256_file(path) != payload.checksum_sha256:
            raise ValueError("OUTPUT_CHECKSUM_MISMATCH")
        probe = CanonicalFFmpegRenderer().probe(path)
        spec = manifest.render_spec
        if (not probe.has_video or not probe.has_audio or probe.file_size_bytes <= 0
                or (probe.width, probe.height, probe.fps) != (spec.width, spec.height, spec.fps)
                or abs(probe.duration_seconds - spec.duration_seconds) > .5):
            raise ValueError("OUTPUT_INVALID")
        run = ProductionRun.model_validate(data["run_snapshot"])
        run.status = ProductionRunStatus.RENDERED
        artifact = RenderArtifact(
            run_id=run.id, output_path_ref=f"/api/v1/production/runs/{run.id}/video",
            storage_ref=payload.storage_ref, checksum_sha256=payload.checksum_sha256,
            internal_file_path=str(path), duration_seconds=probe.duration_seconds,
            width=probe.width, height=probe.height, fps=probe.fps, video_codec=probe.video_codec,
            audio_codec=probe.audio_codec, file_size_bytes=probe.file_size_bytes,
        )
        run.render_artifact = artifact
        run.output_video_url = artifact.output_path_ref
        quality_orchestrator.run_post_render_qc(run, artifact, allow_auto_render=False)
        if run.status == ProductionRunStatus.READY:
            run.status = ProductionRunStatus.HUMAN_REVIEW_PENDING
        # Worker presigned PUTs remain valid until expiry. Promote verified bytes
        # to a backend-only key so late/stale PUTs cannot alter an accepted video.
        accepted_ref = f"visionflow/production/outputs/{job.id}/{payload.checksum_sha256}.mp4"
        storage.put_file(accepted_ref, path, "video/mp4")
        artifact.storage_ref = accepted_ref
        artifact.internal_file_path = None
    run.current_stage = "final_qc"
    run.progress_pct = 100
    from production.contracts import StageStatus
    for stage in run.stages:
        if stage.stage_name == "final_qc":
            stage.status = StageStatus.COMPLETED
            stage.execution_mode = "REAL"
            stage.output_json = run.quality_report.model_dump(mode="json")
    run.updated_at = datetime.now(timezone.utc)
    completion = {"job_id": str(job.id), "status": "COMPLETED", "run_status": run.status.value,
                  "storage_ref": payload.storage_ref, "checksum_sha256": payload.checksum_sha256,
                  "qc_report_id": run.quality_report.report_id}
    data["completion"] = completion
    data["run_snapshot"] = run.model_dump(mode="json")
    job.render_spec_json = data
    job.output_artifact_ref = accepted_ref
    job.status = "COMPLETED"
    job.completed_at = datetime.now(timezone.utc)
    job.lease_expires_at = None
    session.commit()
    # Compatibility cache is secondary; PostgreSQL is authoritative on restart.
    from production.repositories.run_repository import run_repository
    run_repository.update(run)
    return completion
