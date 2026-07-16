"""Create the authoritative Stream B request for a legacy rendering job."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Protocol

from app.domain.workflow import WorkflowState, require_transition


class LegacyJobRequestConflict(RuntimeError):
    """Raised when a replay does not match its original source command."""


@dataclass(frozen=True)
class RequestLegacyJobCommand:
    """Advance a READY workflow and atomically persist its intake outbox event.

    ``source_command_id`` is the durable idempotency boundary shared with the
    future Redis consumer.  It is deliberately a UUID, never a synthesized
    identifier from legacy metadata.
    """

    organization_id: uuid.UUID
    workflow_run_id: uuid.UUID
    source_command_id: uuid.UUID
    actor_subject: str
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass(frozen=True)
class LegacyJobRequestResult:
    workflow_run_id: uuid.UUID
    source_command_id: uuid.UUID
    event_id: uuid.UUID
    state: WorkflowState
    changed: bool


class LegacyJobRequestRepository(Protocol):
    def request(self, command: RequestLegacyJobCommand) -> LegacyJobRequestResult:
        """Persist the QUEUED transition and LegacyJobRequested outbox row atomically."""


class RequestLegacyJob:
    def __init__(self, repository: LegacyJobRequestRepository) -> None:
        self._repository = repository

    def execute(self, command: RequestLegacyJobCommand) -> LegacyJobRequestResult:
        _validate(command)
        return self._repository.request(command)


def _validate(command: RequestLegacyJobCommand) -> None:
    if not command.actor_subject.strip():
        raise ValueError("actor_subject must not be blank")
    if len(command.trace_id) != 32 or any(char not in "0123456789abcdef" for char in command.trace_id.lower()):
        raise ValueError("trace_id must be a 32-character hexadecimal correlation identifier")
    require_transition(WorkflowState.READY, WorkflowState.QUEUED)
