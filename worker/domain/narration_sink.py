"""VF-03.02a.1 — Worker Execution Context and Narration Sink Port."""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class WorkerExecutionContext:
    """Trusted execution context populated from Control Plane or dynamic env vars."""
    workflow_run_id: uuid.UUID
    organization_id: uuid.UUID
    narration_attempt_id: str
    trace_id: str

    @classmethod
    def from_env(cls) -> WorkerExecutionContext:
        """Create execution context strictly from verified environment variables.

        Fails closed on missing or malformed inputs.
        """
        run_id_str = os.environ.get("VISIONFLOW_WORKFLOW_RUN_ID")
        org_id_str = os.environ.get("VISIONFLOW_ORGANIZATION_ID")
        attempt_id = os.environ.get("VISIONFLOW_NARRATION_ATTEMPT_ID") or os.environ.get("VISIONFLOW_SOURCE_GENERATION_REF")
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
