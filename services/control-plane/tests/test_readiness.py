import os
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.core.oidc import VerifiedIdentity
from app.infrastructure.overlay_uploads import OverlayUploadConfigurationError


class MockReadinessRepository:
    def __init__(self) -> None:
        self.gemini_active = True
        self.stocks_active = ["pexels"]
        self.youtube_active = True
        self.prompts_baseline = {
            "short_video_scene_planner": True,
            "short_video_visual_art_director": True
        }

    def check_gemini_active(self, organization_id: uuid.UUID) -> bool:
        return self.gemini_active

    def check_stock_media_active(self, organization_id: uuid.UUID) -> list[str]:
        return self.stocks_active

    def check_youtube_connection_active(self, organization_id: uuid.UUID) -> bool:
        return self.youtube_active

    def check_prompts_baseline_active(self, organization_id: uuid.UUID, required_keys: list[str]) -> dict[str, bool]:
        return self.prompts_baseline


class ReadinessApiTests(unittest.TestCase):
    environment = {
        "DATABASE_URL": "postgresql+psycopg://placeholder:placeholder@localhost:5432/visionflow?sslmode=require",
        "VISIONFLOW_OBJECT_STORE_ENDPOINT": "https://s3.example.com",
        "VISIONFLOW_OBJECT_STORE_BUCKET": "my-bucket",
        "VISIONFLOW_OBJECT_STORE_ACCESS_KEY_ID": "somekey",
        "VISIONFLOW_OBJECT_STORE_SECRET_ACCESS_KEY": "somesecret",
    }

    def setUp(self) -> None:
        self.organization_id = uuid.uuid4()
        self.mock_repo = MockReadinessRepository()
        self.env_patcher = patch.dict(os.environ, self.environment)
        self.env_patcher.start()

    def tearDown(self) -> None:
        self.env_patcher.stop()

    def _client(self) -> TestClient:
        from app.main import app
        from app.routers.auth import require_identity

        app.dependency_overrides[require_identity] = lambda: VerifiedIdentity("oidc|operator", None, None)
        app.dependency_overrides[require_identity] = lambda: VerifiedIdentity("oidc|operator", None, None)
        
        # Default session dependency override
        from app.routers import system
        app.dependency_overrides[system.get_session] = lambda: object()

        self.addCleanup(app.dependency_overrides.clear)
        return TestClient(app)

    def test_requires_bearer_authentication(self) -> None:
        from app.main import app
        # Clear require_identity override to test 401
        self._client()
        app.dependency_overrides.clear()
        
        response = TestClient(app).get(
            f"/api/v1/organizations/{self.organization_id}/readiness"
        )
        self.assertEqual(401, response.status_code)

    @patch("app.routers.system.AuthorizeOrganization")
    def test_wrong_tenant_or_unauthorized_returns_403(self, mock_auth) -> None:
        mock_auth.return_value.require.side_effect = PermissionError("caller is not a member of this organization")
        client = self._client()
        response = client.get(
            f"/api/v1/organizations/{self.organization_id}/readiness",
            headers={"Authorization": "Bearer token"}
        )
        self.assertEqual(403, response.status_code)
        self.assertIn("permission denied", response.json()["detail"].lower())

    @patch("app.routers.system.SqlAlchemyShortFormReadinessRepository")
    @patch("app.routers.system.AuthorizeOrganization")
    def test_returns_degraded_when_fully_configured_and_unknown_runner(self, mock_auth, mock_repo_class) -> None:
        mock_repo_class.return_value = self.mock_repo
        client = self._client()
        
        response = client.get(
            f"/api/v1/organizations/{self.organization_id}/readiness",
            headers={"Authorization": "Bearer token"}
        )
        
        self.assertEqual(200, response.status_code)
        data = response.json()
        self.assertEqual(str(self.organization_id), data["organization_id"])
        self.assertEqual("degraded", data["overall"])
        self.assertTrue(data["creation_ready"])
        self.assertFalse(data["render_dispatch_ready"])
        
        # Check all checks
        checks = {c["key"]: c for c in data["checks"]}
        self.assertEqual("ready", checks["creative_provider"]["state"])
        self.assertEqual("ready", checks["stock_media"]["state"])
        self.assertEqual("ready", checks["r2_storage"]["state"])
        self.assertEqual("unknown", checks["render_runner"]["state"])
        self.assertEqual("ready", checks["prompt_baseline"]["state"])
        self.assertEqual("ready", checks["youtube_connection"]["state"])

        # Remediation checking
        self.assertEqual("url", checks["render_runner"]["remediation"]["kind"])
        self.assertIn("visionflow-render-free.yml", checks["render_runner"]["remediation"]["target"])

    @patch("app.routers.system.SqlAlchemyShortFormReadinessRepository")
    @patch("app.routers.system.AuthorizeOrganization")
    def test_returns_blocked_when_gemini_missing(self, mock_auth, mock_repo_class) -> None:
        self.mock_repo.gemini_active = False
        mock_repo_class.return_value = self.mock_repo
        
        # Ensure env is empty for key
        env_with_no_gemini = self.environment.copy()
        if "GEMINI_API_KEY" in env_with_no_gemini:
            del env_with_no_gemini["GEMINI_API_KEY"]
        if "GEMINI_API_KEYS" in env_with_no_gemini:
            del env_with_no_gemini["GEMINI_API_KEYS"]

        with patch.dict(os.environ, env_with_no_gemini, clear=True):
            client = self._client()
            response = client.get(
                f"/api/v1/organizations/{self.organization_id}/readiness",
                headers={"Authorization": "Bearer token"}
            )
        
        self.assertEqual(200, response.status_code)
        data = response.json()
        self.assertEqual("blocked", data["overall"])
        self.assertFalse(data["creation_ready"])
        
        checks = {c["key"]: c for c in data["checks"]}
        self.assertEqual("blocked", checks["creative_provider"]["state"])
        self.assertEqual("tab", checks["creative_provider"]["remediation"]["kind"])
        self.assertEqual("credential_vault", checks["creative_provider"]["remediation"]["target"])

    @patch("app.routers.system.SqlAlchemyShortFormReadinessRepository")
    @patch("app.routers.system.AuthorizeOrganization")
    def test_returns_blocked_when_stock_media_missing(self, mock_auth, mock_repo_class) -> None:
        self.mock_repo.stocks_active = []
        mock_repo_class.return_value = self.mock_repo
        
        env_with_no_stocks = self.environment.copy()
        for k in ("PEXELS_API_KEY", "PIXABAY_API_KEY", "COVERR_API_KEY"):
            if k in env_with_no_stocks:
                del env_with_no_stocks[k]

        with patch.dict(os.environ, env_with_no_stocks, clear=True):
            client = self._client()
            response = client.get(
                f"/api/v1/organizations/{self.organization_id}/readiness",
                headers={"Authorization": "Bearer token"}
            )
        
        self.assertEqual(200, response.status_code)
        data = response.json()
        self.assertEqual("blocked", data["overall"])
        self.assertFalse(data["creation_ready"])
        
        checks = {c["key"]: c for c in data["checks"]}
        self.assertEqual("blocked", checks["stock_media"]["state"])

    @patch("app.routers.system.SqlAlchemyShortFormReadinessRepository")
    @patch("app.routers.system.AuthorizeOrganization")
    def test_returns_blocked_when_r2_config_fails(self, mock_auth, mock_repo_class) -> None:
        mock_repo_class.return_value = self.mock_repo
        
        # Patch OverlayUploadIssuer.from_env to raise configuration error
        with patch("app.application.get_short_form_readiness.OverlayUploadIssuer.from_env") as mock_from_env:
            mock_from_env.side_effect = OverlayUploadConfigurationError("Missing object storage setting: bucket")
            
            client = self._client()
            response = client.get(
                f"/api/v1/organizations/{self.organization_id}/readiness",
                headers={"Authorization": "Bearer token"}
            )
        
        self.assertEqual(200, response.status_code)
        data = response.json()
        self.assertEqual("blocked", data["overall"])
        self.assertFalse(data["creation_ready"])
        
        checks = {c["key"]: c for c in data["checks"]}
        self.assertEqual("blocked", checks["r2_storage"]["state"])
        self.assertIn("Missing object storage setting: bucket", checks["r2_storage"]["detail"])

    @patch("app.routers.system.SqlAlchemyShortFormReadinessRepository")
    @patch("app.routers.system.AuthorizeOrganization")
    def test_returns_blocked_when_prompts_not_promoted(self, mock_auth, mock_repo_class) -> None:
        self.mock_repo.prompts_baseline = {
            "short_video_scene_planner": True,
            "short_video_visual_art_director": False
        }
        mock_repo_class.return_value = self.mock_repo
        
        client = self._client()
        response = client.get(
            f"/api/v1/organizations/{self.organization_id}/readiness",
            headers={"Authorization": "Bearer token"}
        )
        
        self.assertEqual(200, response.status_code)
        data = response.json()
        self.assertEqual("blocked", data["overall"])
        
        checks = {c["key"]: c for c in data["checks"]}
        self.assertEqual("blocked", checks["prompt_baseline"]["state"])
        self.assertEqual("tab", checks["prompt_baseline"]["remediation"]["kind"])
        self.assertEqual("agent_prompts", checks["prompt_baseline"]["remediation"]["target"])

    @patch("app.routers.system.SqlAlchemyShortFormReadinessRepository")
    @patch("app.routers.system.AuthorizeOrganization")
    def test_returns_degraded_when_youtube_missing(self, mock_auth, mock_repo_class) -> None:
        self.mock_repo.youtube_active = False
        mock_repo_class.return_value = self.mock_repo
        
        client = self._client()
        response = client.get(
            f"/api/v1/organizations/{self.organization_id}/readiness",
            headers={"Authorization": "Bearer token"}
        )
        
        self.assertEqual(200, response.status_code)
        data = response.json()
        self.assertEqual("degraded", data["overall"])
        self.assertTrue(data["creation_ready"])
        
        checks = {c["key"]: c for c in data["checks"]}
        self.assertEqual("degraded", checks["youtube_connection"]["state"])
        self.assertEqual("tab", checks["youtube_connection"]["remediation"]["kind"])
        self.assertEqual("publication_queue", checks["youtube_connection"]["remediation"]["target"])

    @patch("app.routers.system.SqlAlchemyShortFormReadinessRepository")
    @patch("app.routers.system.AuthorizeOrganization")
    def test_ensures_no_secrets_leak_in_response(self, mock_auth, mock_repo_class) -> None:
        mock_repo_class.return_value = self.mock_repo
        client = self._client()
        
        response = client.get(
            f"/api/v1/organizations/{self.organization_id}/readiness",
            headers={"Authorization": "Bearer token"}
        )
        
        text = response.text
        self.assertNotIn("somekey", text)
        self.assertNotIn("somesecret", text)


if __name__ == "__main__":
    unittest.main()
