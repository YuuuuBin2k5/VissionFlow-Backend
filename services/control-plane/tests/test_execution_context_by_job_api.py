"""VF-03.02a.2-R1 — Integration and unit tests for execution context by job API.
"""

from __future__ import annotations

import base64
import os
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker, Session

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.infrastructure.models import (
    Base,
    Organization,
    VideoProject,
    WorkflowRun,
    WorkflowStep,
)


def _make_rsa_key():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return pem


def _base_env(pem_bytes: bytes, db_url: str) -> dict[str, str]:
    return {
        "DATABASE_URL": db_url,
        "MIGRATION_DATABASE_URL": db_url,
        "VISIONFLOW_ALLOW_INSECURE_DB": "true",
        "API_PREFIX": "/api/v1",
        "VISIONFLOW_AUTH_PRIVATE_KEY_PEM_BASE64": base64.b64encode(pem_bytes).decode("ascii"),
        "VISIONFLOW_AUTH_ISSUER": "https://api.visionflow.example",
        "VISIONFLOW_AUTH_AUDIENCE": "visionflow-control-plane",
        "VISIONFLOW_AUTH_KEY_ID": "visionflow-test-key",
        "VISIONFLOW_AUTH_ACCESS_TOKEN_TTL_SECONDS": "900",
        "VISIONFLOW_WORKER_SUBJECT": "service|visionflow-intelligence-worker",
        "VISIONFLOW_INTAKE_SUBJECT": "service|visionflow-legacy-intake",
    }


class ExecutionContextByJobApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from alembic.config import Config
        from alembic import command as alembic_command

        cls.db_url = "postgresql+psycopg://postgres:postgres@localhost:5433/visionflow_test"
        cls.pem = _make_rsa_key()
        cls.env = _base_env(cls.pem, cls.db_url)

        cls.engine = create_engine(cls.db_url)
        cls.SessionFactory = sessionmaker(bind=cls.engine)

        alembic_cfg = Config(str(SERVICE_ROOT / "alembic.ini"))
        alembic_cfg.set_main_option("sqlalchemy.url", cls.db_url)

        with cls.engine.connect() as conn:
            conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE;"))
            conn.execute(text("CREATE SCHEMA public;"))
            conn.commit()

        alembic_command.upgrade(alembic_cfg, "head")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()

    def setUp(self) -> None:
        self.session = self.SessionFactory()
        self._clear_tables()

        self.org_id = uuid.uuid4()
        self.organization = Organization(
            id=self.org_id,
            slug=f"org-{self.org_id.hex[:8]}",
            name="Test Org",
        )
        self.session.add(self.organization)
        self.session.flush()

        from app.infrastructure.models import User, OrganizationMembership
        from app.domain.authorization import OrganizationRole

        self.worker_user = User(
            id=uuid.uuid4(),
            identity_subject="service|visionflow-intelligence-worker",
            email="worker@visionflow.example",
            display_name="Narration Worker",
        )
        self.session.add(self.worker_user)
        self.session.flush()

        self.membership = OrganizationMembership(
            organization_id=self.org_id,
            user_id=self.worker_user.id,
            role=OrganizationRole.SERVICE.value,
        )
        self.session.add(self.membership)

        self.project = VideoProject(
            organization_id=self.org_id,
            title="Test Project",
            brief="Test Brief",
        )
        self.session.add(self.project)
        self.session.flush()

        # Run with a mapped legacy_job_id
        self.run = WorkflowRun(
            project_id=self.project.id,
            state="PLANNING",
            idempotency_key="initial-run-creation-key-mapping-test",
            legacy_job_id="mysql-job-12345",
        )
        self.session.add(self.run)
        self.session.commit()

    def tearDown(self) -> None:
        self.session.close()

    def _clear_tables(self) -> None:
        with self.engine.connect() as conn:
            conn.execute(
                text(
                    "TRUNCATE TABLE workflow_audit_events, command_receipts, outbox_events, "
                    "workflow_steps, creative_scenes, creative_document_versions, "
                    "creative_documents, workflow_runs, video_projects, organization_memberships, "
                    "users, organizations CASCADE;"
                )
            )
            conn.commit()

    def _sign_token(self, subject: str, scopes: list[str] | None = None) -> str:
        with patch.dict(os.environ, self.env, clear=True):
            from app.core.internal_tokens import InternalAuthSettings, Rs256AccessTokenSigner
            settings = InternalAuthSettings.from_env()
            signer = Rs256AccessTokenSigner(settings)
            extra: dict = {}
            if scopes is not None:
                extra["scopes"] = scopes
            return signer.issue(
                subject=subject,
                session_id=f"session-{uuid.uuid4().hex[:8]}",
                extra_claims=extra if extra else None,
            )

    def _app_client(self) -> TestClient:
        """Build a TestClient wired to the disposable test database.

        Override get_session so the app uses our test engine instead of
        the production/placeholder engine cached by get_engine().lru_cache.
        """
        with patch.dict(os.environ, self.env, clear=True):
            from app.main import app
            from app.infrastructure.database import get_session

        engine = self.engine

        def _override_get_session():
            with Session(engine) as session:
                yield session

        app.dependency_overrides[get_session] = _override_get_session
        self.addCleanup(app.dependency_overrides.clear)
        return TestClient(app, raise_server_exceptions=False)

    def _url(self, legacy_job_id: str) -> str:
        return f"/api/v1/workflows/execution-context-by-job/{legacy_job_id}"

    def test_successful_lookup_with_active_attempt(self) -> None:
        # Create a script workflow step with attempt count 3
        step = WorkflowStep(
            workflow_run_id=self.run.id,
            step_key="script",
            state="PLANNING",
            attempt_count=3,
        )
        self.session.add(step)
        self.session.commit()

        token = self._sign_token("service|visionflow-intelligence-worker", ["workflow:narration:complete"])
        client = self._app_client()

        with patch.dict(os.environ, self.env, clear=True):
            response = client.get(
                self._url("mysql-job-12345"),
                params={"organization_id": str(self.org_id)},
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(200, response.status_code, msg=response.text)
        data = response.json()
        self.assertEqual(str(self.run.id), data["workflow_run_id"])
        self.assertEqual("mysql-job-12345", data["legacy_job_id"])
        self.assertEqual("PLANNING", data["state"])
        self.assertEqual(f"narration-{self.run.id}-attempt-3", data["narration_attempt_id"])
        self.assertTrue(data["has_active_attempt"])

        # Prove read-only (attempt_count does not change)
        db_session = self.SessionFactory()
        step_db = db_session.get(WorkflowStep, step.id)
        self.assertEqual(3, step_db.attempt_count)
        db_session.close()

    def test_successful_lookup_without_active_attempt(self) -> None:
        # No script step exists in DB
        token = self._sign_token("service|visionflow-intelligence-worker", ["workflow:narration:complete"])
        client = self._app_client()

        with patch.dict(os.environ, self.env, clear=True):
            response = client.get(
                self._url("mysql-job-12345"),
                params={"organization_id": str(self.org_id)},
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(200, response.status_code, msg=response.text)
        data = response.json()
        self.assertEqual(str(self.run.id), data["workflow_run_id"])
        self.assertEqual("mysql-job-12345", data["legacy_job_id"])
        self.assertIsNone(data["narration_attempt_id"])
        self.assertFalse(data["has_active_attempt"])

    def test_lookup_unknown_job_returns_404(self) -> None:
        token = self._sign_token("service|visionflow-intelligence-worker", ["workflow:narration:complete"])
        client = self._app_client()

        with patch.dict(os.environ, self.env, clear=True):
            response = client.get(
                self._url("unknown-job-999"),
                params={"organization_id": str(self.org_id)},
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(404, response.status_code)

    def test_unauthorized_identities_blocked(self) -> None:
        client = self._app_client()

        # 1. Intake service subject (blocked — context GET is only for worker)
        intake_token = self._sign_token("service|visionflow-legacy-intake", ["workflow:narration:complete"])
        with patch.dict(os.environ, self.env, clear=True):
            response = client.get(
                self._url("mysql-job-12345"),
                params={"organization_id": str(self.org_id)},
                headers={"Authorization": f"Bearer {intake_token}"},
            )
        self.assertEqual(403, response.status_code)

        # 2. Worker subject but missing capability scope
        missing_scope_token = self._sign_token("service|visionflow-intelligence-worker", ["workflow:view"])
        with patch.dict(os.environ, self.env, clear=True):
            response = client.get(
                self._url("mysql-job-12345"),
                params={"organization_id": str(self.org_id)},
                headers={"Authorization": f"Bearer {missing_scope_token}"},
            )
        self.assertEqual(403, response.status_code)

        # 3. User token (blocked)
        user_token = self._sign_token("local|user-123", ["workflow:narration:complete"])
        with patch.dict(os.environ, self.env, clear=True):
            response = client.get(
                self._url("mysql-job-12345"),
                params={"organization_id": str(self.org_id)},
                headers={"Authorization": f"Bearer {user_token}"},
            )
        self.assertEqual(403, response.status_code)


if __name__ == "__main__":
    unittest.main()
