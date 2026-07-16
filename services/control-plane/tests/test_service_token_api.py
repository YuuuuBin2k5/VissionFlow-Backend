from __future__ import annotations

import base64
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient


SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))


class ServiceTokenApiTests(unittest.TestCase):
    def test_worker_client_credentials_receive_a_short_lived_rs256_token(self) -> None:
        values = _environment()
        with patch.dict(os.environ, values, clear=True):
            from app.main import app

            response = TestClient(app).post(
                "/api/v1/auth/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": "visionflow-intelligence-worker",
                    "client_secret": "safe-test-worker-secret",
                    "audience": "visionflow-control-plane",
                },
            )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual("Bearer", payload["token_type"])
        self.assertEqual(900, payload["expires_in"])
        claims = jwt.decode(payload["access_token"], options={"verify_signature": False})
        self.assertEqual("service|visionflow-intelligence-worker", claims["sub"])
        self.assertEqual("service:visionflow-intelligence-worker", claims["sid"])

    def test_worker_client_credentials_reject_an_invalid_secret(self) -> None:
        values = _environment()
        with patch.dict(os.environ, values, clear=True):
            from app.main import app
            response = TestClient(app).post(
                "/api/v1/auth/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": "visionflow-intelligence-worker",
                    "client_secret": "wrong-secret",
                    "audience": "visionflow-control-plane",
                },
            )

        self.assertEqual(401, response.status_code)
        self.assertEqual("Client authentication is invalid", response.json()["detail"])

    def test_mapping_client_receives_only_mapping_scope(self) -> None:
        values = _environment() | {
            "VISIONFLOW_LEGACY_MAPPING_CLIENT_ID": "visionflow-legacy-intake",
            "VISIONFLOW_LEGACY_MAPPING_CLIENT_SECRET": "safe-test-intake-secret",
            "VISIONFLOW_LEGACY_MAPPING_SUBJECT": "service|visionflow-legacy-intake",
        }
        with patch.dict(os.environ, values, clear=True):
            from app.main import app

            response = TestClient(app).post(
                "/api/v1/auth/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": "visionflow-legacy-intake",
                    "client_secret": "safe-test-intake-secret",
                    "audience": "visionflow-control-plane",
                    "scope": "workflow:legacy-mapping:register",
                },
            )

        self.assertEqual(200, response.status_code)
        claims = jwt.decode(response.json()["access_token"], options={"verify_signature": False})
        self.assertEqual("service|visionflow-legacy-intake", claims["sub"])
        self.assertEqual(["workflow:legacy-mapping:register"], claims["scopes"])

    def test_client_credentials_rejects_scope_outside_client_grant(self) -> None:
        values = _environment()
        with patch.dict(os.environ, values, clear=True):
            from app.main import app

            response = TestClient(app).post(
                "/api/v1/auth/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": "visionflow-intelligence-worker",
                    "client_secret": "safe-test-worker-secret",
                    "audience": "visionflow-control-plane",
                    "scope": "workflow:legacy-mapping:register",
                },
            )

        self.assertEqual(400, response.status_code)
        self.assertEqual("Requested scope is not permitted for this client", response.json()["detail"])


def _environment() -> dict[str, str]:
    private_key = rsa.generate_private_key(public_exponent=65_537, key_size=2_048)
    pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return {
        "DATABASE_URL": "postgresql+psycopg://placeholder:placeholder@localhost:5432/visionflow?sslmode=require",
        "API_PREFIX": "/api/v1",
        "VISIONFLOW_AUTH_PRIVATE_KEY_PEM_BASE64": base64.b64encode(pem).decode("ascii"),
        "VISIONFLOW_AUTH_ISSUER": "https://api.visionflow.example",
        "VISIONFLOW_AUTH_AUDIENCE": "visionflow-control-plane",
        "VISIONFLOW_AUTH_KEY_ID": "visionflow-2026-01",
        "VISIONFLOW_AUTH_ACCESS_TOKEN_TTL_SECONDS": "900",
        "VISIONFLOW_WORKER_CLIENT_ID": "visionflow-intelligence-worker",
        "VISIONFLOW_WORKER_CLIENT_SECRET": "safe-test-worker-secret",
        "VISIONFLOW_WORKER_SUBJECT": "service|visionflow-intelligence-worker",
    }
