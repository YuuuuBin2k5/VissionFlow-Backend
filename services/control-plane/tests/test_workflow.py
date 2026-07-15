import sys
import unittest
from pathlib import Path


SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.domain.workflow import InvalidWorkflowTransition, WorkflowState, can_transition, require_transition  # noqa: E402


class WorkflowPolicyTests(unittest.TestCase):
    def test_happy_path_requires_storyboard_before_assets(self) -> None:
        path = [
            WorkflowState.DRAFT,
            WorkflowState.READY,
            WorkflowState.QUEUED,
            WorkflowState.PLANNING,
            WorkflowState.SCRIPTED,
            WorkflowState.STORYBOARDED,
            WorkflowState.ASSETS_READY,
            WorkflowState.RENDERING,
            WorkflowState.QA_PENDING,
            WorkflowState.RENDERED,
            WorkflowState.APPROVAL_PENDING,
            WorkflowState.APPROVED,
            WorkflowState.PUBLISHING,
            WorkflowState.PUBLISHED,
        ]
        for current, target in zip(path, path[1:]):
            self.assertTrue(can_transition(current, target))

    def test_rendered_export_requires_approval_gate(self) -> None:
        self.assertFalse(can_transition(WorkflowState.RENDERED, WorkflowState.PUBLISHING))
        with self.assertRaises(InvalidWorkflowTransition):
            require_transition(WorkflowState.RENDERED, WorkflowState.PUBLISHING)

    def test_terminal_state_cannot_restart(self) -> None:
        self.assertFalse(can_transition(WorkflowState.PUBLISHED, WorkflowState.QUEUED))
