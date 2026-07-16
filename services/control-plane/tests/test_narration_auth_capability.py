"""VF-03.01b — Auth capability integration tests for narration complete endpoint.

These tests use the REAL Rs256AccessTokenSigner and InternalAccessTokenVerifier
(not mocked) to prove the full chain:
  /auth/token -> signer -> JWT scopes claim -> require_identity -> capability check

Negative test cases:
  - No token (401)
  - User token without scopes (403, missing capability)
  - User token with local| prefix (403, user blocked)
  - Service token with wrong subject (403, subject mismatch)
  - Service token with correct subject but missing workflow:narration:complete scope (403)
  - Correct service token with all capabilities -> passes capability gate (200 or 409 from mocked use case)
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

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))


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


def _base_env(pem_bytes: bytes) -> dict[str, str]:
    return {
        "DATABASE_URL": "postgresql+psycopg://placeholder:placeholder@localhost:5432/visionflow?sslmode=require",
        "VISIONFLOW_ALLOW_INSECURE_DB": "true",
        "API_PREFIX": "/api/v1",
        "VISIONFLOW_AUTH_PRIVATE_KEY_PEM_BASE64": base64.b64encode(pem_bytes).decode("ascii"),
        "VISIONFLOW_AUTH_ISSUER": "https://api.visionflow.example",
        "VISIONFLOW_AUTH_AUDIENCE": "visionflow-control-plane",
        "VISIONFLOW_AUTH_KEY_ID": "visionflow-test-key",
        "VISIONFLOW_AUTH_ACCESS_TOKEN_TTL_SECONDS": "900",
        "VISIONFLOW_WORKER_CLIENT_ID": "visionflow-intelligence-worker",
        "VISIONFLOW_WORKER_CLIENT_SECRET": "safe-test-worker-secret",
        "VISIONFLOW_WORKER_SUBJECT": "service|visionflow-intelligence-worker",
    }


class NarrationAuthCapabilityTests(unittest.TestCase):
    """Integration tests using the real Rs256AccessTokenSigner and verifier."""

    def setUp(self) -> None:
        self.pem = _make_rsa_key()
        self.env = _base_env(self.pem)
        self.workflow_run_id = uuid.uuid4()
        self.organization_id = uuid.uuid4()
        self.valid_payload = {
            "organization_id": str(self.organization_id),
            "idempotency_key": "idempotency-key-auth-test-0001",
            "script": "This is a valid narration script that is long enough for testing.",
            "scenes": [
                {"narration": "Scene 1", "visual_prompt": "Prompt 1", "duration_seconds": 5},
                {"narration": "Scene 2", "visual_prompt": "Prompt 2", "duration_seconds": 10},
                {"narration": "Scene 3", "visual_prompt": "Prompt 3", "duration_seconds": 15},
            ],
            "source_metadata": {
                "provider": "google",
                "model": "gemini-1.5-pro",
            },
        }

    def _sign_token(self, subject: str, scopes: list[str] | None = None, session_id: str = "session-test") -> str:
        with patch.dict(os.environ, self.env, clear=True):
            from app.core.internal_tokens import InternalAuthSettings, Rs256AccessTokenSigner
            settings = InternalAuthSettings.from_env()
            signer = Rs256AccessTokenSigner(settings)
            extra: dict = {}
            if scopes is not None:
                extra["scopes"] = scopes
            return signer.issue(subject=subject, session_id=session_id, extra_claims=extra if extra else None)

    def _app_client(self) -> TestClient:
        with patch.dict(os.environ, self.env, clear=True):
            from app.main import app
        return TestClient(app, raise_server_exceptions=False)

    def _url(self) -> str:
        return f"/api/v1/workflows/{self.workflow_run_id}/complete-narration"

    def test_no_token_returns_401(self) -> None:
        client = self._app_client()
        with patch.dict(os.environ, self.env, clear=True):
            response = client.post(self._url(), json=self.valid_payload)
        self.assertEqual(401, response.status_code)
        data = response.json()
        self.assertEqual("UNAUTHORIZED", data["code"])
        self.assertIn("trace_id", data)

    def test_user_token_without_scopes_returns_403(self) -> None:
        # Real local| user token, no scopes claim at all
        token = self._sign_token(subject="local|user-00000000", scopes=None)
        client = self._app_client()
        with patch.dict(os.environ, self.env, clear=True):
            response = client.post(
                self._url(),
                json=self.valid_payload,
                headers={"Authorization": f"Bearer {token}"},
            )
        self.assertEqual(403, response.status_code)
        data = response.json()
        self.assertIn(data["code"], ("PERMISSION_DENIED",))
        self.assertIn("trace_id", data)

    def test_user_token_with_wrong_scope_returns_403(self) -> None:
        # Real local| user token with only a different scope
        token = self._sign_token(subject="local|user-00000000", scopes=["workflow:view"])
        client = self._app_client()
        with patch.dict(os.environ, self.env, clear=True):
            response = client.post(
                self._url(),
                json=self.valid_payload,
                headers={"Authorization": f"Bearer {token}"},
            )
        self.assertEqual(403, response.status_code)
        data = response.json()
        self.assertIn("trace_id", data)
        # Must not leak the scope details or internal error in response body
        self.assertNotIn("local|", str(data))

    def test_service_token_wrong_subject_returns_403(self) -> None:
        # Real service token but for a different worker identity
        token = self._sign_token(
            subject="service|other-worker",
            scopes=["workflow:narration:complete"],
            session_id="service:other-worker",
        )
        client = self._app_client()
        with patch.dict(os.environ, self.env, clear=True):
            response = client.post(
                self._url(),
                json=self.valid_payload,
                headers={"Authorization": f"Bearer {token}"},
            )
        self.assertEqual(403, response.status_code)
        data = response.json()
        self.assertEqual("PERMISSION_DENIED", data["code"])
        self.assertIn("trace_id", data)

    def test_service_token_missing_capability_returns_403(self) -> None:
        # Real service token for the correct worker subject but without the required scope
        token = self._sign_token(
            subject="service|visionflow-intelligence-worker",
            scopes=[],
            session_id="service:visionflow-intelligence-worker",
        )
        client = self._app_client()
        with patch.dict(os.environ, self.env, clear=True):
            response = client.post(
                self._url(),
                json=self.valid_payload,
                headers={"Authorization": f"Bearer {token}"},
            )
        self.assertEqual(403, response.status_code)
        data = response.json()
        self.assertEqual("PERMISSION_DENIED", data["code"])
        self.assertIn("trace_id", data)

    def test_correct_service_token_passes_capability_gate(self) -> None:
        # Real service token for the correct worker subject with required scope
        # Mock the use case and AuthorizeOrganization so we only verify capability gate passes
        token = self._sign_token(
            subject="service|visionflow-intelligence-worker",
            scopes=["workflow:narration:complete"],
            session_id="service:visionflow-intelligence-worker",
        )
        from app.application.record_narration_generated import NarrationResultSummary
        from app.domain.workflow import WorkflowState
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
            client = self._app_client()
            with patch.dict(os.environ, self.env, clear=True):
                response = client.post(
                    self._url(),
                    json=self.valid_payload,
                    headers={"Authorization": f"Bearer {token}"},
                )
        # 200 means capability gate passed and the use-case was invoked
        self.assertEqual(200, response.status_code)
        data = response.json()
        self.assertEqual("SCRIPTED", data["state"])

    def test_user_token_with_correct_scope_returns_403(self) -> None:
        # A user token with the correct scope must be blocked because the subject is a user (local|...)
        token = self._sign_token(subject="local|user-00000000", scopes=["workflow:narration:complete"])
        client = self._app_client()
        with patch.dict(os.environ, self.env, clear=True):
            response = client.post(
                self._url(),
                json=self.valid_payload,
                headers={"Authorization": f"Bearer {token}"},
            )
        self.assertEqual(403, response.status_code)
        data = response.json()
        self.assertEqual("PERMISSION_DENIED", data["code"])

    def test_external_non_service_token_with_correct_scope_returns_403(self) -> None:
        # An external OIDC user token with the correct scope must be blocked because the subject is not the worker
        token = self._sign_token(subject="oidc|external-user", scopes=["workflow:narration:complete"])
        client = self._app_client()
        with patch.dict(os.environ, self.env, clear=True):
            response = client.post(
                self._url(),
                json=self.valid_payload,
                headers={"Authorization": f"Bearer {token}"},
            )
        self.assertEqual(403, response.status_code)
        data = response.json()
        self.assertEqual("PERMISSION_DENIED", data["code"])

    def test_missing_worker_subject_configuration_returns_500_fail_closed(self) -> None:
        # If the expected subject is not configured in env, the request fails closed and returns 500
        token = self._sign_token(
            subject="service|visionflow-intelligence-worker",
            scopes=["workflow:narration:complete"],
            session_id="service:visionflow-intelligence-worker",
        )
        bad_env = self.env.copy()
        bad_env["VISIONFLOW_WORKER_SUBJECT"] = ""  # blank/missing config
        with patch("app.routers.workflows.AuthorizeOrganization"), patch(
            "app.routers.workflows.SqlAlchemyNarrationResultRepository"
        ), patch(
            "app.routers.workflows.RecordNarrationGenerated"
        ):
            with patch.dict(os.environ, bad_env, clear=True):
                from app.main import app
                client = TestClient(app, raise_server_exceptions=False)
                response = client.post(
                    self._url(),
                    json=self.valid_payload,
                    headers={"Authorization": f"Bearer {token}"},
                )
        self.assertEqual(500, response.status_code)
        data = response.json()
        self.assertEqual("INTERNAL_SERVER_ERROR", data["code"])
        self.assertEqual("An unexpected error occurred", data["message"])


if __name__ == "__main__":
    unittest.main()
