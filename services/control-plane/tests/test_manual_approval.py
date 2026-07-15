import sys
import unittest
import uuid
from pathlib import Path


SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.application.advance_workflow import AdvanceWorkflow, AdvanceWorkflowCommand, WorkflowTransitionResult  # noqa: E402
from app.application.manual_approval import (  # noqa: E402
    ApproveManualReviewCommand,
    ManualApproval,
    OpenManualApprovalCommand,
)
from app.domain.workflow import WorkflowState  # noqa: E402


class FakeRepository:
    def __init__(self) -> None:
        self.commands: list[AdvanceWorkflowCommand] = []

    def advance(self, command: AdvanceWorkflowCommand) -> WorkflowTransitionResult:
        self.commands.append(command)
        return WorkflowTransitionResult(command.workflow_run_id, command.target_state, True)


class ManualApprovalTests(unittest.TestCase):
    def test_opens_then_approves_through_canonical_transition_path(self) -> None:
        repository = FakeRepository()
        approval = ManualApproval(AdvanceWorkflow(repository))
        organization_id, workflow_run_id = uuid.uuid4(), uuid.uuid4()

        approval.open(OpenManualApprovalCommand(organization_id, workflow_run_id, trace_id="a" * 32))
        result = approval.approve(
            ApproveManualReviewCommand(organization_id, workflow_run_id, " reviewer-42 ", "Ready", "b" * 32)
        )

        self.assertEqual(WorkflowState.APPROVED, result.state)
        self.assertEqual(
            [(WorkflowState.RENDERED, WorkflowState.APPROVAL_PENDING), (WorkflowState.APPROVAL_PENDING, WorkflowState.APPROVED)],
            [(command.expected_state, command.target_state) for command in repository.commands],
        )
        self.assertEqual("reviewer-42", repository.commands[-1].output_payload["reviewer_subject"])
