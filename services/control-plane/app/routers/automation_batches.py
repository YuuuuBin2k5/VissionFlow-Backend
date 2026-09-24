from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.authorize_organization import AuthorizeOrganization
from app.core.oidc import VerifiedIdentity
from app.domain.authorization import Permission
from app.infrastructure.database import get_session
from app.infrastructure.membership_repository import SqlAlchemyOrganizationMembershipRepository
from app.infrastructure.models import AutomationBatch, AutomationJob
from app.routers.auth import require_identity
from production.contracts import ProductionRunStatus, ReviewSource
from production.human_review import HumanReviewError, human_review_service
from production.input_normalizer import InputNormalizer
from production.orchestrator import orchestrator
from production.repositories.run_repository import run_repository


router = APIRouter(tags=["automation_batches"])

TERMINAL_STATES = {"COMPLETED", "FAILED", "CANCELLED"}
FAILED_RUN_STATES = {
    ProductionRunStatus.FAILED,
    ProductionRunStatus.CANCELLED,
    ProductionRunStatus.BLOCKED_RIGHTS,
    ProductionRunStatus.BLOCKED_FACTS,
    ProductionRunStatus.RENDER_FAILED,
    ProductionRunStatus.QC_FAILED,
}


async def _launch_job(session: Session, batch: AutomationBatch, job: AutomationJob) -> None:
    settings = batch.settings if isinstance(batch.settings, dict) else {}
    normalized = InputNormalizer.normalize(
        raw_instruction=None,
        raw_sources=None,
        requested_format="short",
        language=str(settings.get("language") or "vi"),
        channel_profile_id=batch.channel_profile_id,
        target_duration_sec=job.source_payload.get("total_duration_seconds"),
        review_mode="final_only",
        overrides={
            "voice": job.source_payload.get("voice") or job.source_payload.get("voice_code"),
            "voice_code": job.source_payload.get("voice_code") or job.source_payload.get("voice"),
            "automation_batch_id": str(batch.id),
        },
        input_mode="JSON",
        raw_script=None,
        structured_payload=job.source_payload,
        run_environment=str(settings.get("run_environment") or "PRODUCTION"),
    )
    run = orchestrator.create_run(normalized)
    job.production_run_id = run.id
    job.state = "PROCESSING"
    job.attempt += 1
    job.error_code = None
    job.error_message = None
    session.commit()
    await orchestrator.start_run(run.id)


async def resume_pending_automation_jobs() -> None:
    """Recover jobs that were persisted before a web-process restart."""
    from sqlalchemy.orm import Session as SqlSession
    from app.infrastructure.database import get_engine

    with SqlSession(get_engine()) as session:
        jobs = list(session.scalars(
            select(AutomationJob).where(AutomationJob.state.in_(("QUEUED", "PROCESSING")))
        ))
        for job in jobs:
            if job.production_run_id and run_repository.get(job.production_run_id) is not None:
                continue
            batch = session.get(AutomationBatch, job.batch_id)
            if batch is None or batch.state == "CANCELLED" or job.attempt >= job.max_attempts:
                continue
            try:
                await _launch_job(session, batch, job)
            except Exception as exc:
                job.state = "FAILED"
                job.error_code = type(exc).__name__[:96]
                job.error_message = str(exc)[:4000]
                session.commit()


class AutomationItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    payload: dict[str, Any]

    @field_validator("payload")
    @classmethod
    def validate_visionflow_payload(cls, value: dict[str, Any]) -> dict[str, Any]:
        scenes = value.get("scenes")
        if not isinstance(scenes, list) or not 3 <= len(scenes) <= 20:
            raise ValueError("Mỗi JSON phải có từ 3 đến 20 scenes")
        if not str(value.get("title") or "").strip():
            raise ValueError("Mỗi JSON phải có title")
        for index, scene in enumerate(scenes, start=1):
            if not isinstance(scene, dict) or not str(scene.get("narration") or "").strip():
                raise ValueError(f"Scene {index} thiếu narration")
        return value


class CreateAutomationBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=160)
    channel_profile_id: str | None = Field(default=None, max_length=160)
    approval_policy: Literal["REVIEW_REQUIRED", "AUTO_APPROVE"] = "REVIEW_REQUIRED"
    language: str = Field(default="vi", min_length=2, max_length=12)
    run_environment: Literal["DEV", "PILOT", "PRODUCTION"] = "PRODUCTION"
    items: list[AutomationItemRequest] = Field(min_length=1, max_length=50)
    auto_schedule: bool = Field(default=False)
    schedule_platform: Literal["ALL", "TIKTOK", "YOUTUBE", "FACEBOOK"] = "ALL"
    schedule_start_at: str | None = Field(default=None)
    schedule_interval_minutes: int = Field(default=120, ge=15, le=1440)


class AutomationJobResponse(BaseModel):
    id: uuid.UUID
    position: int
    title: str
    state: str
    production_run_id: str | None
    progress_pct: int = 0
    current_stage: str | None = None
    error_code: str | None
    error_message: str | None
    thumbnail_urls: list[str] = Field(default_factory=list)
    selected_thumbnail_url: str | None = None
    scheduled_publish_at: str | None = None
    schedule_platform: str | None = None
    auto_publish_policy: str = "MANUAL"


class AutomationBatchResponse(BaseModel):
    id: uuid.UUID
    name: str
    state: str
    approval_policy: str
    channel_profile_id: str | None
    total: int
    completed: int
    failed: int
    created_at: str
    jobs: list[AutomationJobResponse]


