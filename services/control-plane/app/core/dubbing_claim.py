"""Transactional lease-based claiming for the monolith dubbing worker."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.infrastructure.models import WorkflowRun


def _is_dubbing(workflow: WorkflowRun) -> bool:
    manifest = workflow.prompt_manifest or {}
    payload = workflow.input_payload or {}
    return (manifest.get("render_mode") or payload.get("render_mode")) == "TRANSLATE_DUB"


def claim_next_dubbing_workflow(session: Session, *, worker_id: str, lease_seconds: int = 1800) -> WorkflowRun | None:
    """Atomically claim one queued/expired workflow using PostgreSQL row locks.

    Lease state lives in JSON until a dedicated operational migration is
    warranted.  ``SKIP LOCKED`` lets independent worker processes progress
    without waiting on or duplicating the same render.
    """
    now = datetime.now(timezone.utc)
    rows = session.scalars(
        select(WorkflowRun)
        .where(WorkflowRun.state.in_(("QUEUED", "RENDERING")))
        .order_by(WorkflowRun.created_at.asc())
        .with_for_update(skip_locked=True)
        .limit(50)
    ).all()
    for workflow in rows:
        if not _is_dubbing(workflow):
            continue
        payload: dict[str, Any] = dict(workflow.input_payload or {})
        lease = payload.get("dubbing_claim") if isinstance(payload.get("dubbing_claim"), dict) else {}
        expires_at = lease.get("expires_at")
        expired = True
        if isinstance(expires_at, str):
            try:
                expired = datetime.fromisoformat(expires_at.replace("Z", "+00:00")) <= now
            except ValueError:
                expired = True
        if workflow.state == "RENDERING" and not expired:
            continue
        payload["dubbing_claim"] = {
            "worker_id": worker_id,
            "claimed_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=lease_seconds)).isoformat(),
            "attempt": int(lease.get("attempt", 0)) + 1,
        }
        workflow.input_payload = payload
        workflow.state = "RENDERING"
        flag_modified(workflow, "input_payload")
        session.commit()
        return workflow
    session.rollback()
    return None
