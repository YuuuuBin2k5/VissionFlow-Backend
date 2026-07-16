import os
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))


class _ApprovalDouble:
    opened_command: object | None = None
    approved_command: object | None = None

    def __init__(self, workflow: object) -> None:
        del workflow

    def open(self, command: object) -> object:
        from app.application.advance_workflow import WorkflowTransitionResult
        from app.domain.workflow import WorkflowState

        type(self).opened_command = command
        return WorkflowTransitionResult(command.workflow_run_id, WorkflowState.APPROVAL_PENDING, True)

    def approve(self, command: object) -> object:
        from app.application.advance_workflow import WorkflowTransitionResult
        from app.domain.workflow import WorkflowState

        type(self).approved_command = command
        return WorkflowTransitionResult(command.workflow_run_id, WorkflowState.APPROVED, True)


class _ManualPublishDouble:
    command: object | None = None

    def __init__(self, workflow: object) -> None:
        del workflow

    def execute(self, command: object) -> object:
        from app.application.advance_workflow import WorkflowTransitionResult
        from app.domain.workflow import WorkflowState

        type(self).command = command
        return WorkflowTransitionResult(command.workflow_run_id, WorkflowState.PUBLISHING, True)


class ManualApprovalApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.environment = {
            "DATABASE_URL": "postgresql+psycopg://placeholder:placeholder@localhost:5432/visionflow?sslmode=require"
        }
        self.organization_id = uuid.uuid4()
        self.workflow_run_id = uuid.uuid4()
        self.publisher_connection_id = uuid.uuid4()
        _ApprovalDouble.opened_command = None
        _ApprovalDouble.approved_command = None
        _ManualPublishDouble.command = None

    def _client(self) -> TestClient:
        with patch.dict(os.environ, self.environment, clear=True):
            from app.core.oidc import VerifiedIdentity
            from app.main import app
            from app.routers import workflows
            from app.routers.auth import require_identity

        app.dependency_overrides[require_identity] = lambda: VerifiedIdentity("oidc|reviewer-42", None, None)
        session = MagicMock()
        connection = MagicMock()
        connection.id = self.publisher_connection_id
        connection.provider = "youtube"
        connection.provider_account_id = "UC_channel_123"
        session.scalar.return_value = connection
        app.dependency_overrides[workflows.get_session] = lambda: session
        self.addCleanup(app.dependency_overrides.clear)
        return TestClient(app)

    def test_open_requires_workflow_advance_and_uses_canonical_manual_approval(self) -> None:
        with patch("app.routers.workflows.AuthorizeOrganization") as authorize, patch(
            "app.routers.workflows.ManualApproval", _ApprovalDouble
        ):
            response = self._client().post(
                f"/api/v1/workflows/{self.workflow_run_id}/approval/open",
                headers={"Authorization": "Bearer service-token", "X-Request-ID": "a" * 32},
                json={"organization_id": str(self.organization_id)},
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual("APPROVAL_PENDING", response.json()["state"])
        self.assertEqual(self.organization_id, _ApprovalDouble.opened_command.organization_id)
        self.assertEqual("a" * 32, _ApprovalDouble.opened_command.trace_id)
        self.assertEqual(1, authorize.return_value.require.call_count)
        self.assertEqual("workflow:advance", authorize.return_value.require.call_args.args[2].value)

    def test_approve_requires_publish_approval_and_derives_reviewer_from_oidc(self) -> None:
        with patch("app.routers.workflows.AuthorizeOrganization") as authorize, patch(
            "app.routers.workflows.ManualApproval", _ApprovalDouble
        ):
            response = self._client().post(
                f"/api/v1/workflows/{self.workflow_run_id}/approval/approve",
                headers={"Authorization": "Bearer reviewer-token"},
                json={"organization_id": str(self.organization_id), "note": "Approved for manual publishing."},
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual("APPROVED", response.json()["state"])
        self.assertEqual("oidc|reviewer-42", _ApprovalDouble.approved_command.reviewer_subject)
        self.assertEqual("Approved for manual publishing.", _ApprovalDouble.approved_command.note)
        self.assertEqual("publish:approve", authorize.return_value.require.call_args.args[2].value)

    def test_approval_rejects_members_without_required_organization_permission(self) -> None:
        with patch("app.routers.workflows.AuthorizeOrganization") as authorize, patch(
            "app.routers.workflows.ManualApproval", _ApprovalDouble
        ):
            authorize.return_value.require.side_effect = PermissionError("not a reviewer")
            response = self._client().post(
                f"/api/v1/workflows/{self.workflow_run_id}/approval/approve",
                headers={"Authorization": "Bearer producer-token"},
                json={"organization_id": str(self.organization_id)},
            )

        self.assertEqual(403, response.status_code)
        self.assertEqual("Organization permission denied", response.json()["detail"])
        self.assertIsNone(_ApprovalDouble.approved_command)

    def test_manual_publish_requires_execute_permission_and_uses_canonical_boundary(self) -> None:
        with patch("app.routers.workflows.AuthorizeOrganization") as authorize, patch(
            "app.routers.workflows.BeginManualPublish", _ManualPublishDouble
        ):
            response = self._client().post(
                f"/api/v1/workflows/{self.workflow_run_id}/publication/manual-dispatch",
                headers={"Authorization": "Bearer publisher-token", "X-Request-ID": "f" * 32},
                json={"organization_id": str(self.organization_id), "publisher_connection_id": str(self.publisher_connection_id), "note": "Operator accepted handoff."},
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual("PUBLISHING", response.json()["state"])
        self.assertEqual("oidc|reviewer-42", _ManualPublishDouble.command.requested_by_subject)
        self.assertEqual(self.publisher_connection_id, _ManualPublishDouble.command.publisher_connection_id)
        self.assertEqual("publish:execute", authorize.return_value.require.call_args.args[2].value)


if __name__ == "__main__":
    unittest.main()
