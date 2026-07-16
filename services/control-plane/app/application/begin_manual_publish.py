from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from app.application.advance_workflow import AdvanceWorkflow, AdvanceWorkflowCommand, WorkflowTransitionResult
from app.domain.workflow import WorkflowState


@dataclass(frozen=True)
class BeginManualPublishCommand:
    """Declare an approved artifact ready for a human-controlled publish action.

    The selected publisher connection is an opaque organization-owned ID. It
    deliberately never carries platform credentials; the future publisher
    adapter resolves credentials only inside the Control Plane boundary.
    """

    organization_id: uuid.UUID
    workflow_run_id: uuid.UUID
    publisher_connection_id: uuid.UUID
    publisher_provider: str
    publisher_account_id: str
    requested_by_subject: str
    note: str | None = None
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)


class BeginManualPublish:
    """Canonical boundary from approved content to manual publishing.

    Delegating to ``AdvanceWorkflow`` centralizes state-machine validation,
    locking, organization scoping, idempotency, and outbox publication. It
    deliberately does not perform platform automation.
    """

    def __init__(self, workflow: AdvanceWorkflow) -> None:
        self._workflow = workflow

    def execute(self, command: BeginManualPublishCommand) -> WorkflowTransitionResult:
        requested_by_subject = command.requested_by_subject.strip()
        if not requested_by_subject:
            raise ValueError("requested_by_subject is required")

        return self._workflow.execute(
            AdvanceWorkflowCommand(
                organization_id=command.organization_id,
                workflow_run_id=command.workflow_run_id,
                expected_state=WorkflowState.APPROVED,
                target_state=WorkflowState.PUBLISHING,
                output_payload={
                    "publish_status": "manual_publish_requested",
                    "publisher_connection_id": str(command.publisher_connection_id),
                    "publisher_provider": command.publisher_provider,
                    "publisher_account_id": command.publisher_account_id,
                    "requested_by_subject": requested_by_subject,
                    "note": command.note,
                },
                trace_id=command.trace_id,
            )
        )
