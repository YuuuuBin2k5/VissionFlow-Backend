import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))


class WorkflowApiAuthenticationTests(unittest.TestCase):
    def test_short_form_creation_requires_bearer_authentication(self) -> None:
        values = {
            "DATABASE_URL": "postgresql+psycopg://placeholder:placeholder@localhost:5432/visionflow?sslmode=require"
        }
        with patch.dict(os.environ, values, clear=True):
            from app.main import app

            response = TestClient(app).post(
                "/api/v1/workflows/short-form",
                headers={"Idempotency-Key": "short-form-request-0001"},
                json={
                    "organization_id": "00000000-0000-0000-0000-000000000001",
                    "title": "Test workflow",
                    "brief": "A real API must reject unauthenticated writes.",
                },
            )

        self.assertEqual(401, response.status_code)
        self.assertEqual("Bearer authentication is required", response.json()["detail"])
