from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Protocol

from app.domain.workflow import WorkflowState


class WorkflowStateConflict(RuntimeError):
    """Raised when a worker result was submitted for a stale workflow state."""


class IdempotencyKeyConflict(RuntimeError):
    """Raised when a key belongs to a different workflow run."""


class StaleNarrationAttempt(RuntimeError):
    """Raised when the narration_attempt_id does not match the active script step attempt."""


class ActiveNarrationAttemptMissing(RuntimeError):
    """Raised when no active narration attempt exists for the workflow run (context GET)."""


@dataclass(frozen=True)
class SceneCommandPayload:
    narration: str
    visual_prompt: str
    duration_seconds: int
    transition: str = "cut"
    caption: str | None = None


@dataclass(frozen=True)
class SourceMetadataPayload:
    provider: str
    model: str
    model_version_config: str | None = None
    source_run_ref: str | None = None


@dataclass(frozen=True)
class RecordNarrationGeneratedCommand:
    organization_id: uuid.UUID
    workflow_run_id: uuid.UUID
    idempotency_key: str
    script: str
    scenes: list[SceneCommandPayload]
    source_metadata: SourceMetadataPayload
    # narration_attempt_id must be provided by the worker (obtained from context endpoint).
    # Control Plane verifies this matches the active script step attempt before persisting.
    narration_attempt_id: str
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    legacy_job_id: str | None = None
    actor_subject: str = "worker:narration"


@dataclass(frozen=True)
class NarrationResultSummary:
    workflow_run_id: uuid.UUID
    state: WorkflowState
    changed: bool
    version_id: uuid.UUID
    version: int


class NarrationResultRepository(Protocol):
    def record_narration_result(
        self, command: RecordNarrationGeneratedCommand
    ) -> NarrationResultSummary:
        """Atomically persist narration result, update workflow state, and log events."""


class RecordNarrationGenerated:
    """Application use case for worker submission of narration planning result."""

    def __init__(self, repository: NarrationResultRepository) -> None:
        self._repository = repository

    def execute(self, command: RecordNarrationGeneratedCommand) -> NarrationResultSummary:
        _validate(command)
        return self._repository.record_narration_result(command)


def _validate(command: RecordNarrationGeneratedCommand) -> None:
    if not command.script.strip():
        raise ValueError("script must not be blank")
    if len(command.script.strip()) < 40:
        raise ValueError("script must be at least 40 characters")
    if len(command.script.strip()) > 50000:
        raise ValueError("script must be 50,000 characters or fewer")

    if not command.scenes:
        raise ValueError("scenes list must not be empty")
    if not (3 <= len(command.scenes) <= 20):
        raise ValueError("scenes list must contain between 3 and 20 elements")

    for index, scene in enumerate(command.scenes, start=1):
        if not scene.narration.strip():
            raise ValueError(f"scene {index}: narration must not be blank")
        if len(scene.narration.strip()) > 5000:
            raise ValueError(f"scene {index}: narration must be 5,000 characters or fewer")
        if not scene.visual_prompt.strip():
            raise ValueError(f"scene {index}: visual_prompt must not be blank")
        if len(scene.visual_prompt.strip()) > 5000:
            raise ValueError(f"scene {index}: visual_prompt must be 5,000 characters or fewer")
        if not (1 <= scene.duration_seconds <= 90):
            raise ValueError(f"scene {index}: duration_seconds must be between 1 and 90")
        if not scene.transition.strip():
            raise ValueError(f"scene {index}: transition must not be blank")
        if len(scene.transition.strip()) > 500:
            raise ValueError(f"scene {index}: transition must be 500 characters or fewer")
        if scene.caption is not None and len(scene.caption) > 2000:
            raise ValueError(f"scene {index}: caption must be 2,000 characters or fewer")

    if len(command.idempotency_key.strip()) < 16:
        raise ValueError("idempotency_key must be at least 16 characters")
    if len(command.idempotency_key) > 128:
        raise ValueError("idempotency_key must be 128 characters or fewer")
    if len(command.trace_id) != 32:
        raise ValueError("trace_id must be a 32-character correlation identifier")

    narration_attempt_id = command.narration_attempt_id.strip()
    if not narration_attempt_id:
        raise ValueError("narration_attempt_id must not be blank")
    if len(narration_attempt_id) > 128:
        raise ValueError("narration_attempt_id must be 128 characters or fewer")