def _authorize(session: Session, identity: VerifiedIdentity, organization_id: uuid.UUID, permission: Permission) -> None:
    try:
        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(
            identity.subject, organization_id, permission, identity.email
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization permission denied") from exc


def _map_run_state(run_status: ProductionRunStatus) -> str:
    if run_status == ProductionRunStatus.CANCELLED:
        return "CANCELLED"
    if run_status in FAILED_RUN_STATES:
        return "FAILED"
    if run_status == ProductionRunStatus.APPROVED:
        return "COMPLETED"
    if run_status in {ProductionRunStatus.HUMAN_REVIEW_PENDING, ProductionRunStatus.READY, ProductionRunStatus.NEEDS_REVIEW}:
        return "REVIEW_PENDING"
    if run_status in {
        ProductionRunStatus.WAITING_FOR_RENDER_WORKER,
        ProductionRunStatus.DOWNLOADING_RENDER_ASSETS,
        ProductionRunStatus.UPLOADING_RENDER,
        ProductionRunStatus.RENDERING,
        ProductionRunStatus.RENDERED,
        ProductionRunStatus.QC_RUNNING,
        ProductionRunStatus.QC_PASSED,
    }:
        return "RENDERING"
    return "PROCESSING"


def _reconcile(session: Session, batch: AutomationBatch) -> list[tuple[AutomationJob, int, str | None]]:
    jobs = list(session.scalars(select(AutomationJob).where(AutomationJob.batch_id == batch.id).order_by(AutomationJob.position)))
    projections: list[tuple[AutomationJob, int, str | None]] = []
    for job in jobs:
        progress = 0
        stage = None
        if job.production_run_id:
            run = run_repository.get(job.production_run_id)
            if run is not None:
                progress = run.progress_pct
                stage = run.current_stage
                mapped = _map_run_state(run.status)

                # Sync generated thumbnails from run
                if run.thumbnail_urls and not job.thumbnail_urls:
                    job.thumbnail_urls = run.thumbnail_urls
                if run.selected_thumbnail_url and not job.selected_thumbnail_url:
                    job.selected_thumbnail_url = run.selected_thumbnail_url

                if mapped == "REVIEW_PENDING" and batch.approval_policy == "AUTO_APPROVE":
                    try:
                        human_review_service.submit_review(
                            run_id=run.id,
                            reviewer=batch.requested_by_subject,
                            decision="APPROVED",
                            notes="Pre-authorized by durable automation batch policy.",
                            review_source=ReviewSource.REAL_OPERATOR,
                            client_source="automation_batch",
                        )
                        mapped = "COMPLETED"
                    except HumanReviewError as exc:
                        job.error_message = str(exc)
                job.state = mapped
                if mapped == "FAILED":
                    job.error_code = run.status.value
                    job.error_message = run.error_message
        projections.append((job, progress, stage))

    states = {job.state for job in jobs}
    if jobs and states <= TERMINAL_STATES:
        batch.state = "FAILED" if states == {"FAILED"} else "COMPLETED"
    elif "FAILED" in states:
        batch.state = "PARTIAL_FAILURE"
    elif any(state not in {"QUEUED"} for state in states):
        batch.state = "RUNNING"
    session.commit()
    return projections


def _response(batch: AutomationBatch, projections: list[tuple[AutomationJob, int, str | None]]) -> AutomationBatchResponse:
    jobs = [
        AutomationJobResponse(
            id=job.id,
            position=job.position,
            title=job.title,
            state=job.state,
            production_run_id=job.production_run_id,
            progress_pct=progress,
            current_stage=stage,
            error_code=job.error_code,
            error_message=job.error_message,
            thumbnail_urls=job.thumbnail_urls or [],
            selected_thumbnail_url=job.selected_thumbnail_url,
            scheduled_publish_at=job.scheduled_publish_at.isoformat() if job.scheduled_publish_at else None,
            schedule_platform=job.schedule_platform,
            auto_publish_policy=job.auto_publish_policy or "MANUAL",
        )
        for job, progress, stage in projections
    ]
    return AutomationBatchResponse(
        id=batch.id,
        name=batch.name,
        state=batch.state,
        approval_policy=batch.approval_policy,
        channel_profile_id=batch.channel_profile_id,
        total=len(jobs),
        completed=sum(item.state == "COMPLETED" for item in jobs),
        failed=sum(item.state == "FAILED" for item in jobs),
        created_at=batch.created_at.isoformat(),
        jobs=jobs,
    )


@router.post("/organizations/{organization_id}/automation-batches", response_model=AutomationBatchResponse, status_code=201)
async def create_automation_batch(
    organization_id: uuid.UUID,
    request: CreateAutomationBatchRequest,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=16, max_length=128),
    identity: VerifiedIdentity = Depends(require_identity),
    session: Session = Depends(get_session),
) -> AutomationBatchResponse:
    _authorize(session, identity, organization_id, Permission.WORKFLOW_CREATE)
    existing = session.scalar(select(AutomationBatch).where(
        AutomationBatch.organization_id == organization_id,
        AutomationBatch.idempotency_key == idempotency_key,
    ))
    if existing is not None:
        return _response(existing, _reconcile(session, existing))

    batch = AutomationBatch(
        organization_id=organization_id,
        name=request.name.strip(),
        approval_policy=request.approval_policy,
        channel_profile_id=request.channel_profile_id,
        requested_by_subject=identity.subject,
        idempotency_key=idempotency_key,
        settings={"language": request.language, "run_environment": request.run_environment},
    )
    session.add(batch)
    session.flush()

    start_dt: datetime | None = None
    if request.auto_schedule and request.schedule_start_at:
        try:
            start_dt = datetime.fromisoformat(request.schedule_start_at.replace("Z", "+00:00"))
        except Exception:
            start_dt = datetime.now(timezone.utc) + timedelta(hours=2)
    elif request.auto_schedule:
        start_dt = datetime.now(timezone.utc) + timedelta(hours=2)

    jobs: list[AutomationJob] = []
    for position, item in enumerate(request.items, start=1):
        payload = item.payload
        job_sched = None
        if start_dt:
            job_sched = start_dt + timedelta(minutes=(position - 1) * request.schedule_interval_minutes)
        job = AutomationJob(
            batch_id=batch.id,
            position=position,
            title=str(payload.get("title") or f"Video {position}")[:240],
            source_payload=payload,
            scheduled_publish_at=job_sched,
            schedule_platform=request.schedule_platform if request.auto_schedule else None,
            auto_publish_policy="AUTO_SCHEDULE" if request.auto_schedule else "MANUAL",
        )
        session.add(job)
        jobs.append(job)
    session.commit()

    for job in jobs:
        try:
            await _launch_job(session, batch, job)
        except Exception as exc:
            job.state = "FAILED"
            job.error_code = type(exc).__name__[:96]
            job.error_message = str(exc)[:4000]
            session.commit()

    return _response(batch, _reconcile(session, batch))


