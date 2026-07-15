from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Protocol

from app.domain.workflow import WorkflowState, require_transition


class WorkflowStateConflict(RuntimeError):
    """Raised when a worker result was produced for a stale workflow state."""


@dataclass(frozen=True)
class AdvanceWorkflowCommand:
    organization_id: uuid.UUID
    workflow_run_id: uuid.UUID
    expected_state: WorkflowState
    target_state: WorkflowState
    output_payload: dict[str, object] = field(default_factory=dict)
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass(frozen=True)
class WorkflowTransitionResult:
    workflow_run_id: uuid.UUID
    state: WorkflowState
    changed: bool


class WorkflowProgressionRepository(Protocol):
    def advance(self, command: AdvanceWorkflowCommand) -> WorkflowTransitionResult:
        """Lock, validate and transition a workflow state atomically."""


class AdvanceWorkflow:
    """Single write path for all state progressions submitted by operators or workers."""

    def __init__(self, repository: WorkflowProgressionRepository) -> None:
        self._repository = repository

    def execute(self, command: AdvanceWorkflowCommand) -> WorkflowTransitionResult:
        if len(command.trace_id) != 32:
            raise ValueError("trace_id must be a 32-character correlation identifier")
        require_transition(command.expected_state, command.target_state)
        return self._repository.advance(command)
