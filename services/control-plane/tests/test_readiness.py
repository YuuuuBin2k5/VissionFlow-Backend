import os
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.core.oidc import VerifiedIdentity
from app.infrastructure.models import (
    Base,
    Organization,
    User,
    OrganizationMembership,
    ProviderCredential,
    PublisherConnection,
    PromptTemplate
)
from app.infrastructure.repositories import SqlAlchemyShortFormReadinessRepository
from app.domain.authorization import ROLE_PERMISSIONS, OrganizationRole


class ReadinessApiTests(unittest.TestCase):
    db_url = "postgresql+psycopg://postgres:postgres@localhost:5433/visionflow_test"

    @classmethod
    def setUpClass(cls) -> None:
        os.environ["VISIONFLOW_ALLOW_INSECURE_DB"] = "true"
        os.environ["DATABASE_URL"] = cls.db_url
        os.environ["MIGRATION_DATABASE_URL"] = cls.db_url

        cls.engine = create_engine(cls.db_url)
        cls.Session = sessionmaker(bind=cls.engine)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()

    def setUp(self) -> None:
        self.session = self.Session()
        self._clear_tables()

        self.environment = {
            "DATABASE_URL": self.db_url,
            "VISIONFLOW_OBJECT_STORE_ENDPOINT": "https://s3.example.com",
            "VISIONFLOW_OBJECT_STORE_BUCKET": "my-bucket",
            "VISIONFLOW_OBJECT_STORE_ACCESS_KEY_ID": "somekey",
            "VISIONFLOW_OBJECT_STORE_SECRET_ACCESS_KEY": "somesecret",
            "GEMINI_API_KEY": "test-gemini-key",
            "PEXELS_API_KEY": "test-pexels-key",
        }
        self.env_patcher = patch.dict(os.environ, self.environment)
        self.env_patcher.start()

        # Seed default organization and user first (to satisfy memberships FK)
        self.org_id = uuid.uuid4()
        self.org = Organization(id=self.org_id, slug=f"org-{self.org_id.hex[:8]}", name="Test Org")
        self.session.add(self.org)

        self.user_subject = "oidc|authorized-producer"
        self.user = User(id=uuid.uuid4(), identity_subject=self.user_subject, email="prod@example.com")
        self.session.add(self.user)
        self.session.commit()

        # Now seed membership (producer role has WORKFLOW_VIEW)
        self.membership = OrganizationMembership(
            id=uuid.uuid4(),
            organization_id=self.org_id,
            user_id=self.user.id,
            role="producer"
        )
        self.session.add(self.membership)
        self.session.commit()

    def tearDown(self) -> None:
        self.session.close()
        self.env_patcher.stop()

    def _clear_tables(self) -> None:
        with self.engine.connect() as conn:
            conn.execute(
                text(
                    "TRUNCATE TABLE provider_credentials, publisher_connections, prompt_templates, "
                    "organization_memberships, users, organizations CASCADE;"
                )
            )
            conn.commit()

    def _client(self, identity_subject: str = "oidc|authorized-producer") -> TestClient:
        from app.main import app
        from app.routers.auth import require_identity
        from app.routers import system

        app.dependency_overrides[require_identity] = lambda: VerifiedIdentity(identity_subject, None, None)
        app.dependency_overrides[system.get_session] = lambda: self.session

        self.addCleanup(app.dependency_overrides.clear)
        return TestClient(app)

    # 1. Repository tests (True PostgreSQL Integration)
    def test_repository_checks_gemini_active(self) -> None:
        repository = SqlAlchemyShortFormReadinessRepository(self.session)
        self.assertFalse(repository.check_gemini_active(self.org_id))

        cred = ProviderCredential(
            id=uuid.uuid4(),
            organization_id=self.org_id,
            provider="gemini",
            label="Gemini Key",
            secret_ciphertext="ciphertext",
            secret_fingerprint="fingerprint",
            priority=1,
            status="active",
            created_by_subject="system"
        )
        self.session.add(cred)
        self.session.commit()

        self.assertTrue(repository.check_gemini_active(self.org_id))

    def test_repository_checks_stock_media_active(self) -> None:
        repository = SqlAlchemyShortFormReadinessRepository(self.session)
        self.assertEqual([], repository.check_stock_media_active(self.org_id))

        cred = ProviderCredential(
            id=uuid.uuid4(),
            organization_id=self.org_id,
            provider="pexels",
            label="Pexels Key",
            secret_ciphertext="ciphertext",
            secret_fingerprint="fingerprint",
            priority=1,
            status="active",
            created_by_subject="system"
        )
        self.session.add(cred)
        self.session.commit()

        self.assertEqual(["pexels"], repository.check_stock_media_active(self.org_id))

    def test_repository_checks_youtube_connection_active(self) -> None:
        repository = SqlAlchemyShortFormReadinessRepository(self.session)
        self.assertFalse(repository.check_youtube_connection_active(self.org_id))

        conn = PublisherConnection(
            id=uuid.uuid4(),
            organization_id=self.org_id,
            provider="youtube",
            provider_account_id="yt-channel-id",
            display_name="My Channel",
            encrypted_refresh_token="encrypted",
            connected_by_subject="system",
            status="active"
        )
        self.session.add(conn)
        self.session.commit()

        self.assertTrue(repository.check_youtube_connection_active(self.org_id))

    def test_repository_checks_prompts_baseline_active(self) -> None:
        repository = SqlAlchemyShortFormReadinessRepository(self.session)
        required = ["short_video_scene_planner", "short_video_visual_art_director"]

        status = repository.check_prompts_baseline_active(self.org_id, required)
        self.assertFalse(status.get("short_video_scene_planner", False))
        self.assertFalse(status.get("short_video_visual_art_director", False))

        prompt = PromptTemplate(
            id=uuid.uuid4(),
            organization_id=self.org_id,
            prompt_key="short_video_scene_planner",
            name="Planner",
            description="Short video scene planner",
            production_version=1
        )
        self.session.add(prompt)
        self.session.commit()

        status = repository.check_prompts_baseline_active(self.org_id, required)
        self.assertTrue(status.get("short_video_scene_planner"))
        self.assertFalse(status.get("short_video_visual_art_director", False))

    # 2. Authentication & True Membership integration tests
    def test_requires_bearer_authentication(self) -> None:
        from app.main import app
        self._client()
        app.dependency_overrides.clear()

        response = TestClient(app).get(
            f"/api/v1/organizations/{self.org_id}/readiness"
        )
        self.assertEqual(401, response.status_code)

    def test_authorized_member_succeeds(self) -> None:
        client = self._client(self.user_subject)
        response = client.get(
            f"/api/v1/organizations/{self.org_id}/readiness",
            headers={"Authorization": "Bearer token"}
        )
        self.assertEqual(200, response.status_code)

    def test_non_member_returns_403(self) -> None:
        non_member_subject = "oidc|random-stranger"
        # Stranger is a registered User in database but not in the organization memberships
        stranger = User(id=uuid.uuid4(), identity_subject=non_member_subject, email="stranger@example.com")
        self.session.add(stranger)
        self.session.commit()

        client = self._client(non_member_subject)
        response = client.get(
            f"/api/v1/organizations/{self.org_id}/readiness",
            headers={"Authorization": "Bearer token"}
        )
        self.assertEqual(403, response.status_code)
        self.assertIn("permission denied", response.json()["detail"].lower())

    def test_member_with_insufficient_role_returns_403(self) -> None:
        # Patch ROLE_PERMISSIONS to temporarily strip VIEWER of workflow:view permission
        original_permissions = ROLE_PERMISSIONS.copy()
        try:
            ROLE_PERMISSIONS[OrganizationRole.VIEWER] = frozenset()

            viewer_subject = "oidc|unprivileged-viewer"
            viewer = User(id=uuid.uuid4(), identity_subject=viewer_subject, email="viewer@example.com")
            self.session.add(viewer)
            self.session.commit()

            membership = OrganizationMembership(
                id=uuid.uuid4(),
                organization_id=self.org_id,
                user_id=viewer.id,
                role="viewer"
            )
            self.session.add(membership)
            self.session.commit()

            client = self._client(viewer_subject)
            response = client.get(
                f"/api/v1/organizations/{self.org_id}/readiness",
                headers={"Authorization": "Bearer token"}
            )
            self.assertEqual(403, response.status_code)
            self.assertIn("permission denied", response.json()["detail"].lower())
        finally:
            ROLE_PERMISSIONS.update(original_permissions)

    # 3. Capability responses & Configuration edge cases tests
    def test_returns_degraded_when_fully_configured_and_unknown_runner(self) -> None:
        # Seed Gemini + Stock credentials + Prompts + YouTube connection in PostgreSQL
        cred1 = ProviderCredential(
            id=uuid.uuid4(), organization_id=self.org_id, provider="gemini", label="G",
            secret_ciphertext="c", secret_fingerprint="f", priority=1, status="active", created_by_subject="sys"
        )
        cred2 = ProviderCredential(
            id=uuid.uuid4(), organization_id=self.org_id, provider="pexels", label="P",
            secret_ciphertext="c", secret_fingerprint="f", priority=1, status="active", created_by_subject="sys"
        )
        prompt1 = PromptTemplate(
            id=uuid.uuid4(), organization_id=self.org_id, prompt_key="short_video_scene_planner", name="P", description="d", production_version=1
        )
        prompt2 = PromptTemplate(
            id=uuid.uuid4(), organization_id=self.org_id, prompt_key="short_video_visual_art_director", name="D", description="d", production_version=1
        )
        conn = PublisherConnection(
            id=uuid.uuid4(), organization_id=self.org_id, provider="youtube", provider_account_id="acct", display_name="display",
            encrypted_refresh_token="enc", connected_by_subject="sys", status="active"
        )
        self.session.add_all([cred1, cred2, prompt1, prompt2, conn])
        self.session.commit()

        client = self._client()
        response = client.get(
            f"/api/v1/organizations/{self.org_id}/readiness",
            headers={"Authorization": "Bearer token"}
        )
        self.assertEqual(200, response.status_code)
        data = response.json()
        self.assertEqual("degraded", data["overall"])

        # Manual creative draft is always ready
        self.assertTrue(data["creation_ready"])
        self.assertTrue(data["ai_planning_ready"])
        self.assertTrue(data["render_prerequisites_ready"])
        self.assertFalse(data["render_dispatch_ready"])

        checks = {c["key"]: c for c in data["checks"]}
        self.assertEqual("ready", checks["creative_provider"]["state"])
        self.assertEqual("ready", checks["stock_media"]["state"])
        self.assertEqual("ready", checks["r2_storage"]["state"])
        self.assertEqual("unknown", checks["render_runner"]["state"])
        self.assertEqual("ready", checks["prompt_baseline"]["state"])
        self.assertEqual("ready", checks["youtube_connection"]["state"])

    def test_returns_blocked_when_gemini_missing(self) -> None:
        # Erase Gemini environment variable key
        env = self.environment.copy()
        if "GEMINI_API_KEY" in env:
            del env["GEMINI_API_KEY"]
        if "GEMINI_API_KEYS" in env:
            del env["GEMINI_API_KEYS"]

        with patch.dict(os.environ, env, clear=True):
            client = self._client()
            response = client.get(
                f"/api/v1/organizations/{self.org_id}/readiness",
                headers={"Authorization": "Bearer token"}
            )
        self.assertEqual(200, response.status_code)
        data = response.json()
        self.assertEqual("blocked", data["overall"])

        # Manual script is never blocked by lack of AI
        self.assertTrue(data["creation_ready"])
        self.assertFalse(data["ai_planning_ready"])

        checks = {c["key"]: c for c in data["checks"]}
        self.assertEqual("blocked", checks["creative_provider"]["state"])
        self.assertEqual("tab", checks["creative_provider"]["remediation"]["kind"])
        self.assertEqual("credential_vault", checks["creative_provider"]["remediation"]["target"])

    def test_returns_blocked_when_r2_config_fails(self) -> None:
        # Clear object storage variables to force complete config failure
        env = self.environment.copy()
        for k in ("VISIONFLOW_OBJECT_STORE_ENDPOINT", "VISIONFLOW_OBJECT_STORE_BUCKET", "VISIONFLOW_OBJECT_STORE_ACCESS_KEY_ID", "VISIONFLOW_OBJECT_STORE_SECRET_ACCESS_KEY"):
            if k in env:
                del env[k]

        with patch.dict(os.environ, env, clear=True):
            client = self._client()
            response = client.get(
                f"/api/v1/organizations/{self.org_id}/readiness",
                headers={"Authorization": "Bearer token"}
            )
        self.assertEqual(200, response.status_code)
        data = response.json()
        self.assertEqual("blocked", data["overall"])

        # R2 blocked doesn't block manual brief/script drafting
        self.assertTrue(data["creation_ready"])
        self.assertFalse(data["render_prerequisites_ready"])

        checks = {c["key"]: c for c in data["checks"]}
        self.assertEqual("blocked", checks["r2_storage"]["state"])
        # Safe detail check (no leakage, no traceback)
        self.assertEqual("Object storage configuration is incomplete.", checks["r2_storage"]["detail"])

    def test_returns_degraded_when_prompts_not_promoted(self) -> None:
        client = self._client()
        response = client.get(
            f"/api/v1/organizations/{self.org_id}/readiness",
            headers={"Authorization": "Bearer token"}
        )
        self.assertEqual(200, response.status_code)
        data = response.json()
        self.assertEqual("degraded", data["overall"])
        self.assertTrue(data["creation_ready"])

        checks = {c["key"]: c for c in data["checks"]}
        self.assertEqual("degraded", checks["prompt_baseline"]["state"])
        self.assertEqual("tab", checks["prompt_baseline"]["remediation"]["kind"])
        self.assertEqual("agent_prompts", checks["prompt_baseline"]["remediation"]["target"])

    def test_ensures_no_secrets_leak_in_response(self) -> None:
        client = self._client()
        response = client.get(
            f"/api/v1/organizations/{self.org_id}/readiness",
            headers={"Authorization": "Bearer token"}
        )
        text_content = response.text
        self.assertNotIn("somekey", text_content)
        self.assertNotIn("somesecret", text_content)


if __name__ == "__main__":
    unittest.main()
