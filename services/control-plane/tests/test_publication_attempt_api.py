"""PostgreSQL acceptance tests for the service-only YouTube retry boundary."""

from __future__ import annotations

import base64
import os
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker


SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.infrastructure.models import Organization, PublicationAttempt, PublisherConnection, VideoProject, WorkflowRun  # noqa: E402


def _rsa_key_pem() -> bytes:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())


def _env(pem: bytes, db_url: str) -> dict[str, str]:
    return {
        "DATABASE_URL": db_url,
        "MIGRATION_DATABASE_URL": db_url,
        "VISIONFLOW_ALLOW_INSECURE_DB": "true",
        "API_PREFIX": "/api/v1",
        "VISIONFLOW_AUTH_PRIVATE_KEY_PEM_BASE64": base64.b64encode(pem).decode("ascii"),
        "VISIONFLOW_AUTH_ISSUER": "https://api.visionflow.example",
        "VISIONFLOW_AUTH_AUDIENCE": "visionflow-control-plane",
        "VISIONFLOW_AUTH_KEY_ID": "visionflow-test-key",
        "VISIONFLOW_AUTH_ACCESS_TOKEN_TTL_SECONDS": "900",
        "VISIONFLOW_PUBLISHER_WORKER_SUBJECT": "service|visionflow-publisher",
    }


class PublicationAttemptApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from alembic import command
        from alembic.config import Config

        cls.db_url = "postgresql+psycopg://postgres:postgres@localhost:5433/visionflow_test"
        cls.pem = _rsa_key_pem()
        cls.env = _env(cls.pem, cls.db_url)
        cls.engine = create_engine(cls.db_url)
        cls.SessionFactory = sessionmaker(bind=cls.engine)
        with cls.engine.connect() as connection:
            connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
            connection.commit()
        config = Config(str(SERVICE_ROOT / "alembic.ini"))
        config.set_main_option("sqlalchemy.url", cls.db_url)
        with patch.dict(os.environ, cls.env, clear=True):
            command.upgrade(config, "head")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()

    def setUp(self) -> None:
        self.session = self.SessionFactory()
        self._truncate()
        self.organization = Organization(slug=f"retry-{uuid.uuid4().hex[:8]}", name="Retry test")
        self.session.add(self.organization)
        self.session.flush()
        self.project = VideoProject(organization_id=self.organization.id, title="Recovered short", brief="A retried YouTube short")
        self.session.add(self.project)
        self.session.flush()
        self.workflow = WorkflowRun(project_id=self.project.id, state="FAILED", idempotency_key=f"retry-{uuid.uuid4().hex}")
        self.connection = PublisherConnection(organization_id=self.organization.id, provider="youtube", provider_account_id=f"UC{uuid.uuid4().hex}", display_name="VisionFlow channel", encrypted_refresh_token="ciphertext", scopes={"granted": "youtube.upload"}, status="active", connected_by_subject="local|operator")
        self.session.add_all([self.workflow, self.connection])
        self.session.flush()
        self.attempt = PublicationAttempt(workflow_run_id=self.workflow.id, publisher_connection_id=self.connection.id, attempt_number=1, state="requested", requested_by_subject="local|operator")
        self.session.add(self.attempt)
        self.session.commit()

    def tearDown(self) -> None:
        self.session.close()

    def _truncate(self) -> None:
        with self.engine.connect() as connection:
            connection.execute(text("TRUNCATE TABLE publication_attempts, publisher_connections, workflow_steps, workflow_runs, video_projects, organizations CASCADE"))
            connection.commit()

    def _token(self) -> str:
        with patch.dict(os.environ, self.env, clear=True):
            from app.core.internal_tokens import InternalAuthSettings, Rs256AccessTokenSigner

            return Rs256AccessTokenSigner(InternalAuthSettings.from_env()).issue(
                subject="service|visionflow-publisher",
                session_id=f"publisher-{uuid.uuid4().hex}",
                extra_claims={"scopes": ["publish:execute"]},
            )

    def _client(self) -> TestClient:
        with patch.dict(os.environ, self.env, clear=True):
            from app.main import app
            from app.infrastructure.database import get_session

        engine = self.engine

        def override_get_session():
            with Session(engine) as session:
                yield session

        app.dependency_overrides[get_session] = override_get_session
        self.addCleanup(app.dependency_overrides.clear)
        return TestClient(app, raise_server_exceptions=False)

    def _manifest(self):
        from app.routers.integrations import YouTubePublishManifest

        return YouTubePublishManifest(
            workflow_run_id=self.workflow.id,
            publisher_connection_id=self.connection.id,
            title="Recovered short",
            description="A retried YouTube short",
            artifact_download_url="https://object.example/final.mp4",
            artifact_expires_in_seconds=300,
            artifact_byte_size=1024,
            artifact_checksum_sha256="a" * 64,
            access_token="short-lived-token",
            access_token_expires_in_seconds=300,
        )

    def test_claim_then_complete_persists_attempt_result_without_reopening_workflow(self) -> None:
        client = self._client()
        headers = {"Authorization": f"Bearer {self._token()}"}
        base = f"/api/v1/integrations/youtube/publication-attempts/{self.attempt.id}"
        with patch.dict(os.environ, self.env, clear=True), patch("app.routers.integrations._issue_youtube_manifest", return_value=self._manifest()):
            claim = client.post(f"{base}/claim", json={"organization_id": str(self.organization.id)}, headers=headers)
        self.assertEqual(200, claim.status_code, claim.text)
        lease_token = claim.json()["lease_token"]
        with patch.dict(os.environ, self.env, clear=True):
            complete = client.post(f"{base}/complete", json={"organization_id": str(self.organization.id), "publisher_connection_id": str(self.connection.id), "lease_token": lease_token, "video_id": "yt-video-1", "video_url": "https://www.youtube.com/watch?v=yt-video-1"}, headers=headers)
        self.assertEqual(200, complete.status_code, complete.text)
        db = self.SessionFactory()
        persisted = db.get(PublicationAttempt, self.attempt.id)
        workflow = db.get(WorkflowRun, self.workflow.id)
        self.assertEqual("succeeded", persisted.state)
        self.assertEqual("https://www.youtube.com/watch?v=yt-video-1", persisted.external_url)
        self.assertIsNone(persisted.lease_token)
        self.assertEqual("FAILED", workflow.state)
        db.close()

    def test_rejects_completion_with_an_invalid_lease(self) -> None:
        client = self._client()
        headers = {"Authorization": f"Bearer {self._token()}"}
        base = f"/api/v1/integrations/youtube/publication-attempts/{self.attempt.id}"
        with patch.dict(os.environ, self.env, clear=True), patch("app.routers.integrations._issue_youtube_manifest", return_value=self._manifest()):
            claim = client.post(f"{base}/claim", json={"organization_id": str(self.organization.id)}, headers=headers)
        self.assertEqual(200, claim.status_code, claim.text)
        with patch.dict(os.environ, self.env, clear=True):
            response = client.post(f"{base}/complete", json={"organization_id": str(self.organization.id), "publisher_connection_id": str(self.connection.id), "lease_token": "x" * 64, "video_id": "yt-video-1", "video_url": "https://www.youtube.com/watch?v=yt-video-1"}, headers=headers)
        self.assertEqual(409, response.status_code, response.text)

    def test_uploading_boundary_prevents_a_second_claim_after_lease_expiry(self) -> None:
        client = self._client()
        headers = {"Authorization": f"Bearer {self._token()}"}
        base = f"/api/v1/integrations/youtube/publication-attempts/{self.attempt.id}"
        with patch.dict(os.environ, self.env, clear=True), patch("app.routers.integrations._issue_youtube_manifest", return_value=self._manifest()):
            claim = client.post(f"{base}/claim", json={"organization_id": str(self.organization.id)}, headers=headers)
        self.assertEqual(200, claim.status_code, claim.text)
        lease_token = claim.json()["lease_token"]
        with patch.dict(os.environ, self.env, clear=True):
            marked = client.post(f"{base}/mark-uploading", json={"organization_id": str(self.organization.id), "publisher_connection_id": str(self.connection.id), "lease_token": lease_token}, headers=headers)
        self.assertEqual(200, marked.status_code, marked.text)
        db = self.SessionFactory()
        persisted = db.get(PublicationAttempt, self.attempt.id)
        self.assertEqual("uploading", persisted.state)
        persisted.lease_expires_at = None
        db.commit()
        db.close()
        with patch.dict(os.environ, self.env, clear=True):
            duplicate_claim = client.post(f"{base}/claim", json={"organization_id": str(self.organization.id)}, headers=headers)
        self.assertEqual(409, duplicate_claim.status_code, duplicate_claim.text)

    def test_database_permits_only_one_active_attempt_per_workflow(self) -> None:
        self.session.add(
            PublicationAttempt(
                workflow_run_id=self.workflow.id,
                publisher_connection_id=self.connection.id,
                attempt_number=2,
                state="claimed",
                requested_by_subject="local|operator",
            )
        )

        with self.assertRaises(IntegrityError):
            self.session.commit()
        self.session.rollback()

    def test_database_treats_uploading_as_an_active_attempt(self) -> None:
        self.attempt.state = "uploading"
        self.session.add(
            PublicationAttempt(
                workflow_run_id=self.workflow.id,
                publisher_connection_id=self.connection.id,
                attempt_number=2,
                state="requested",
                requested_by_subject="local|operator",
            )
        )
        with self.assertRaises(IntegrityError):
            self.session.commit()
        self.session.rollback()

    def test_tenant_mismatch_is_a_safe_not_found(self) -> None:
        client = self._client()
        headers = {"Authorization": f"Bearer {self._token()}"}
        with patch.dict(os.environ, self.env, clear=True):
            response = client.post(f"/api/v1/integrations/youtube/publication-attempts/{self.attempt.id}/claim", json={"organization_id": str(uuid.uuid4())}, headers=headers)
        self.assertEqual(404, response.status_code, response.text)


if __name__ == "__main__":
    unittest.main()
