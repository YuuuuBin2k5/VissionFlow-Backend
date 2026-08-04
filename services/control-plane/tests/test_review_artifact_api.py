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


class _ScalarSession:
    def __init__(self, *values: object):
        self._values = iter(values)

    def scalar(self, _statement: object) -> object:
        return next(self._values)


class ReviewArtifactApiTests(unittest.TestCase):
    """Review previews must use persisted, tenant-scoped final-export lineage."""

    environment = {
        "DATABASE_URL": "postgresql+psycopg://placeholder:placeholder@localhost:5432/visionflow?sslmode=require"
    }

    def setUp(self) -> None:
        self.organization_id = uuid.uuid4()
        self.workflow_run_id = uuid.uuid4()

    def _client(self, session: object) -> TestClient:
        with patch.dict(os.environ, self.environment, clear=True):
            from app.core.oidc import VerifiedIdentity
            from app.main import app
            from app.routers import workflows
            from app.routers.auth import require_identity

        app.dependency_overrides[require_identity] = lambda: VerifiedIdentity("oidc|reviewer", None, None)
        app.dependency_overrides[workflows.get_session] = lambda: session
        self.addCleanup(app.dependency_overrides.clear)
        return TestClient(app)

    def test_issues_preview_from_persisted_final_export(self) -> None:
        artifact_key = f"visionflow/{self.workflow_run_id}/exports/final.mp4"
        session = _ScalarSession(
            SimpleNamespace(state="APPROVAL_PENDING"),
            SimpleNamespace(object_key=artifact_key),
        )
        ticket = SimpleNamespace(
            object_key=artifact_key,
            download_url="https://storage.example/preview",
            expires_in_seconds=300,
        )

        with patch("app.routers.workflows.AuthorizeOrganization") as authorize, patch(
            "app.routers.workflows.PrivateObjectPreviewIssuer.from_env"
        ) as issuer:
            issuer.return_value.issue_final_export.return_value = ticket
            response = self._client(session).get(
                f"/api/v1/workflows/{self.workflow_run_id}/review-artifact",
                params={"organization_id": str(self.organization_id)},
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual(artifact_key, response.json()["object_key"])
        authorize.return_value.require.assert_called_once()
        issuer.return_value.issue_final_export.assert_called_once_with(
            workflow_run_id=self.workflow_run_id,
            object_key=artifact_key,
        )

    def test_returns_not_found_when_no_persisted_final_export_exists(self) -> None:
        session = _ScalarSession(SimpleNamespace(state="APPROVAL_PENDING"), None)

        with patch("app.routers.workflows.AuthorizeOrganization") as authorize:
            response = self._client(session).get(
                f"/api/v1/workflows/{self.workflow_run_id}/review-artifact",
                params={"organization_id": str(self.organization_id)},
            )

        self.assertEqual(404, response.status_code)
        self.assertEqual("Review artifact not found", response.json()["detail"])
        authorize.return_value.require.assert_called_once()
