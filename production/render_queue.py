"""
Render Queue & Concurrency Management for VisionFlow Auto Production System (Phase 7 - Section 13, 14, 15).
Manages render state transitions (QUEUED, RENDERING, COMPLETED, FAILED, RETRYING),
worker heartbeats, crash recovery, and pipeline concurrency controls.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from production.canonical_renderer import CanonicalRenderSpec
from production.contracts import RenderJobState

logger = logging.getLogger("visionflow.production.render_queue")


@dataclass
class RenderJob:
    job_id: str
    run_id: str
    spec: CanonicalRenderSpec
    state: RenderJobState = RenderJobState.QUEUED
    worker_id: Optional[str] = None
    attempt_count: int = 0
    max_attempts: int = 3
    started_at: Optional[datetime] = None
    heartbeat_at: Optional[datetime] = None
    timeout_seconds: int = 300
    output_path: Optional[str] = None
    error_message: Optional[str] = None
    claimed_by_worker_id: Optional[str] = None
    claim_expires_at: Optional[datetime] = None
    output_artifact_ref: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ConcurrencyLimiter:
    """
    Guards pipeline resource allocation to prevent RAM/CPU exhaustion.
    Configured thresholds:
    - max simultaneous ingest: 5
    - max VLM concurrency: 3
    - max TTS concurrency: 4
    - max render concurrency: 2
    - max stock provider concurrency: 4
    """

    def __init__(self):
        self.max_ingest = 5
        self.max_vlm = 3
        self.max_tts = 4
        self.max_render = 2
        self.max_stock = 4

        self._active_counts = {
            "ingest": 0,
            "vlm": 0,
            "tts": 0,
            "render": 0,
            "stock": 0,
        }
        self._lock = asyncio.Lock()

    async def acquire(self, resource_name: str) -> bool:
        async with self._lock:
            limit = getattr(self, f"max_{resource_name}", 5)
            if self._active_counts.get(resource_name, 0) < limit:
                self._active_counts[resource_name] = self._active_counts.get(resource_name, 0) + 1
                return True
            return False

    async def release(self, resource_name: str) -> None:
        async with self._lock:
            if resource_name in self._active_counts and self._active_counts[resource_name] > 0:
                self._active_counts[resource_name] -= 1

    def get_status(self) -> Dict[str, Dict[str, int]]:
        return {
            res: {
                "active": self._active_counts.get(res, 0),
                "limit": getattr(self, f"max_{res}", 5),
            }
            for res in ["ingest", "vlm", "tts", "render", "stock"]
        }


class RenderQueue:
    """
    In-memory / durable render queue engine.
    Supports worker heartbeat inspection and automatic dead-worker crash recovery.
    """

    def __init__(self):
        self._jobs: Dict[str, RenderJob] = {}
        self._lock = threading.RLock()
        self.concurrency = ConcurrencyLimiter()

    def enqueue(self, run_id: str, spec: CanonicalRenderSpec) -> str:
        job_id = f"job_rnd_{uuid.uuid4().hex[:12]}"
        job = RenderJob(
            job_id=job_id,
            run_id=run_id,
            spec=spec,
            state=RenderJobState.QUEUED,
        )
        with self._lock:
            self._jobs[job_id] = job
        logger.info("Enqueued render job %s for run %s", job_id, run_id)
        return job_id

    def get_job(self, job_id: str) -> Optional[RenderJob]:
        return self._jobs.get(job_id)

    def get_job_by_run(self, run_id: str) -> Optional[RenderJob]:
        for j in reversed(list(self._jobs.values())):
            if j.run_id == run_id:
                return j
        return None

    def acquire_next_job(self, worker_id: str, lease_seconds: Optional[int] = None) -> Optional[RenderJob]:
        """Atomically claims a job. In-memory locking is the development implementation;
        a production repository must provide equivalent database compare-and-set semantics."""
        now = datetime.now(timezone.utc)
        lease = lease_seconds or int(os.getenv("VISIONFLOW_WORKER_LEASE_SECONDS", "180"))
        with self._lock:
          for job in self._jobs.values():
            if job.state in (RenderJobState.QUEUED, RenderJobState.WAITING_FOR_WORKER, RenderJobState.RETRYING):
                # Preserve the legacy in-process daemon contract: acquisition starts rendering.
                # Remote HTTP workers should use claim_next_job(), which exposes CLAIMED first.
                job.state = RenderJobState.RENDERING
                job.worker_id = worker_id
                job.claimed_by_worker_id = worker_id
                job.claim_expires_at = now + timedelta(seconds=lease)
                job.attempt_count += 1
                job.started_at = now
                job.heartbeat_at = now
                job.updated_at = now
                logger.info("Worker %s acquired render job %s (attempt %d)", worker_id, job.job_id, job.attempt_count)
                return job
        return None

    def claim_next_job(self, worker_id: str, lease_seconds: Optional[int] = None) -> Optional[RenderJob]:
        job = self.acquire_next_job(worker_id, lease_seconds)
        if job:
            job.state = RenderJobState.CLAIMED
        return job

    def record_heartbeat(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job and job.state in (RenderJobState.CLAIMED, RenderJobState.DOWNLOADING, RenderJobState.RENDERING, RenderJobState.UPLOADING):
            job.heartbeat_at = datetime.now(timezone.utc)
            job.updated_at = job.heartbeat_at
            return True
        return False

    def complete_job(self, job_id: str, output_path: str, worker_id: Optional[str] = None) -> bool:
        job = self._jobs.get(job_id)
        if job and (worker_id is None or job.claimed_by_worker_id == worker_id):
            job.state = RenderJobState.COMPLETED
            job.output_path = output_path
            job.output_artifact_ref = output_path
            job.updated_at = datetime.now(timezone.utc)
            logger.info("Render job %s completed successfully: %s", job_id, output_path)
            return True
        return False

    def fail_job(self, job_id: str, error_message: str) -> bool:
        job = self._jobs.get(job_id)
        if not job:
            return False
        job.error_message = error_message
        job.updated_at = datetime.now(timezone.utc)
        if job.attempt_count < job.max_attempts:
            job.state = RenderJobState.RETRYING
            logger.warning("Render job %s failed, scheduled for retry (%d/%d): %s", job_id, job.attempt_count, job.max_attempts, error_message)
        else:
            job.state = RenderJobState.FAILED
            logger.error("Render job %s permanently failed after %d attempts: %s", job_id, job.attempt_count, error_message)
        return True

    def check_stale_jobs(self, stale_threshold_seconds: int = 180) -> List[str]:
        """
        Detects jobs where the assigned worker crashed or stopped heartbeating.
        Requeues them safely if attempts remain, or fails them cleanly.
        """
        now = datetime.now(timezone.utc)
        reclaimed = []
        for job in self._jobs.values():
            if job.state in (RenderJobState.CLAIMED, RenderJobState.DOWNLOADING, RenderJobState.RENDERING, RenderJobState.UPLOADING) and job.heartbeat_at:
                elapsed = (now - job.heartbeat_at).total_seconds()
                if elapsed > stale_threshold_seconds:
                    logger.warning("Render job %s stale (last heartbeat %ds ago). Reclaiming...", job.job_id, int(elapsed))
                    if job.attempt_count < job.max_attempts:
                        job.state = RenderJobState.RETRYING
                        job.worker_id = None
                        job.updated_at = now
                    else:
                        job.state = RenderJobState.FAILED
                        job.error_message = f"Worker heartbeat timeout after {job.attempt_count} attempts"
                        job.updated_at = now
                    reclaimed.append(job.job_id)
        return reclaimed

    def list_active_jobs(self) -> List[RenderJob]:
        return [
            j for j in self._jobs.values()
            if j.state in (RenderJobState.QUEUED, RenderJobState.WAITING_FOR_WORKER, RenderJobState.CLAIMED, RenderJobState.DOWNLOADING, RenderJobState.RENDERING, RenderJobState.UPLOADING, RenderJobState.RETRYING)
        ]


# Singleton instance
render_queue = RenderQueue()
