from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Protocol

from app.domain.workflow import WorkflowState


class IdempotencyKeyConflict(RuntimeError):
    """Raised when a key belongs to a different organization and cannot be replayed safely."""


@dataclass(frozen=True)
class CreateShortFormCommand:
    """A validated request to open one on-demand short-form workflow."""

    organization_id: uuid.UUID
    title: str
    brief: str
    idempotency_key: str
    format_profile: str = "short_vertical"
    timezone: str = "Asia/Bangkok"
    prompt_manifest: dict[str, object] = field(default_factory=dict)
    input_payload: dict[str, object] = field(default_factory=dict)
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass(frozen=True)
class WorkflowRunSummary:
    project_id: uuid.UUID
    workflow_run_id: uuid.UUID
    state: WorkflowState
    created: bool


class ShortFormWorkflowRepository(Protocol):
    def create_or_get_initial_run(self, command: CreateShortFormCommand) -> WorkflowRunSummary:
        """Atomically create a DRAFT run, or return the prior idempotent result."""


class CreateShortFormWorkflow:
    """Application boundary for the Brief → approved short-form workflow."""

    def __init__(self, repository: ShortFormWorkflowRepository) -> None:
        self._repository = repository

    def execute(self, command: CreateShortFormCommand) -> WorkflowRunSummary:
        _validate(command)
        return self._repository.create_or_get_initial_run(command)


def _validate(command: CreateShortFormCommand) -> None:
    if not command.title.strip():
        raise ValueError("title must not be blank")
    if len(command.title.strip()) > 240:
        raise ValueError("title must be 240 characters or fewer")
    if not command.brief.strip():
        raise ValueError("brief must not be blank")
    if len(command.idempotency_key.strip()) < 16:
        raise ValueError("idempotency_key must be at least 16 characters")
    if len(command.idempotency_key) > 128:
        raise ValueError("idempotency_key must be 128 characters or fewer")
    if len(command.trace_id) != 32:
        raise ValueError("trace_id must be a 32-character correlation identifier")
    if command.format_profile != "short_vertical":
        raise ValueError("VisionFlow V1 only accepts the short_vertical format profile")
