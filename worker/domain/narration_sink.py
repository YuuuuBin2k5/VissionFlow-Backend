"""VF-03.02a.2 — Worker Execution Context and Narration Sink Port.

Per-job execution context is sourced exclusively from the authenticated
Control Plane API (GET /workflows/execution-context-by-job/{job_id}).
Environment variables are used only for static worker configuration.
"""
from __future__ import annotations

import datetime
import os
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class WorkerExecutionContext:
    """Immutable, per-job execution context sourced from the Control Plane API.

    Each instance is isolated to a single job call-stack. No global mutable
    state is used for per-job identity. Dataclass is frozen to prevent
    accidental mutation during concurrent processing.
    """

    workflow_run_id: uuid.UUID
    organization_id: uuid.UUID
    narration_attempt_id: str
    trace_id: str
    legacy_job_id: str | None = field(default=None)
    issued_at: str | None = field(default=None)
    event_version: int = field(default=1)

    @classmethod
    def from_api_response(
        cls,
        payload: dict[str, Any],
        *,
        legacy_job_id: str | int | None = None,
        trace_id: str | None = None,
    ) -> "WorkerExecutionContext":
        """Construct context from an authenticated Control Plane API response.

        This is the authoritative per-job context constructor. The payload
        must originate from GET /workflows/execution-context-by-job/{job_id}
        via the authenticated client. No heuristic mapping is performed.

        Args:
            payload: The JSON response body from the Control Plane API.
            legacy_job_id: The queue-level job ID used to look up the context.
            trace_id: Caller-supplied trace ID (X-Request-ID). If omitted,
                the field is taken from the payload or a UUID is generated.

        Raises:
            ValueError: If any required field is missing or malformed.
        """
        if not isinstance(payload, dict):
            raise ValueError("Execution context payload must be a JSON object")

        raw_run_id = payload.get("workflow_run_id")
        raw_org_id = payload.get("organization_id")
        attempt_id = (payload.get("narration_attempt_id") or "").strip()
        issued_at = payload.get("issued_at") or datetime.datetime.now(datetime.timezone.utc).isoformat()
        event_version = int(payload.get("event_version") or 1)

        if not raw_run_id:
            raise ValueError(
                "Missing workflow_run_id in execution context API response"
            )
        if not raw_org_id:
            raise ValueError(
                "Missing organization_id in execution context API response"
            )
        if not attempt_id:
            raise ValueError(
                "Missing or empty narration_attempt_id in execution context API response"
            )

        try:
            workflow_run_id = uuid.UUID(str(raw_run_id).strip())
        except (ValueError, AttributeError) as exc:
            raise ValueError(
                f"Invalid workflow_run_id UUID in execution context response: {raw_run_id!r}"
            ) from exc

        try:
            organization_id = uuid.UUID(str(raw_org_id).strip())
        except (ValueError, AttributeError) as exc:
            raise ValueError(
                f"Invalid organization_id UUID in execution context response: {raw_org_id!r}"
            ) from exc

        resolved_trace_id = (trace_id or payload.get("trace_id") or uuid.uuid4().hex).strip()

        return cls(
            workflow_run_id=workflow_run_id,
            organization_id=organization_id,
            narration_attempt_id=attempt_id,
            trace_id=resolved_trace_id,
            legacy_job_id=str(legacy_job_id) if legacy_job_id is not None else None,
            issued_at=issued_at,
            event_version=event_version,
        )

    @classmethod
    def from_env(cls) -> "WorkerExecutionContext":
        """[DEPRECATED — fallback for local development / unit tests only]

        Create execution context strictly from verified environment variables.
        This method MUST NOT be used for per-job identity in shadow or
        control_plane modes. Use from_api_response() via the authenticated
        Control Plane API instead.

        Fails closed on missing or malformed inputs.
        """
        run_id_str = os.environ.get("VISIONFLOW_WORKFLOW_RUN_ID")
        org_id_str = os.environ.get("VISIONFLOW_ORGANIZATION_ID")
        attempt_id = (
            os.environ.get("VISIONFLOW_NARRATION_ATTEMPT_ID")
            or os.environ.get("VISIONFLOW_SOURCE_GENERATION_REF")
        )
        trace_id = os.environ.get("VISIONFLOW_TRACE_ID") or os.environ.get("X_REQUEST_ID")

        if not run_id_str or not org_id_str or not attempt_id or not trace_id:
            raise ValueError(
                f"Missing required fields for WorkerExecutionContext (run_id: {bool(run_id_str)}, "
                f"org_id: {bool(org_id_str)}, attempt_id: {bool(attempt_id)}, trace_id: {bool(trace_id)})"
            )

        try:
            workflow_run_id = uuid.UUID(run_id_str.strip())
            organization_id = uuid.UUID(org_id_str.strip())
        except ValueError as exc:
            raise ValueError(f"Invalid UUID in WorkerExecutionContext: {exc}")

        attempt_id_clean = attempt_id.strip()
        trace_id_clean = trace_id.strip()

        if not attempt_id_clean:
            raise ValueError("Empty narration_attempt_id in WorkerExecutionContext")
        if not trace_id_clean or len(trace_id_clean) < 16:
            raise ValueError("Invalid trace_id in WorkerExecutionContext")

        return cls(
            workflow_run_id=workflow_run_id,
            organization_id=organization_id,
            narration_attempt_id=attempt_id_clean,
            trace_id=trace_id_clean,
        )


class NarrationSinkPort(Protocol):
    """Port interface for sinking LLM script/narration generation results."""

    def save_narration_result(
        self,
        job_id: int,
        hook: str,
        full_script: str,
        scenes_layout_json: Any,
        seo_tags: dict[str, Any],
        *,
        context: WorkerExecutionContext | None = None,
    ) -> dict[str, Any]:
        """Saves the narration results.

        Returns a dictionary containing execution metadata (success, source, version details).
        """
        ...
