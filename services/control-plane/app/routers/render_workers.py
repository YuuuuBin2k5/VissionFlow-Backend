"""Outbound render worker API; durable PostgreSQL coordination only."""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import Field, model_validator
from sqlalchemy.orm import Session

from app.infrastructure.database import get_session
from app.infrastructure.render_job_repository import get_render_job_repository, PostgresRenderWorkerRepository
from app.routers.auth import require_identity
from production.artifact_storage import get_artifact_storage
from production.remote_manifest import Checksum, WireModel, PortableRenderManifest
from production.remote_render import complete_remote_render, remote_render_enabled
from production.remote_worker_auth import WorkerIdentity, require_render_worker, worker_credentials

router = APIRouter(prefix="/render-workers", tags=["render-workers"])


class Registration(WireModel):
    platform: str = Field(max_length=32)
    renderer_version: Literal["canonical-v1"]
    ffmpeg_version: str = Field(max_length=200)
    capabilities: list[str] = Field(max_length=16)
    max_concurrent_jobs: Literal[1] = 1


class Attempt(WireModel):
    attempt: int = Field(ge=1)


class Heartbeat(WireModel):
    job_id: UUID | None = None
    attempt: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def paired(self):
        if (self.job_id is None) != (self.attempt is None):
            raise ValueError("job_id and attempt are required together")
        return self


class Progress(Attempt):
    status: Literal["CLAIMED", "DOWNLOADING", "RENDERING", "UPLOADING"]


class OutputUpload(Attempt):
    checksum_sha256: Checksum
    file_size_bytes: int = Field(gt=0, le=10 * 1024**3)


class RenderTelemetry(WireModel):
    renderer_version: Literal["canonical-v1"] = "canonical-v1"
    render_seconds: float = Field(default=0, ge=0, le=86400)


class Completion(OutputUpload):
    storage_ref: str = Field(max_length=1024)
    duration_seconds: float = Field(gt=0, le=3601)
    width: int = Field(gt=0, le=3840)
    height: int = Field(gt=0, le=3840)
    fps: float = Field(gt=0, le=60)
    video_codec: str = Field(max_length=32)
    audio_codec: str = Field(max_length=32)
    telemetry: RenderTelemetry = Field(default_factory=RenderTelemetry)


class Failure(Attempt):
    error_code: Literal["ASSET_DOWNLOAD_FAILED", "ASSET_CHECKSUM_MISMATCH", "FFMPEG_UNAVAILABLE",
                        "RENDER_FAILED", "OUTPUT_INVALID", "UPLOAD_FAILED", "WORKER_INTERNAL_ERROR"]
    retryable: bool


def repository(session: Session = Depends(get_session)):
    try:
        return get_render_job_repository(session)
    except Exception:
        raise HTTPException(503, "Durable render queue unavailable") from None


def registered_worker(identity: WorkerIdentity = Depends(require_render_worker), session: Session = Depends(get_session)):
    worker = PostgresRenderWorkerRepository(session).get_worker(identity.worker_id)
    if worker is None or worker.status == "DISABLED":
        raise HTTPException(403, "Worker is not registered or is disabled")
    return WorkerIdentity(worker_id=identity.worker_id, capabilities=tuple(worker.capabilities), status=worker.status)


def owned(repo, job_id, worker, attempt, allow_completed=False):
    try:
        return repo.locked_owned_job(job_id, worker.worker_id, attempt, allow_completed=allow_completed)
    except PermissionError:
        raise HTTPException(409, "Job lease is not owned or has expired") from None


@router.get("/status")
def status(identity=Depends(require_identity), session: Session = Depends(get_session)):
    if identity.subject == "local|anonymous":
        raise HTTPException(401, "Operator authentication required")
    configured = remote_render_enabled() and bool(worker_credentials())
    return {"configured": configured, "workers": PostgresRenderWorkerRepository(session).list_workers() if configured else []}


@router.post("/register")
def register(payload: Registration, identity=Depends(require_render_worker), session: Session = Depends(get_session), repo=Depends(repository)):
    if not set(identity.capabilities).issubset(payload.capabilities):
        raise HTTPException(422, "Canonical renderer capabilities required")
    try:
        worker = PostgresRenderWorkerRepository(session).register_worker(
            worker_id=identity.worker_id, worker_type="REMOTE_PERSONAL_WORKER", platform=payload.platform,
            renderer_version=payload.renderer_version, ffmpeg_version=payload.ffmpeg_version[:160],
            capabilities=list(identity.capabilities), max_concurrent_jobs=1,
        )
    except PermissionError:
        raise HTTPException(403, "Worker is disabled") from None
    return {"worker_id": worker.worker_id, "status": worker.status, "heartbeat_seconds": 10, "lease_seconds": 180}


