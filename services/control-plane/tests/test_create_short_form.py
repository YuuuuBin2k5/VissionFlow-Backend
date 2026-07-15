import sys
import unittest
import uuid
from pathlib import Path


SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.application.create_short_form import (  # noqa: E402
    CreateShortFormCommand,
    CreateShortFormWorkflow,
    WorkflowRunSummary,
)
from app.domain.workflow import WorkflowState  # noqa: E402


class FakeRepository:
    def __init__(self) -> None:
        self.commands: list[CreateShortFormCommand] = []

    def create_or_get_initial_run(self, command: CreateShortFormCommand) -> WorkflowRunSummary:
        self.commands.append(command)
        return WorkflowRunSummary(
            project_id=uuid.uuid4(),
            workflow_run_id=uuid.uuid4(),
            state=WorkflowState.DRAFT,
            created=True,
        )


class CreateShortFormWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = FakeRepository()
        self.use_case = CreateShortFormWorkflow(self.repository)

    def _command(self, **overrides: object) -> CreateShortFormCommand:
        values: dict[str, object] = {
            "organization_id": uuid.uuid4(),
            "title": "Summer product launch",
            "brief": "A concise creator-led product story.",
            "idempotency_key": "short-form-request-0001",
        }
        values.update(overrides)
        return CreateShortFormCommand(**values)  # type: ignore[arg-type]

    def test_opens_a_draft_short_form_run(self) -> None:
        result = self.use_case.execute(self._command())

        self.assertEqual(WorkflowState.DRAFT, result.state)
        self.assertTrue(result.created)
        self.assertEqual(1, len(self.repository.commands))

    def test_rejects_non_short_form_profile_in_v1(self) -> None:
        with self.assertRaisesRegex(ValueError, "short_vertical"):
            self.use_case.execute(self._command(format_profile="long_horizontal"))

    def test_rejects_short_idempotency_key_before_repository(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least 16"):
            self.use_case.execute(self._command(idempotency_key="too-short"))
        self.assertEqual([], self.repository.commands)
