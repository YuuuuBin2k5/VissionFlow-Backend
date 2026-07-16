"""VF-03.02a Commit 1 — Narration Sink Port and Mapping Contract."""
from __future__ import annotations

import uuid
from typing import Any, Protocol


# Deterministic UUID Namespace for mapping legacy_job_id -> workflow_run_id
UUID_NAMESPACE_VISIONFLOW = uuid.UUID("3d82084c-80b6-4d15-9bd3-d0459b1e50df")


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
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """Saves the narration results.

        Returns a dictionary containing execution metadata (success, source, version details).
        """
        ...


def get_deterministic_workflow_run_id(job_id: int) -> uuid.UUID:
    """Generates a stable, unique, and deterministic workflow_run_id for a legacy job."""
    return uuid.uuid5(UUID_NAMESPACE_VISIONFLOW, f"legacy-job-{job_id}")