@router.post("/heartbeat")
def heartbeat(payload: Heartbeat, worker=Depends(registered_worker), session: Session = Depends(get_session), repo=Depends(repository)):
    if payload.job_id:
        job = owned(repo, payload.job_id, worker, payload.attempt, allow_completed=True)
        if job.status != "COMPLETED":
            repo.heartbeat_job(job.id, worker.worker_id, attempt=payload.attempt)
        else:
            session.commit()
    PostgresRenderWorkerRepository(session).heartbeat_worker(worker.worker_id)
    return {"status": "ONLINE"}


@router.post("/jobs/claim")
def claim(worker=Depends(registered_worker), repo=Depends(repository)):
    repo.release_expired_jobs()
    try:
        job = repo.claim_next_job(worker.worker_id)
    except PermissionError:
        raise HTTPException(409, "Worker must heartbeat before claiming") from None
    if job is None:
        return Response(status_code=204)
    return {"job_id": str(job.id), "run_id": job.run_id, "attempt": job.attempt}


@router.get("/jobs/{job_id}/manifest")
def manifest(job_id: UUID, attempt: int = Query(ge=1), worker=Depends(registered_worker),
             repo=Depends(repository), session: Session = Depends(get_session), storage=Depends(get_artifact_storage)):
    job = owned(repo, job_id, worker, attempt)
    result = PortableRenderManifest.model_validate(job.render_spec_json["manifest"]).persisted()
    for artifact in result["artifacts"]:
        artifact["download_url"] = storage.presigned_download(artifact["storage_ref"])
    session.commit()
    return result


@router.post("/jobs/{job_id}/progress")
def progress(job_id: UUID, payload: Progress, worker=Depends(registered_worker), repo=Depends(repository)):
    owned(repo, job_id, worker, payload.attempt)
    try:
        job = repo.update_progress(job_id, worker.worker_id, payload.status, attempt=payload.attempt)
    except ValueError:
        raise HTTPException(409, "Invalid progress transition") from None
    return {"status": job.status}


@router.post("/jobs/{job_id}/output-upload")
def output_upload(job_id: UUID, payload: OutputUpload, worker=Depends(registered_worker), repo=Depends(repository),
                  session: Session = Depends(get_session), storage=Depends(get_artifact_storage)):
    job = owned(repo, job_id, worker, payload.attempt)
    data = dict(job.render_spec_json)
    if job.status != "UPLOADING":
        raise HTTPException(409, "Output upload requires UPLOADING state")
    ref = f"visionflow/production/attempts/{job.id}/{job.attempt}/{payload.checksum_sha256}.mp4"
    authorized = {**payload.model_dump(), "storage_ref": ref}
    if data.get("authorized_upload", {}).get("attempt") == job.attempt and data["authorized_upload"] != authorized:
        raise HTTPException(409, "This attempt already authorized a different output")
    response = storage.presigned_upload(ref, payload.checksum_sha256)
    data["authorized_upload"] = authorized
    job.render_spec_json = data
    session.commit()
    return response


@router.post("/jobs/{job_id}/complete")
def complete(job_id: UUID, payload: Completion, worker=Depends(registered_worker), repo=Depends(repository),
             session: Session = Depends(get_session), storage=Depends(get_artifact_storage)):
    job = owned(repo, job_id, worker, payload.attempt, allow_completed=True)
    try:
        return complete_remote_render(session, job, payload, storage)
    except ValueError as exc:
        session.rollback()
        safe = str(exc) if str(exc).startswith("OUTPUT_") else "OUTPUT_INVALID"
        raise HTTPException(422, safe) from None


@router.post("/jobs/{job_id}/fail")
def fail(job_id: UUID, payload: Failure, worker=Depends(registered_worker), repo=Depends(repository)):
    owned(repo, job_id, worker, payload.attempt)
    job = repo.fail_job(job_id, worker.worker_id, payload.error_code, payload.error_code,
                        payload.retryable, attempt=payload.attempt)
    return {"status": job.status}
