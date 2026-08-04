"""VF-03.02a.2-R1 — Integration and unit tests for legacy job mapping API.
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
    Organization,
    VideoProject,
    WorkflowRun,
    WorkflowAuditEvent,
    OutboxEvent,
    CommandReceipt,
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


class LegacyJobMappingApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from alembic.config import Config
        from alembic import command as alembic_command

        cls.db_url = "postgresql+psycopg://postgres:postgres@localhost:5433/visionflow_test"
        cls.pem = _make_rsa_key()
        cls.env = _base_env(cls.pem, cls.db_url)

        cls.engine = create_engine(cls.db_url)
        cls.SessionFactory = sessionmaker(bind=cls.engine)

        # Run Alembic migrations programmatically
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

        self.intake_user = User(
            id=uuid.uuid4(),
            identity_subject="service|visionflow-legacy-intake",
            email="intake@visionflow.example",
            display_name="Intake Service",
        )
        self.session.add(self.intake_user)
        self.session.flush()

        self.membership = OrganizationMembership(
            organization_id=self.org_id,
            user_id=self.intake_user.id,
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

        self.run = WorkflowRun(
            project_id=self.project.id,
            state="PLANNING",
            idempotency_key="initial-run-creation-key-mapping-test",
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

    def _url(self, run_id: uuid.UUID) -> str:
        return f"/api/v1/workflows/{run_id}/legacy-job-mapping"

    def test_successful_mapping_registration(self) -> None:
        token = self._sign_token("service|visionflow-legacy-intake", ["workflow:legacy-mapping:register"])
        client = self._app_client()

        payload = {
            "organization_id": str(self.org_id),
            "legacy_source": "agentbot.orchestrator.v1",
            "legacy_job_id": "mysql-job-12345",
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "idempotency-key-mapping-01-new",
            "X-Request-ID": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4",
        }

        with patch.dict(os.environ, self.env, clear=True):
            response = client.post(self._url(self.run.id), json=payload, headers=headers)

        self.assertEqual(201, response.status_code, msg=response.text)
        data = response.json()
        self.assertEqual(str(self.run.id), data["workflow_run_id"])
        self.assertEqual("mysql-job-12345", data["legacy_job_id"])
        self.assertTrue(data["registered"])

        # Verify DB updates
        db_session = self.SessionFactory()
        run = db_session.get(WorkflowRun, self.run.id)
        self.assertEqual("mysql-job-12345", run.legacy_job_id)

        # Audit Event
        audit = db_session.scalar(select(WorkflowAuditEvent).where(WorkflowAuditEvent.workflow_run_id == self.run.id))
        self.assertIsNotNone(audit)
        self.assertEqual("register_legacy_job_mapping", audit.action)
        self.assertEqual("service|visionflow-legacy-intake", audit.actor_subject)

        # Outbox Event
        outbox = db_session.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_id == self.run.id))
        self.assertIsNotNone(outbox)
        self.assertEqual("visionflow.workflow_run.legacy_job_mapped.v1", outbox.event_type)
        self.assertEqual("mysql-job-12345", outbox.payload["legacy_job_id"])

        # Receipt
        receipt = db_session.scalar(
            select(CommandReceipt).where(CommandReceipt.idempotency_key == "idempotency-key-mapping-01-new")
        )
        self.assertIsNotNone(receipt)
        self.assertEqual("register_legacy_job_mapping", receipt.operation_type)
        db_session.close()

    def test_idempotent_replay_returns_200(self) -> None:
        token = self._sign_token("service|visionflow-legacy-intake", ["workflow:legacy-mapping:register"])
        client = self._app_client()

        payload = {
            "organization_id": str(self.org_id),
            "legacy_source": "agentbot.orchestrator.v1",
            "legacy_job_id": "mysql-job-12345",
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "idempotency-key-mapping-idempotent",
        }

        with patch.dict(os.environ, self.env, clear=True):
            # First write
            res1 = client.post(self._url(self.run.id), json=payload, headers=headers)
            self.assertEqual(201, res1.status_code, msg=res1.text)

            # Replay
            res2 = client.post(self._url(self.run.id), json=payload, headers=headers)
            self.assertEqual(200, res2.status_code, msg=res2.text)
            data = res2.json()
            self.assertEqual(str(self.run.id), data["workflow_run_id"])
            self.assertEqual("mysql-job-12345", data["legacy_job_id"])
            self.assertFalse(data["registered"])

    def test_idempotency_key_conflict_different_mapping(self) -> None:
        token = self._sign_token("service|visionflow-legacy-intake", ["workflow:legacy-mapping:register"])
        client = self._app_client()

        payload1 = {
            "organization_id": str(self.org_id),
            "legacy_source": "agentbot.orchestrator.v1",
            "legacy_job_id": "mysql-job-12345",
        }
        payload2 = {
            "organization_id": str(self.org_id),
            "legacy_source": "agentbot.orchestrator.v1",
            "legacy_job_id": "mysql-job-54321",
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "idempotency-key-shared-conflict",
        }

        with patch.dict(os.environ, self.env, clear=True):
            res1 = client.post(self._url(self.run.id), json=payload1, headers=headers)
            self.assertEqual(201, res1.status_code, msg=res1.text)

            res2 = client.post(self._url(self.run.id), json=payload2, headers=headers)
            self.assertEqual(409, res2.status_code)
            self.assertEqual("IDEMPOTENCY_KEY_CONFLICT", res2.json()["code"])

    def test_duplicate_mapping_to_different_run_returns_409(self) -> None:
        token = self._sign_token("service|visionflow-legacy-intake", ["workflow:legacy-mapping:register"])
        client = self._app_client()

        # Run 1 mapped to job-777
        payload1 = {
            "organization_id": str(self.org_id),
            "legacy_source": "agentbot.orchestrator.v1",
            "legacy_job_id": "job-777",
        }
        with patch.dict(os.environ, self.env, clear=True):
            res1 = client.post(
                self._url(self.run.id),
                json=payload1,
                headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "idempotency-key-key1"},
            )
            self.assertEqual(201, res1.status_code, msg=res1.text)

        # Create Run 2 via direct DB
        run2 = WorkflowRun(
            project_id=self.project.id,
            state="PLANNING",
            idempotency_key="run-2-idemp-key-mapping-test",
        )
        self.session.add(run2)
        self.session.commit()

        # Map Run 2 to same job-777
        payload2 = {
            "organization_id": str(self.org_id),
            "legacy_source": "agentbot.orchestrator.v1",
            "legacy_job_id": "job-777",
        }
        with patch.dict(os.environ, self.env, clear=True):
            res2 = client.post(
                self._url(run2.id),
                json=payload2,
                headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "idempotency-key-key2"},
            )
            self.assertEqual(409, res2.status_code)
            self.assertEqual("LEGACY_JOB_MAPPING_CONFLICT", res2.json()["code"])

    def test_overwrite_mapping_blocked(self) -> None:
        token = self._sign_token("service|visionflow-legacy-intake", ["workflow:legacy-mapping:register"])
        client = self._app_client()

        with patch.dict(os.environ, self.env, clear=True):
            # Map run to job-1
            res1 = client.post(
                self._url(self.run.id),
                json={
                    "organization_id": str(self.org_id),
                    "legacy_source": "agentbot.orchestrator.v1",
                    "legacy_job_id": "job-1",
                },
                headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "idempotency-key-overwrite-1"},
            )
            self.assertEqual(201, res1.status_code, msg=res1.text)

            # Map same run to job-2 (should be blocked)
            res2 = client.post(
                self._url(self.run.id),
                json={
                    "organization_id": str(self.org_id),
                    "legacy_source": "agentbot.orchestrator.v1",
                    "legacy_job_id": "job-2",
                },
                headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "idempotency-key-overwrite-2"},
            )
            self.assertEqual(409, res2.status_code)
            self.assertEqual("LEGACY_JOB_MAPPING_CONFLICT", res2.json()["code"])

    def test_unauthorized_service_subject_and_scope(self) -> None:
        client = self._app_client()
        payload = {
            "organization_id": str(self.org_id),
            "legacy_source": "agentbot.orchestrator.v1",
            "legacy_job_id": "mysql-job-12345",
        }

        # 1. Narration worker subject (blocked even if has scope)
        worker_token = self._sign_token("service|visionflow-intelligence-worker", ["workflow:legacy-mapping:register"])
        with patch.dict(os.environ, self.env, clear=True):
            response = client.post(
                self._url(self.run.id),
                json=payload,
                headers={"Authorization": f"Bearer {worker_token}", "Idempotency-Key": "idempotency-worker-check"},
            )
        self.assertEqual(403, response.status_code)
        self.assertEqual("PERMISSION_DENIED", response.json()["code"])

        # 2. Correct subject but missing scope
        no_scope_token = self._sign_token("service|visionflow-legacy-intake", [])
        with patch.dict(os.environ, self.env, clear=True):
            response = client.post(
                self._url(self.run.id),
                json=payload,
                headers={"Authorization": f"Bearer {no_scope_token}", "Idempotency-Key": "idempotency-scope-check"},
            )
        self.assertEqual(403, response.status_code)
        self.assertEqual("PERMISSION_DENIED", response.json()["code"])

        # 3. User token with correct scope (blocked since user role does not have this permission)
        user_token = self._sign_token("local|user-12345", ["workflow:legacy-mapping:register"])
        with patch.dict(os.environ, self.env, clear=True):
            response = client.post(
                self._url(self.run.id),
                json=payload,
                headers={"Authorization": f"Bearer {user_token}", "Idempotency-Key": "idempotency-user-check"},
            )
        self.assertEqual(403, response.status_code)
        self.assertEqual("PERMISSION_DENIED", response.json()["code"])


if __name__ == "__main__":
    unittest.main()
