from __future__ import annotations

import os
import sys
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException


SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))


class ManualPublishIdempotencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.environment = {
            "DATABASE_URL": "postgresql+psycopg://placeholder:placeholder@localhost:5432/visionflow?sslmode=require"
        }
        self.organization_id = uuid.uuid4()
        self.workflow_id = uuid.uuid4()
        self.connection_id = uuid.uuid4()

    def request(self):
        from app.routers.workflows import BeginManualPublishRequest

        return BeginManualPublishRequest(
            organization_id=self.organization_id,
            publisher_connection_id=self.connection_id,
        )

    def identity(self):
        from app.core.oidc import VerifiedIdentity

        return VerifiedIdentity("oidc|publisher", None, None)

    def test_repeated_request_does_not_start_a_second_upload(self) -> None:
        with patch.dict(os.environ, self.environment, clear=True):
            from app.routers.workflows import begin_manual_publish

        session = MagicMock()
        session.scalar.side_effect = [
            SimpleNamespace(id=self.connection_id, provider="youtube", provider_account_id="UC123"),
            SimpleNamespace(id=self.workflow_id, state="PUBLISHING", prompt_manifest={}),
        ]
        with patch("app.routers.workflows.AuthorizeOrganization"), patch(
            "app.routers.workflows._process_publication_attempt_in_background"
        ) as process:
            response = begin_manual_publish(
                self.workflow_id, self.request(), request_id=None,
                identity=self.identity(), session=session,
            )

        self.assertEqual("PUBLISHING", response.state)
        self.assertFalse(response.changed)
        process.assert_not_called()

    def test_rejects_non_youtube_connection_before_upload(self) -> None:
        with patch.dict(os.environ, self.environment, clear=True):
            from app.routers.workflows import begin_manual_publish

        session = MagicMock()
        session.scalar.return_value = SimpleNamespace(
            id=self.connection_id, provider="tiktok", provider_account_id="tt123"
        )
        with patch("app.routers.workflows.AuthorizeOrganization"), patch(
            "app.routers.workflows._process_publication_attempt_in_background"
        ) as process:
            with self.assertRaises(HTTPException) as raised:
                begin_manual_publish(
                    self.workflow_id, self.request(), request_id=None,
                    identity=self.identity(), session=session,
                )

        self.assertEqual(422, raised.exception.status_code)
        process.assert_not_called()


if __name__ == "__main__":
    unittest.main()