@router.get("/organizations/{organization_id}/automation-batches", response_model=list[AutomationBatchResponse])
def list_automation_batches(
    organization_id: uuid.UUID,
    limit: int = Query(default=20, ge=1, le=100),
    identity: VerifiedIdentity = Depends(require_identity),
    session: Session = Depends(get_session),
) -> list[AutomationBatchResponse]:
    _authorize(session, identity, organization_id, Permission.WORKFLOW_VIEW)
    batches = list(session.scalars(select(AutomationBatch).where(
        AutomationBatch.organization_id == organization_id
    ).order_by(AutomationBatch.created_at.desc()).limit(limit)))
    return [_response(batch, _reconcile(session, batch)) for batch in batches]


@router.get("/organizations/{organization_id}/automation-batches/{batch_id}", response_model=AutomationBatchResponse)
def get_automation_batch(
    organization_id: uuid.UUID,
    batch_id: uuid.UUID,
    identity: VerifiedIdentity = Depends(require_identity),
    session: Session = Depends(get_session),
) -> AutomationBatchResponse:
    _authorize(session, identity, organization_id, Permission.WORKFLOW_VIEW)
    batch = session.scalar(select(AutomationBatch).where(
        AutomationBatch.id == batch_id, AutomationBatch.organization_id == organization_id
    ))
    if batch is None:
        raise HTTPException(status_code=404, detail="Automation batch not found")
    return _response(batch, _reconcile(session, batch))


@router.post("/organizations/{organization_id}/automation-batches/{batch_id}/cancel", response_model=AutomationBatchResponse)
async def cancel_automation_batch(
    organization_id: uuid.UUID,
    batch_id: uuid.UUID,
    identity: VerifiedIdentity = Depends(require_identity),
    session: Session = Depends(get_session),
) -> AutomationBatchResponse:
    _authorize(session, identity, organization_id, Permission.WORKFLOW_ADVANCE)
    batch = session.scalar(select(AutomationBatch).where(
        AutomationBatch.id == batch_id, AutomationBatch.organization_id == organization_id
    ))
    if batch is None:
        raise HTTPException(status_code=404, detail="Automation batch not found")
    jobs = list(session.scalars(select(AutomationJob).where(AutomationJob.batch_id == batch.id)))
    for job in jobs:
        if job.production_run_id and job.state not in TERMINAL_STATES:
            await orchestrator.cancel_run(job.production_run_id)
            job.state = "CANCELLED"
    batch.state = "CANCELLED"
    session.commit()
    return _response(batch, [(job, 0, None) for job in jobs])


@router.post("/organizations/{organization_id}/automation-batches/{batch_id}/jobs/{job_id}/retry", response_model=AutomationBatchResponse)
async def retry_automation_job(
    organization_id: uuid.UUID,
    batch_id: uuid.UUID,
    job_id: uuid.UUID,
    identity: VerifiedIdentity = Depends(require_identity),
    session: Session = Depends(get_session),
) -> AutomationBatchResponse:
    _authorize(session, identity, organization_id, Permission.WORKFLOW_ADVANCE)
    batch = session.scalar(select(AutomationBatch).where(
        AutomationBatch.id == batch_id, AutomationBatch.organization_id == organization_id
    ))
    job = session.scalar(select(AutomationJob).where(
        AutomationJob.id == job_id, AutomationJob.batch_id == batch_id
    ))
    if batch is None or job is None:
        raise HTTPException(status_code=404, detail="Automation job not found")
    if job.state not in {"FAILED", "CANCELLED"}:
        raise HTTPException(status_code=409, detail="Only failed or cancelled jobs can be retried")
    if job.attempt >= job.max_attempts:
        raise HTTPException(status_code=409, detail="Automation job reached its retry limit")
    batch.state = "RUNNING"
    await _launch_job(session, batch, job)
    return _response(batch, _reconcile(session, batch))


class SelectThumbnailRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    thumbnail_url: str = Field(min_length=1, max_length=2048)


@router.post("/organizations/{organization_id}/automation-batches/{batch_id}/jobs/{job_id}/thumbnail/select", response_model=AutomationBatchResponse)
async def select_job_thumbnail(
    organization_id: uuid.UUID,
    batch_id: uuid.UUID,
    job_id: uuid.UUID,
    request: SelectThumbnailRequest,
    identity: VerifiedIdentity = Depends(require_identity),
    session: Session = Depends(get_session),
) -> AutomationBatchResponse:
    _authorize(session, identity, organization_id, Permission.WORKFLOW_ADVANCE)
    batch = session.scalar(select(AutomationBatch).where(
        AutomationBatch.id == batch_id, AutomationBatch.organization_id == organization_id
    ))
    job = session.scalar(select(AutomationJob).where(
        AutomationJob.id == job_id, AutomationJob.batch_id == batch_id
    ))
    if batch is None or job is None:
        raise HTTPException(status_code=404, detail="Automation batch or job not found")

    job.selected_thumbnail_url = request.thumbnail_url
    if job.production_run_id:
        run = run_repository.get(job.production_run_id)
        if run:
            run.selected_thumbnail_url = request.thumbnail_url
            run_repository.update(run)
    session.commit()
    return _response(batch, _reconcile(session, batch))


@router.post("/organizations/{organization_id}/automation-batches/{batch_id}/jobs/{job_id}/thumbnail/regenerate", response_model=AutomationBatchResponse)
async def regenerate_job_thumbnails(
    organization_id: uuid.UUID,
    batch_id: uuid.UUID,
    job_id: uuid.UUID,
    identity: VerifiedIdentity = Depends(require_identity),
    session: Session = Depends(get_session),
) -> AutomationBatchResponse:
    _authorize(session, identity, organization_id, Permission.WORKFLOW_ADVANCE)
    batch = session.scalar(select(AutomationBatch).where(
        AutomationBatch.id == batch_id, AutomationBatch.organization_id == organization_id
    ))
    job = session.scalar(select(AutomationJob).where(
        AutomationJob.id == job_id, AutomationJob.batch_id == batch_id
    ))
    if batch is None or job is None:
        raise HTTPException(status_code=404, detail="Automation batch or job not found")

    from production.thumbnail_generator import thumbnail_generator

    hook_text = ""
    scenes = job.source_payload.get("scenes", [])
    if isinstance(scenes, list) and scenes:
        hook_text = str(scenes[0].get("narration") or "")

    cat = "general"
    topic_str = (job.title + " " + hook_text).lower()
    if any(k in topic_str for k in ["lịch sử", "chiến", "vua", "triều", "history", "cổ đại"]):
        cat = "history"
    elif any(k in topic_str for k in ["khoa học", "vũ trụ", "bí ẩn", "mystery", "science"]):
        cat = "mystery" if "bí ẩn" in topic_str else "science"
    elif any(k in topic_str for k in ["viral", "hot", "tin tức", "news", "trend"]):
        cat = "viral"

    run_id = job.production_run_id or f"job_{job.id.hex[:8]}"
    new_urls = await asyncio.to_thread(
        thumbnail_generator.generate_thumbnails,
        title=job.title,
        hook=hook_text,
        category=cat,
        run_id=run_id,
    )
    job.thumbnail_urls = new_urls
    if new_urls:
        job.selected_thumbnail_url = new_urls[0]
    if job.production_run_id:
        run = run_repository.get(job.production_run_id)
        if run:
            run.thumbnail_urls = new_urls
            if new_urls:
                run.selected_thumbnail_url = new_urls[0]
            run_repository.update(run)
    session.commit()
    return _response(batch, _reconcile(session, batch))


class ScheduleJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scheduled_publish_at: str | None = None
    schedule_platform: str | None = "ALL"
    auto_publish_policy: Literal["MANUAL", "AUTO_SCHEDULE", "AUTO_APPROVE"] = "AUTO_SCHEDULE"


@router.post("/organizations/{organization_id}/automation-batches/{batch_id}/jobs/{job_id}/schedule", response_model=AutomationBatchResponse)
async def schedule_automation_job(
    organization_id: uuid.UUID,
    batch_id: uuid.UUID,
    job_id: uuid.UUID,
    request: ScheduleJobRequest,
    identity: VerifiedIdentity = Depends(require_identity),
    session: Session = Depends(get_session),
) -> AutomationBatchResponse:
    _authorize(session, identity, organization_id, Permission.WORKFLOW_ADVANCE)
    batch = session.scalar(select(AutomationBatch).where(
        AutomationBatch.id == batch_id, AutomationBatch.organization_id == organization_id
    ))
    job = session.scalar(select(AutomationJob).where(
        AutomationJob.id == job_id, AutomationJob.batch_id == batch_id
    ))
    if batch is None or job is None:
        raise HTTPException(status_code=404, detail="Automation batch or job not found")

    dt: datetime | None = None
    if request.scheduled_publish_at:
        try:
            dt = datetime.fromisoformat(request.scheduled_publish_at.replace("Z", "+00:00"))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid ISO datetime format: {exc}")

    job.scheduled_publish_at = dt
    job.schedule_platform = request.schedule_platform
    job.auto_publish_policy = request.auto_publish_policy

    if job.production_run_id:
        run = run_repository.get(job.production_run_id)
        if run:
            run.scheduled_publish_at = dt
            run.schedule_platform = request.schedule_platform
            run.auto_publish_policy = request.auto_publish_policy
            run_repository.update(run)

    session.commit()
    return _response(batch, _reconcile(session, batch))


class BatchScheduleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_at: str
    interval_minutes: int = Field(default=120, ge=15, le=1440)
    platform: Literal["ALL", "TIKTOK", "YOUTUBE", "FACEBOOK"] = "ALL"


@router.post("/organizations/{organization_id}/automation-batches/{batch_id}/batch-schedule", response_model=AutomationBatchResponse)
async def batch_schedule_jobs(
    organization_id: uuid.UUID,
    batch_id: uuid.UUID,
    request: BatchScheduleRequest,
    identity: VerifiedIdentity = Depends(require_identity),
    session: Session = Depends(get_session),
) -> AutomationBatchResponse:
    _authorize(session, identity, organization_id, Permission.WORKFLOW_ADVANCE)
    batch = session.scalar(select(AutomationBatch).where(
        AutomationBatch.id == batch_id, AutomationBatch.organization_id == organization_id
    ))
    if batch is None:
        raise HTTPException(status_code=404, detail="Automation batch not found")

    try:
        base_dt = datetime.fromisoformat(request.start_at.replace("Z", "+00:00"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid ISO datetime format: {exc}")

    jobs = list(session.scalars(select(AutomationJob).where(AutomationJob.batch_id == batch.id).order_by(AutomationJob.position)))
    for idx, job in enumerate(jobs):
        sched_time = base_dt + timedelta(minutes=idx * request.interval_minutes)
        job.scheduled_publish_at = sched_time
        job.schedule_platform = request.platform
        job.auto_publish_policy = "AUTO_SCHEDULE"
        if job.production_run_id:
            run = run_repository.get(job.production_run_id)
            if run:
                run.scheduled_publish_at = sched_time
                run.schedule_platform = request.platform
                run.auto_publish_policy = "AUTO_SCHEDULE"
                run_repository.update(run)

    session.commit()
    return _response(batch, _reconcile(session, batch))
