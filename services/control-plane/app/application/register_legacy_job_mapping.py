from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Protocol


class LegacyJobMappingConflict(RuntimeError):
    """Raised when legacy_job_id is already mapped to a different workflow run."""


class LegacyJobAlreadyMappedToSameRun(RuntimeError):
    """Raised when the mapping already exists with identical values (cached idempotent result)."""


@dataclass(frozen=True)
class RegisterLegacyJobMappingCommand:
    """Typed command to bind a legacy MySQL job ID to an existing Control Plane workflow run.

    Must be issued by the legacy intake/orchestrator service only.  The narration
    worker MUST NOT issue this command — endpoint-level subject checks enforce this.
    """

    organization_id: uuid.UUID
    workflow_run_id: uuid.UUID
    legacy_source: str          # e.g. "agentbot.orchestrator.v1"
    legacy_job_id: str          # normalized VARCHAR(64) from MySQL PK
    idempotency_key: str        # min 16, max 128 chars
    actor_subject: str          # VISIONFLOW_INTAKE_SUBJECT; must differ from WORKER_SUBJECT
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass(frozen=True)
class LegacyJobMappingResult:
    workflow_run_id: uuid.UUID
    legacy_job_id: str
    registered: bool            # False means idempotent replay; True means first write


class LegacyJobMappingRepository(Protocol):
    def register(
        self, command: RegisterLegacyJobMappingCommand
    ) -> LegacyJobMappingResult:
        """Atomically persist a legacy job mapping with all required invariants.

        Invariants:
        - workflow_run must belong to organization_id;
        - legacy_job_id may only be mapped once globally (unique constraint);
        - duplicate attempt with same idempotency_key/same mapping → return cached result;
        - duplicate attempt mapping same legacy_job_id to a DIFFERENT run → raise LegacyJobMappingConflict;
        - worker identity must not call this; enforced by caller before reaching this layer.
        """


class RegisterLegacyJobMapping:
    """Application use case: register a legacy orchestrator job ID onto a workflow run."""

    def __init__(self, repository: LegacyJobMappingRepository) -> None:
        self._repository = repository

    def execute(self, command: RegisterLegacyJobMappingCommand) -> LegacyJobMappingResult:
        _validate(command)
        return self._repository.register(command)


def _validate(command: RegisterLegacyJobMappingCommand) -> None:
    legacy_job_id = command.legacy_job_id.strip()
    if not legacy_job_id:
        raise ValueError("legacy_job_id must not be blank")
    if len(legacy_job_id) > 64:
        raise ValueError("legacy_job_id must be 64 characters or fewer")

    legacy_source = command.legacy_source.strip()
    if not legacy_source:
        raise ValueError("legacy_source must not be blank")
    if len(legacy_source) > 128:
        raise ValueError("legacy_source must be 128 characters or fewer")

    idempotency_key = command.idempotency_key.strip()
    if len(idempotency_key) < 16:
        raise ValueError("idempotency_key must be at least 16 characters")
    if len(idempotency_key) > 128:
        raise ValueError("idempotency_key must be 128 characters or fewer")

    if not command.actor_subject.strip():
        raise ValueError("actor_subject must not be blank")

    if len(command.trace_id) != 32:
        raise ValueError("trace_id must be a 32-character correlation identifier")
