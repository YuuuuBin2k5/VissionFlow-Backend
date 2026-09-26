from __future__ import annotations

import os
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch


SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))


class CreativeDocumentLockApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.environment = {
            "DATABASE_URL": "postgresql+psycopg://placeholder:placeholder@localhost:5432/visionflow?sslmode=require"
        }
        self.organization_id = uuid.uuid4()
        self.workflow_run_id = uuid.uuid4()

    def test_post_queue_lock_returns_latest_read_snapshot_instead_of_calling_missing_method(self) -> None:
        with patch.dict(os.environ, self.environment, clear=True):
            from app.core.oidc import VerifiedIdentity
            from app.routers.workflows import LockCreativeDocumentRequest, lock_creative_document

        snapshot = object()
        repository = MagicMock()
        repository.lock.side_effect = ValueError("Creative document can only be edited before queueing")
        repository.read.return_value = snapshot
        response = object()

        with (
            patch("app.routers.workflows.AuthorizeOrganization"),
            patch("app.routers.workflows.SqlAlchemyCreativeDocumentRepository", return_value=repository),
            patch("app.routers.workflows._creative_document_response", return_value=response),
        ):
            result = lock_creative_document(
                self.workflow_run_id,
                LockCreativeDocumentRequest(organization_id=self.organization_id, expected_revision=1),
                VerifiedIdentity("local|operator", None, None),
                MagicMock(),
            )

        self.assertIs(response, result)
        repository.read.assert_called_once_with(self.organization_id, self.workflow_run_id)

    def test_lock_requires_create_permission_and_does_not_disclose_document_on_denial(self) -> None:
        with patch.dict(os.environ, self.environment, clear=True):
            from app.core.oidc import VerifiedIdentity
            from app.routers.workflows import LockCreativeDocumentRequest, lock_creative_document
            from fastapi import HTTPException

        repository = MagicMock()
        with (
            patch("app.routers.workflows.AuthorizeOrganization") as authorize,
            patch("app.routers.workflows.SqlAlchemyCreativeDocumentRepository", return_value=repository),
        ):
            authorize.return_value.require.side_effect = PermissionError("denied")
            with self.assertRaises(HTTPException) as raised:
                lock_creative_document(
                    self.workflow_run_id,
                    LockCreativeDocumentRequest(organization_id=self.organization_id, expected_revision=1),
                    VerifiedIdentity("local|blocked", None, None),
                    MagicMock(),
                )

        self.assertEqual(403, raised.exception.status_code)
        repository.lock.assert_not_called()
        repository.read.assert_not_called()


if __name__ == "__main__":
    unittest.main()
