"""Least-privilege registry for outbound render workers.

The token is accepted only by the worker endpoints; it is never exposed to UI
routes or used for review/publishing/channel operations.
"""
from __future__ import annotations

import hmac
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import RLock
from typing import Dict, List, Optional


@dataclass
class RenderWorker:
    worker_id: str
    worker_type: str = "REMOTE_PERSONAL_WORKER"
    status: str = "ONLINE"
    platform: str = "windows"
    renderer_version: str = "canonical-v1"
    ffmpeg_version: str = "unknown"
    capabilities: List[str] = field(default_factory=list)
    max_concurrent_jobs: int = 1
    active_jobs: int = 0
    last_heartbeat_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class WorkerAuthError(PermissionError):
    pass


class WorkerRegistry:
    def __init__(self) -> None:
        self._workers: Dict[str, RenderWorker] = {}
        self._lock = RLock()

    def authenticate(self, token: Optional[str]) -> None:
        expected = os.getenv("VISIONFLOW_WORKER_TOKEN")
        if not expected or not token or not hmac.compare_digest(expected, token):
            raise WorkerAuthError("Invalid render worker credential")

    def register(self, payload: dict) -> RenderWorker:
        worker_id = str(payload.get("worker_id") or "").strip()
        if not worker_id or len(worker_id) > 120:
            raise ValueError("A valid worker_id is required")
        worker = RenderWorker(worker_id=worker_id, platform=str(payload.get("platform") or "windows"), renderer_version=str(payload.get("renderer_version") or "canonical-v1"), ffmpeg_version=str(payload.get("ffmpeg_version") or "unknown"), capabilities=list(payload.get("capabilities") or []), max_concurrent_jobs=max(1, int(payload.get("max_concurrent_jobs") or 1)))
        with self._lock:
            self._workers[worker_id] = worker
        return worker

    def heartbeat(self, worker_id: str, active_jobs: int = 0) -> RenderWorker:
        with self._lock:
            worker = self._workers.get(worker_id)
            if not worker:
                raise ValueError("Worker is not registered")
            worker.status = "ONLINE"
            worker.active_jobs = max(0, active_jobs)
            worker.last_heartbeat_at = datetime.now(timezone.utc)
            return worker

    def online_workers(self) -> List[RenderWorker]:
        with self._lock:
            return [item for item in self._workers.values() if item.status == "ONLINE"]


worker_registry = WorkerRegistry()
