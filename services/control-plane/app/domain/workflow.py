from __future__ import annotations

from enum import StrEnum


class WorkflowState(StrEnum):
    DRAFT = "DRAFT"
    READY = "READY"
    QUEUED = "QUEUED"
    PLANNING = "PLANNING"
    SCRIPTED = "SCRIPTED"
    STORYBOARDED = "STORYBOARDED"
    ASSETS_READY = "ASSETS_READY"
    RENDERING = "RENDERING"
    QA_PENDING = "QA_PENDING"
    RENDERED = "RENDERED"
    APPROVAL_PENDING = "APPROVAL_PENDING"
    APPROVED = "APPROVED"
    PUBLISHING = "PUBLISHING"
    PUBLISHED = "PUBLISHED"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    CANCELED = "CANCELED"
    FAILED = "FAILED"


TERMINAL_STATES = frozenset({WorkflowState.PUBLISHED, WorkflowState.CANCELED, WorkflowState.FAILED})

ALLOWED_TRANSITIONS: dict[WorkflowState, frozenset[WorkflowState]] = {
    WorkflowState.DRAFT: frozenset({WorkflowState.READY, WorkflowState.CANCELED}),
    WorkflowState.READY: frozenset({WorkflowState.QUEUED, WorkflowState.CANCELED}),
    WorkflowState.QUEUED: frozenset({WorkflowState.PLANNING, WorkflowState.CANCELED, WorkflowState.FAILED}),
    WorkflowState.PLANNING: frozenset({WorkflowState.SCRIPTED, WorkflowState.RETRY_SCHEDULED, WorkflowState.FAILED}),
    WorkflowState.SCRIPTED: frozenset({WorkflowState.STORYBOARDED, WorkflowState.RETRY_SCHEDULED, WorkflowState.FAILED}),
    WorkflowState.STORYBOARDED: frozenset({WorkflowState.ASSETS_READY, WorkflowState.RETRY_SCHEDULED, WorkflowState.FAILED}),
    WorkflowState.ASSETS_READY: frozenset({WorkflowState.RENDERING, WorkflowState.RETRY_SCHEDULED, WorkflowState.FAILED}),
    WorkflowState.RENDERING: frozenset({WorkflowState.QA_PENDING, WorkflowState.RETRY_SCHEDULED, WorkflowState.FAILED}),
    WorkflowState.QA_PENDING: frozenset({WorkflowState.RENDERED, WorkflowState.RETRY_SCHEDULED, WorkflowState.FAILED}),
    WorkflowState.RENDERED: frozenset({WorkflowState.APPROVAL_PENDING, WorkflowState.RETRY_SCHEDULED, WorkflowState.FAILED}),
    WorkflowState.APPROVAL_PENDING: frozenset({WorkflowState.APPROVED, WorkflowState.CANCELED, WorkflowState.RETRY_SCHEDULED}),
    WorkflowState.APPROVED: frozenset({WorkflowState.PUBLISHING, WorkflowState.CANCELED}),
    WorkflowState.PUBLISHING: frozenset({WorkflowState.PUBLISHED, WorkflowState.RETRY_SCHEDULED, WorkflowState.FAILED}),
    WorkflowState.RETRY_SCHEDULED: frozenset({WorkflowState.QUEUED, WorkflowState.CANCELED, WorkflowState.FAILED}),
    WorkflowState.PUBLISHED: frozenset(),
    WorkflowState.CANCELED: frozenset(),
    WorkflowState.FAILED: frozenset(),
}


class InvalidWorkflowTransition(ValueError):
    """Raised when a workflow command attempts to violate the V1 state machine."""


def can_transition(current: WorkflowState, target: WorkflowState) -> bool:
    return target in ALLOWED_TRANSITIONS[current]


def require_transition(current: WorkflowState, target: WorkflowState) -> None:
    if not can_transition(current, target):
        raise InvalidWorkflowTransition(f"Cannot transition workflow from {current} to {target}")
