from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from app.application.advance_workflow import AdvanceWorkflow, AdvanceWorkflowCommand, WorkflowTransitionResult
from app.domain.workflow import WorkflowState


@dataclass(frozen=True)
class OpenManualApprovalCommand:
    """Move a QA-passed render into the human-review boundary."""

    organization_id: uuid.UUID
    workflow_run_id: uuid.UUID
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass(frozen=True)
class ApproveManualReviewCommand:
    """Record the reviewer identity in the immutable workflow-step payload."""

    organization_id: uuid.UUID
    workflow_run_id: uuid.UUID
    reviewer_subject: str
    note: str | None = None
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)


class ManualApproval:
    """Small application boundary for the V1 human approval state transitions.

    Persistence, audit storage, and HTTP authorization remain adapters. This
    use case deliberately delegates every state change to the one canonical
    transition path so state-machine validation and idempotency stay central.
    """

    def __init__(self, workflow: AdvanceWorkflow) -> None:
        self._workflow = workflow

    def open(self, command: OpenManualApprovalCommand) -> WorkflowTransitionResult:
        return self._workflow.execute(
            AdvanceWorkflowCommand(
                organization_id=command.organization_id,
                workflow_run_id=command.workflow_run_id,
                expected_state=WorkflowState.RENDERED,
                target_state=WorkflowState.APPROVAL_PENDING,
                output_payload={"approval_status": "pending"},
                trace_id=command.trace_id,
            )
        )

    def approve(self, command: ApproveManualReviewCommand) -> WorkflowTransitionResult:
        reviewer_subject = command.reviewer_subject.strip()
        if not reviewer_subject:
            raise ValueError("reviewer_subject is required")
        return self._workflow.execute(
            AdvanceWorkflowCommand(
                organization_id=command.organization_id,
                workflow_run_id=command.workflow_run_id,
                expected_state=WorkflowState.APPROVAL_PENDING,
                target_state=WorkflowState.APPROVED,
                output_payload={
                    "approval_status": "approved",
                    "reviewer_subject": reviewer_subject,
                    "note": command.note,
                },
                trace_id=command.trace_id,
            )
        )
