import os
import sys
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient


SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))


class _ScalarResults:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def all(self) -> list[object]:
        return self._values


class _ExecutionContextSession:
    def __init__(self, run: object | None, project: object | None, steps: list[object]) -> None:
        self._run = run
        self._project = project
        self._steps = steps
        self.get_calls = 0

    def scalar(self, statement: object) -> object | None:
        del statement
        return self._run

    def get(self, model: object, identity: object) -> object | None:
        del model, identity
        self.get_calls += 1
        return self._project

    def scalars(self, statement: object) -> _ScalarResults:
        del statement
        return _ScalarResults(self._steps)


class WorkflowExecutionContextApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.environment = {
            "DATABASE_URL": "postgresql+psycopg://placeholder:placeholder@localhost:5432/visionflow?sslmode=require"
        }
        self.organization_id = uuid.uuid4()
        self.workflow_run_id = uuid.uuid4()

    def _client_for(self, session: _ExecutionContextSession) -> TestClient:
        with patch.dict(os.environ, self.environment, clear=True):
            from app.core.oidc import VerifiedIdentity
            from app.main import app
            from app.routers import workflows
            from app.routers.auth import require_identity

        app.dependency_overrides[require_identity] = lambda: VerifiedIdentity("oidc|worker", None, None)
        app.dependency_overrides[workflows.get_session] = lambda: session
        self.addCleanup(app.dependency_overrides.clear)
        return TestClient(app)

    def test_requires_bearer_authentication(self) -> None:
        with patch.dict(os.environ, self.environment, clear=True):
            from app.main import app

            response = TestClient(app).get(
                f"/api/v1/workflows/{self.workflow_run_id}/execution-context",
                params={"organization_id": str(self.organization_id)},
            )

        self.assertEqual(401, response.status_code)

    def test_returns_only_the_requested_organization_workflow_context(self) -> None:
        run = SimpleNamespace(
            id=self.workflow_run_id,
            state="STORYBOARDED",
            project_id=uuid.uuid4(),
            input_payload={"voice_code": "en-US-JennyNeural"},
            prompt_manifest={"short-form.script": {"version": 3}},
        )
        project = SimpleNamespace(title="Product launch", brief="Explain the launch in 30 seconds.")
        steps = [
            SimpleNamespace(step_key="script", output_payload={"script": "A concise script."}),
            SimpleNamespace(step_key="storyboard", output_payload={"scenes": [{"id": "scene-01"}]}),
        ]
        session = _ExecutionContextSession(run, project, steps)

        with patch("app.routers.workflows.AuthorizeOrganization") as authorize:
            response = self._client_for(session).get(
                f"/api/v1/workflows/{self.workflow_run_id}/execution-context",
                params={"organization_id": str(self.organization_id)},
                headers={"Authorization": "Bearer service-token"},
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual("STORYBOARDED", response.json()["state"])
        self.assertEqual("Product launch", response.json()["intake"]["title"])
        self.assertEqual({"script": "A concise script."}, response.json()["steps"]["script"])
        self.assertEqual({"scenes": [{"id": "scene-01"}]}, response.json()["steps"]["storyboard"])
        authorize.return_value.require.assert_called_once()

    def test_returns_not_found_when_run_is_not_owned_by_requested_organization(self) -> None:
        session = _ExecutionContextSession(run=None, project=None, steps=[])

        with patch("app.routers.workflows.AuthorizeOrganization"):
            response = self._client_for(session).get(
                f"/api/v1/workflows/{self.workflow_run_id}/execution-context",
                params={"organization_id": str(self.organization_id)},
                headers={"Authorization": "Bearer service-token"},
            )

        self.assertEqual(404, response.status_code)
        self.assertEqual("Workflow run not found", response.json()["detail"])
        self.assertEqual(0, session.get_calls)


if __name__ == "__main__":
    unittest.main()
