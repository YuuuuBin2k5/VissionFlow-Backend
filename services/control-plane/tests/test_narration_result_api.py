import os
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.domain.workflow import WorkflowState
from app.application.record_narration_generated import NarrationResultSummary
from app.domain.authorization import Permission


class NarrationResultApiTests(unittest.TestCase):
    environment = {
        "DATABASE_URL": "postgresql+psycopg://placeholder:placeholder@localhost:5432/visionflow?sslmode=require",
        "VISIONFLOW_ALLOW_INSECURE_DB": "true",
        "VISIONFLOW_WORKER_SUBJECT": "service|visionflow-intelligence-worker",
    }

    def setUp(self) -> None:
        self.patcher = patch.dict(os.environ, self.environment, clear=True)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

        self.organization_id = uuid.uuid4()
        self.workflow_run_id = uuid.uuid4()
        self.valid_payload = {
            "organization_id": str(self.organization_id),
            "idempotency_key": "idempotency-key-test-api-999",
            "script": "This is a valid narration script that is long enough.",
            "scenes": [
                {"narration": "Scene 1", "visual_prompt": "Prompt 1", "duration_seconds": 5},
                {"narration": "Scene 2", "visual_prompt": "Prompt 2", "duration_seconds": 10},
                {"narration": "Scene 3", "visual_prompt": "Prompt 3", "duration_seconds": 15},
            ],
            "source_metadata": {
                "provider": "openai",
                "model": "gpt-4",
            },
            "narration_attempt_id": "narration-test-attempt-1",
        }

    def _client(self) -> TestClient:
        with patch.dict(os.environ, self.environment, clear=True):
            from app.core.oidc import VerifiedIdentity
            from app.main import app
            from app.routers import workflows
            from app.routers.auth import require_identity

        app.dependency_overrides[require_identity] = lambda: VerifiedIdentity(
            subject="service|visionflow-intelligence-worker",
            email=None,
            display_name=None,
            scopes=["workflow:narration:complete"],
        )
        app.dependency_overrides[workflows.get_session] = lambda: object()
        self.addCleanup(app.dependency_overrides.clear)
        return TestClient(app)

    def test_requires_bearer_authentication(self) -> None:
        with patch.dict(os.environ, self.environment, clear=True):
            from app.main import app
            response = TestClient(app).post(
                f"/api/v1/workflows/{self.workflow_run_id}/complete-narration",
                json=self.valid_payload,
            )
        self.assertEqual(401, response.status_code)
        data = response.json()
        self.assertEqual("UNAUTHORIZED", data["code"])
        self.assertIn("trace_id", data)

    def test_complete_narration_calls_usecase_and_returns_summary(self) -> None:
        expected_summary = NarrationResultSummary(
            workflow_run_id=self.workflow_run_id,
            state=WorkflowState.SCRIPTED,
            changed=True,
            version_id=uuid.uuid4(),
            version=1,
        )

        with patch("app.routers.workflows.AuthorizeOrganization") as authorize, patch(
            "app.routers.workflows.SqlAlchemyNarrationResultRepository"
        ), patch(
            "app.routers.workflows.RecordNarrationGenerated"
        ) as use_case:
            use_case.return_value.execute.return_value = expected_summary
            response = self._client().post(
                f"/api/v1/workflows/{self.workflow_run_id}/complete-narration",
                headers={"Authorization": "Bearer service-token"},
                json=self.valid_payload,
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual("SCRIPTED", response.json()["state"])
        self.assertTrue(response.json()["changed"])
        self.assertEqual(str(expected_summary.version_id), response.json()["version_id"])
        self.assertEqual(1, response.json()["version"])
        authorize.return_value.require.assert_called_once_with(
            "service|visionflow-intelligence-worker",
            self.organization_id,
            Permission.WORKFLOW_NARRATION_COMPLETE,
        )

    def test_maps_permission_error_to_403(self) -> None:
        with patch("app.routers.workflows.AuthorizeOrganization") as authorize:
            authorize.return_value.require.side_effect = PermissionError("Caller is not authorized")
            response = self._client().post(
                f"/api/v1/workflows/{self.workflow_run_id}/complete-narration",
                headers={"Authorization": "Bearer service-token"},
                json=self.valid_payload,
            )
        self.assertEqual(403, response.status_code)
        data = response.json()
        self.assertEqual("PERMISSION_DENIED", data["code"])
        self.assertEqual("Organization permission denied", data["message"])
        self.assertIn("trace_id", data)
        self.assertEqual("Caller is not authorized", data["detail"])

    def test_maps_lookup_error_to_404(self) -> None:
        with patch("app.routers.workflows.AuthorizeOrganization"), patch(
            "app.routers.workflows.SqlAlchemyNarrationResultRepository"
        ), patch(
            "app.routers.workflows.RecordNarrationGenerated"
        ) as use_case:
            use_case.return_value.execute.side_effect = LookupError("Workflow run not found")
            response = self._client().post(
                f"/api/v1/workflows/{self.workflow_run_id}/complete-narration",
                headers={"Authorization": "Bearer service-token"},
                json=self.valid_payload,
            )
        self.assertEqual(404, response.status_code)
        data = response.json()
        self.assertEqual("NOT_FOUND", data["code"])
        self.assertEqual("Workflow run not found", data["message"])
        self.assertIn("trace_id", data)
        self.assertIsNone(data["detail"])

    def test_maps_state_conflict_to_409(self) -> None:
        from app.application.record_narration_generated import WorkflowStateConflict
        with patch("app.routers.workflows.AuthorizeOrganization"), patch(
            "app.routers.workflows.SqlAlchemyNarrationResultRepository"
        ), patch(
            "app.routers.workflows.RecordNarrationGenerated"
        ) as use_case:
            use_case.return_value.execute.side_effect = WorkflowStateConflict("expected PLANNING")
            response = self._client().post(
                f"/api/v1/workflows/{self.workflow_run_id}/complete-narration",
                headers={"Authorization": "Bearer service-token"},
                json=self.valid_payload,
            )
        self.assertEqual(409, response.status_code)
        data = response.json()
        self.assertEqual("WORKFLOW_STATE_CONFLICT", data["code"])
        self.assertEqual("expected PLANNING", data["message"])
        self.assertIsNone(data["detail"])

    def test_maps_validation_error_to_422(self) -> None:
        invalid_payload = self.valid_payload.copy()
        invalid_payload["script"] = "too short"

        response = self._client().post(
            f"/api/v1/workflows/{self.workflow_run_id}/complete-narration",
            headers={"Authorization": "Bearer service-token"},
            json=invalid_payload,
        )
        self.assertEqual(422, response.status_code)
        data = response.json()
        self.assertEqual("VALIDATION_ERROR", data["code"])
        self.assertIn("trace_id", data)

    def test_maps_unexpected_error_to_500_safe(self) -> None:
        with patch("app.routers.workflows.AuthorizeOrganization"), patch(
            "app.routers.workflows.SqlAlchemyNarrationResultRepository"
        ), patch(
            "app.routers.workflows.RecordNarrationGenerated"
        ) as use_case:
            use_case.return_value.execute.side_effect = RuntimeError("database connection failure or disk crash")
            response = self._client().post(
                f"/api/v1/workflows/{self.workflow_run_id}/complete-narration",
                headers={"Authorization": "Bearer service-token"},
                json=self.valid_payload,
            )
        self.assertEqual(500, response.status_code)
        data = response.json()
        self.assertEqual("INTERNAL_SERVER_ERROR", data["code"])
        self.assertEqual("An unexpected error occurred", data["message"])
        # Do not leak RuntimeErrors or trace details in detail field
        self.assertIsNone(data["detail"])
        self.assertIn("trace_id", data)


if __name__ == "__main__":
    unittest.main()
