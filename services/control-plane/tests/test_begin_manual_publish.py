import sys
import unittest
import uuid
from pathlib import Path


SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.application.advance_workflow import AdvanceWorkflow, AdvanceWorkflowCommand, WorkflowTransitionResult  # noqa: E402
from app.application.begin_manual_publish import BeginManualPublish, BeginManualPublishCommand  # noqa: E402
from app.domain.workflow import WorkflowState  # noqa: E402


class FakeRepository:
    def __init__(self) -> None:
        self.commands: list[AdvanceWorkflowCommand] = []

    def advance(self, command: AdvanceWorkflowCommand) -> WorkflowTransitionResult:
        self.commands.append(command)
        return WorkflowTransitionResult(command.workflow_run_id, command.target_state, True)


class BeginManualPublishTests(unittest.TestCase):
    def test_starts_manual_publish_through_the_canonical_transition_path(self) -> None:
        repository = FakeRepository()
        publish = BeginManualPublish(AdvanceWorkflow(repository))
        organization_id, workflow_run_id = uuid.uuid4(), uuid.uuid4()

        result = publish.execute(
            BeginManualPublishCommand(
                organization_id=organization_id,
                workflow_run_id=workflow_run_id,
                requested_by_subject=" operator-7 ",
                note="Ready for the platform operator",
                trace_id="c" * 32,
            )
        )

        self.assertEqual(WorkflowState.PUBLISHING, result.state)
        self.assertEqual(1, len(repository.commands))
        command = repository.commands[0]
        self.assertEqual(organization_id, command.organization_id)
        self.assertEqual(WorkflowState.APPROVED, command.expected_state)
        self.assertEqual(WorkflowState.PUBLISHING, command.target_state)
        self.assertEqual("manual_publish_requested", command.output_payload["publish_status"])
        self.assertEqual("operator-7", command.output_payload["requested_by_subject"])

    def test_rejects_empty_requester(self) -> None:
        repository = FakeRepository()
        publish = BeginManualPublish(AdvanceWorkflow(repository))

        with self.assertRaisesRegex(ValueError, "requested_by_subject is required"):
            publish.execute(
                BeginManualPublishCommand(uuid.uuid4(), uuid.uuid4(), "   ", trace_id="d" * 32)
            )

        self.assertEqual([], repository.commands)
