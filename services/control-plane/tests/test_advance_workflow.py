import sys
import unittest
import uuid
from pathlib import Path


SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.application.advance_workflow import (  # noqa: E402
    AdvanceWorkflow,
    AdvanceWorkflowCommand,
    WorkflowTransitionResult,
)
from app.domain.workflow import InvalidWorkflowTransition, WorkflowState  # noqa: E402


class FakeRepository:
    def __init__(self) -> None:
        self.commands: list[AdvanceWorkflowCommand] = []

    def advance(self, command: AdvanceWorkflowCommand) -> WorkflowTransitionResult:
        self.commands.append(command)
        return WorkflowTransitionResult(command.workflow_run_id, command.target_state, changed=True)


class AdvanceWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = FakeRepository()
        self.use_case = AdvanceWorkflow(self.repository)

    def test_accepts_script_completion_after_planning(self) -> None:
        command = AdvanceWorkflowCommand(
            organization_id=uuid.uuid4(),
            workflow_run_id=uuid.uuid4(),
            expected_state=WorkflowState.PLANNING,
            target_state=WorkflowState.SCRIPTED,
            output_payload={"script": "A short, validated script."},
        )

        result = self.use_case.execute(command)

        self.assertEqual(WorkflowState.SCRIPTED, result.state)
        self.assertEqual([command], self.repository.commands)

    def test_rejects_skipping_from_planning_to_rendering(self) -> None:
        with self.assertRaises(InvalidWorkflowTransition):
            self.use_case.execute(
                AdvanceWorkflowCommand(
                    organization_id=uuid.uuid4(),
                    workflow_run_id=uuid.uuid4(),
                    expected_state=WorkflowState.PLANNING,
                    target_state=WorkflowState.RENDERING,
                )
            )

    def test_rejects_invalid_trace_id_before_repository(self) -> None:
        with self.assertRaisesRegex(ValueError, "32-character"):
            self.use_case.execute(
                AdvanceWorkflowCommand(
                    organization_id=uuid.uuid4(),
                    workflow_run_id=uuid.uuid4(),
                    expected_state=WorkflowState.QUEUED,
                    target_state=WorkflowState.PLANNING,
                    trace_id="trace",
                )
            )
        self.assertEqual([], self.repository.commands)
