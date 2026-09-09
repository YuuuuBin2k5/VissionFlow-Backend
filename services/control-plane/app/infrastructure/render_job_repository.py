"""Durable, leased PostgreSQL queue for outbound canonical render workers.

Public mutations commit one transaction. ``locked_owned_job`` instead lets the
completion service save the job and production-run snapshot atomically.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import ConfigurationError
from app.infrastructure.models import RenderJob, RenderWorker

CLAIMABLE = ("QUEUED", "WAITING_FOR_WORKER", "RETRYING")
ACTIVE = ("CLAIMED", "DOWNLOADING", "RENDERING", "UPLOADING")
WORKER_ONLINE_SECONDS = 180


def worker_online_seconds():
    value = int(os.getenv("VISIONFLOW_WORKER_ONLINE_SECONDS", str(WORKER_ONLINE_SECONDS)))
    if not 90 <= value <= 300:
        raise ValueError("Worker freshness threshold must be between 90 and 300 seconds")
    return value


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _job_id(value: uuid.UUID | str) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _lease_duration(seconds: int) -> timedelta:
    if not 1 <= seconds <= 3600:
        raise ValueError("Lease duration must be between 1 and 3600 seconds")
    return timedelta(seconds=seconds)


class PostgresRenderJobRepository:
    def __init__(self, session: Session) -> None:
        if session.get_bind().dialect.name != "postgresql":
            raise ConfigurationError("Remote render jobs require PostgreSQL")
        self._session = session

    def create_job(
        self, *, run_id: str, spec: dict[str, Any], input_hash: str,
        idempotency_key: str, max_attempts: int = 3,
        job_id: uuid.UUID | str | None = None, priority: int = 100,
        render_spec_version: str = "canonical-v1",
    ) -> RenderJob:
        if not 1 <= max_attempts <= 20:
            raise ValueError("max_attempts must be between 1 and 20")
        if not run_id or not idempotency_key:
            raise ValueError("run_id and idempotency_key are required")
        # The unique index arbitrates producer races across backend processes.
        self._session.execute(insert(RenderJob).values(
            id=_job_id(job_id) if job_id else uuid.uuid4(), run_id=run_id,
            status="WAITING_FOR_WORKER", priority=priority,
            render_spec_version=render_spec_version, render_spec_json=spec,
            render_input_hash=input_hash, max_attempts=max_attempts, attempt=0,
            retryable=True, idempotency_key=idempotency_key,
        ).on_conflict_do_nothing(index_elements=[RenderJob.idempotency_key]))
        job = self.get_job_by_idempotency_key(idempotency_key)
        if job is None:
            raise RuntimeError("Render job insert did not persist")
        if job.run_id != run_id or job.render_input_hash != input_hash:
            self._session.rollback()
            raise ValueError("Render idempotency key already belongs to different input")
        self._session.commit()
        self._session.refresh(job)
        return job

    def get_job(self, job_id: uuid.UUID | str) -> RenderJob | None:
        return self._session.get(RenderJob, _job_id(job_id))

    def get_job_by_idempotency_key(self, key: str) -> RenderJob | None:
        return self._session.scalar(select(RenderJob).where(RenderJob.idempotency_key == key))

    def claim_next_job(self, worker_id: str, lease_seconds: int = 180) -> RenderJob | None:
        lease = _lease_duration(lease_seconds)
        # Serialize claims per worker to protect capacity across HTTP requests.
        worker = self._session.scalar(
            select(RenderWorker).where(RenderWorker.worker_id == worker_id)
            .with_for_update().execution_options(populate_existing=True)
        )
        now = _now()
        if (
            worker is None or worker.status != "ONLINE" or worker.last_heartbeat_at is None
            or worker.last_heartbeat_at <= now - timedelta(seconds=worker_online_seconds())
        ):
            self._session.rollback()
            raise PermissionError("Render worker is not registered and online")
        active_jobs = self._session.scalar(select(func.count()).select_from(RenderJob).where(
            RenderJob.claimed_by_worker_id == worker_id, RenderJob.status.in_(ACTIVE),
            RenderJob.lease_expires_at > now,
        )) or 0
        if active_jobs >= worker.max_concurrent_jobs:
            self._session.commit()
            return None
        # PostgreSQL row locks arbitrate claims across independent processes.
        job = self._session.scalar(
            select(RenderJob).where(
                RenderJob.status.in_(CLAIMABLE), RenderJob.attempt < RenderJob.max_attempts,
            ).order_by(RenderJob.priority, RenderJob.created_at, RenderJob.id)
            .with_for_update(skip_locked=True).limit(1)
            .execution_options(populate_existing=True)
        )
        if job is None:
            self._session.commit()
            return None
        job.status = "CLAIMED"
        job.claimed_by_worker_id = worker_id
        job.attempt += 1
        job.last_heartbeat_at = now
        job.lease_expires_at = now + lease
        job.error_code = None
        job.error_message = None
        job.failed_at = None
        self._session.commit()
        self._session.refresh(job)
        return job

    def locked_owned_job(
        self, job_id: uuid.UUID | str, worker_id: str, attempt: int,
        allow_completed: bool = False,
    ) -> RenderJob:
        """Lock an attempt-fenced lease; caller must commit or roll back.

        Only replay of a completed attempt may bypass expiry. A restarted worker
        with the same identity cannot mutate its previous claim attempt.
        """
        job = self._session.scalar(
            select(RenderJob).where(RenderJob.id == _job_id(job_id))
            .with_for_update().execution_options(populate_existing=True)
        )
        if job is None or job.claimed_by_worker_id != worker_id or job.attempt != attempt:
            raise PermissionError("Job lease is not owned by this worker attempt")
        if allow_completed and job.status == "COMPLETED":
            return job
        if job.status not in ACTIVE or job.lease_expires_at is None or job.lease_expires_at <= _now():
            raise PermissionError("Job lease is inactive or expired")
        return job

    def heartbeat_job(
        self, job_id: uuid.UUID | str, worker_id: str, lease_seconds: int = 180, *, attempt: int,
    ) -> RenderJob:
        lease = _lease_duration(lease_seconds)
        job = self.locked_owned_job(job_id, worker_id, attempt)
        now = _now()
        job.last_heartbeat_at = now
        job.lease_expires_at = now + lease
        self._session.commit()
        return job

    def update_progress(
        self, job_id: uuid.UUID | str, worker_id: str, status: str,
        *, attempt: int, lease_seconds: int = 180,
    ) -> RenderJob:
        lease = _lease_duration(lease_seconds)
        if status not in ACTIVE:
            raise ValueError("Unsupported render progress state")
        job = self.locked_owned_job(job_id, worker_id, attempt)
        if ACTIVE.index(status) < ACTIVE.index(job.status):
            raise ValueError("Render progress cannot move backwards")
        now = _now()
        job.status = status
        job.last_heartbeat_at = now
        job.lease_expires_at = now + lease
        self._session.commit()
        return job

    def complete_job(
        self, job_id: uuid.UUID | str, worker_id: str, artifact_ref: str, *, attempt: int,
    ) -> RenderJob:
        """Repository primitive; the HTTP completion service validates storage first."""
        job = self.locked_owned_job(job_id, worker_id, attempt, allow_completed=True)
        if job.status == "COMPLETED":
            if job.output_artifact_ref != artifact_ref:
                raise ValueError("Completed job already has a different artifact")
            self._session.commit()
            return job
        if not artifact_ref:
            raise ValueError("Output artifact reference is required")
        job.status = "COMPLETED"
        job.output_artifact_ref = artifact_ref
        job.completed_at = _now()
        job.lease_expires_at = None
        self._session.commit()
        return job

    def fail_job(
        self, job_id: uuid.UUID | str, worker_id: str, code: str, message: str,
        retryable: bool, *, attempt: int,
    ) -> RenderJob:
        job = self.locked_owned_job(job_id, worker_id, attempt)
        self._fail(job, code, message, retryable, _now())
        self._session.commit()
        return job

    @staticmethod
    def _fail(job: RenderJob, code: str, message: str, retryable: bool, now: datetime) -> None:
        job.error_code = code[:80]
        job.error_message = message[:2000]
        job.retryable = retryable
        job.status = "RETRYING" if retryable and job.attempt < job.max_attempts else "FAILED"
        job.failed_at = now if job.status == "FAILED" else None
        job.claimed_by_worker_id = None
        job.lease_expires_at = None

    def release_expired_jobs(self) -> int:
        now = _now()
        jobs = self._session.scalars(select(RenderJob).where(
            RenderJob.status.in_(ACTIVE), RenderJob.lease_expires_at <= now,
        ).with_for_update(skip_locked=True).execution_options(populate_existing=True)).all()
        for job in jobs:
            self._fail(job, "WORKER_LEASE_EXPIRED", "Worker stopped renewing its lease", True, now)
        self._session.commit()
        return len(jobs)


class PostgresRenderWorkerRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_worker(self, worker_id: str) -> RenderWorker | None:
        return self._session.get(RenderWorker, worker_id)

    def register_worker(self, **payload: Any) -> RenderWorker:
        allowed = {
            "worker_id", "worker_type", "platform", "renderer_version", "ffmpeg_version",
            "capabilities", "max_concurrent_jobs",
        }
        if set(payload) - allowed:
            raise ValueError("Unsupported worker registration fields")
        capacity = int(payload.get("max_concurrent_jobs", 1))
        if not 1 <= capacity <= 32:
            raise ValueError("Worker capacity must be between 1 and 32")
        payload["max_concurrent_jobs"] = capacity
        worker_id = payload["worker_id"]
        self._session.execute(insert(RenderWorker).values(**payload).on_conflict_do_nothing(
            index_elements=[RenderWorker.worker_id],
        ))
        worker = self._session.scalar(
            select(RenderWorker).where(RenderWorker.worker_id == worker_id)
            .with_for_update().execution_options(populate_existing=True)
        )
        if worker is None or worker.status == "DISABLED":
            self._session.rollback()
            raise PermissionError("Render worker is disabled")
        for key, value in payload.items():
            setattr(worker, key, value)
        worker.status = "ONLINE"
        worker.last_heartbeat_at = _now()
        self._session.commit()
        return worker

    def heartbeat_worker(self, worker_id: str) -> RenderWorker:
        worker = self._session.scalar(
            select(RenderWorker).where(RenderWorker.worker_id == worker_id)
            .with_for_update().execution_options(populate_existing=True)
        )
        if worker is None or worker.status == "DISABLED":
            raise PermissionError("Worker is not registered or is disabled")
        worker.status = "ONLINE"
        worker.last_heartbeat_at = _now()
        self._session.commit()
        return worker

    def list_workers(self, *, online_seconds: int | None = None) -> list[dict[str, Any]]:
        online_seconds = worker_online_seconds() if online_seconds is None else online_seconds
        now = _now()
        workers = self._session.scalars(select(RenderWorker).order_by(RenderWorker.worker_id)).all()
        counts = dict(self._session.execute(select(RenderJob.claimed_by_worker_id, func.count()).where(
            RenderJob.status.in_(ACTIVE), RenderJob.lease_expires_at > now,
        ).group_by(RenderJob.claimed_by_worker_id)).all())
        return [{
            "worker_id": worker.worker_id,
            "status": (
                "ONLINE" if worker.status == "ONLINE" and worker.last_heartbeat_at
                and worker.last_heartbeat_at > now - timedelta(seconds=online_seconds)
                else "DISABLED" if worker.status == "DISABLED" else "OFFLINE"
            ),
            "last_heartbeat_at": worker.last_heartbeat_at.isoformat() if worker.last_heartbeat_at else None,
            "active_jobs": counts.get(worker.worker_id, 0),
            "capacity": worker.max_concurrent_jobs,
        } for worker in workers]

    def list_active_workers(self, *, online_seconds: int | None = None) -> list[dict[str, Any]]:
        return [worker for worker in self.list_workers(online_seconds=online_seconds) if worker["status"] == "ONLINE"]


def get_render_job_repository(session: Session) -> PostgresRenderJobRepository:
    """Remote services must not silently downgrade to the local dev queue."""
    backend = os.getenv("VISIONFLOW_RENDER_JOB_BACKEND", "postgres").strip().lower()
    if backend != "postgres":
        raise ConfigurationError("Remote rendering requires VISIONFLOW_RENDER_JOB_BACKEND=postgres")
    return PostgresRenderJobRepository(session)
