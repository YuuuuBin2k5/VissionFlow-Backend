from __future__ import annotations

import os
import sys
import unittest
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sqlalchemy.exc import IntegrityError


SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))


class _Rows:
    def __init__(self, rows: list[tuple[object, object]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[object, object]]:
        return self._rows


class _Session:
    def __init__(self, rows: list[tuple[object, object]]) -> None:
        self._rows = rows
        self.query = None

    def execute(self, query: object) -> _Rows:
        self.query = query
        return _Rows(self._rows)


class ReviewQueueApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.organization_id = uuid.uuid4()
        self.workflow_run_id = uuid.uuid4()
        self.project_id = uuid.uuid4()
        self.environment = {
            "DATABASE_URL": "postgresql+psycopg://placeholder:placeholder@localhost:5432/visionflow?sslmode=require"
        }

    def test_returns_only_the_minimal_review_projection_after_tenant_authorization(self) -> None:
        with patch.dict(os.environ, self.environment, clear=True):
            from app.core.oidc import VerifiedIdentity
            from app.routers.workflows import list_review_queue

        workflow = SimpleNamespace(
            id=self.workflow_run_id,
            state="APPROVAL_PENDING",
            created_at=datetime(2026, 7, 16, tzinfo=UTC),
        )
        project = SimpleNamespace(id=self.project_id, title="Vertical launch")
        session = _Session([(workflow, project)])
        identity = VerifiedIdentity("oidc|reviewer", None, None)

        with patch("app.routers.workflows.AuthorizeOrganization") as authorize:
            response = list_review_queue(self.organization_id, 50, identity, session)

        self.assertEqual(1, len(response.items))
        self.assertEqual(self.workflow_run_id, response.items[0].workflow_run_id)
        self.assertEqual("Vertical launch", response.items[0].title)
        self.assertEqual("workflow:view", authorize.return_value.require.call_args.args[2].value)
        self.assertIsNotNone(session.query)

    def test_rejects_unreadable_organization_before_querying(self) -> None:
        with patch.dict(os.environ, self.environment, clear=True):
            from app.core.oidc import VerifiedIdentity
            from app.routers.workflows import list_review_queue
            from fastapi import HTTPException

        session = _Session([])
        with patch("app.routers.workflows.AuthorizeOrganization") as authorize:
            authorize.return_value.require.side_effect = PermissionError("denied")
            with self.assertRaises(HTTPException) as raised:
                list_review_queue(self.organization_id, 50, VerifiedIdentity("oidc|blocked", None, None), session)

        self.assertEqual(403, raised.exception.status_code)
        self.assertIsNone(session.query)

    def test_only_accepts_a_youtube_publish_failure_for_retry(self) -> None:
        with patch.dict(os.environ, self.environment, clear=True):
            from app.routers.workflows import _is_youtube_publish_failure

        self.assertTrue(
            _is_youtube_publish_failure(
                SimpleNamespace(output_payload={"provider": "youtube", "failure_code": "UPLOAD_FAILED"})
            )
        )
        self.assertFalse(
            _is_youtube_publish_failure(
                SimpleNamespace(output_payload={"provider": "render", "failure_code": "RENDER_FAILED"})
            )
        )
        self.assertFalse(_is_youtube_publish_failure(None))

    def test_rejects_a_second_retry_while_the_first_is_active(self) -> None:
        with patch.dict(os.environ, self.environment, clear=True):
            from app.core.oidc import VerifiedIdentity
            from app.routers.workflows import CreatePublicationAttemptRequest, create_publication_attempt
            from app.domain.workflow import WorkflowState
            from fastapi import HTTPException

        workflow = SimpleNamespace(state=WorkflowState.FAILED.value)
        connection = SimpleNamespace(id=uuid.uuid4())
        failure = SimpleNamespace(output_payload={"provider": "youtube", "failure_code": "UPLOAD_FAILED"})
        active_attempt = SimpleNamespace(id=uuid.uuid4())
        session = MagicMock()
        session.scalar.side_effect = [workflow, connection, failure, active_attempt]

        with patch("app.routers.workflows.AuthorizeOrganization"):
            with self.assertRaises(HTTPException) as raised:
                create_publication_attempt(
                    self.workflow_run_id,
                    CreatePublicationAttemptRequest(
                        organization_id=self.organization_id,
                        publisher_connection_id=connection.id,
                    ),
                    VerifiedIdentity("local|operator", None, None),
                    session,
                )

        self.assertEqual(409, raised.exception.status_code)
        self.assertEqual("PUBLICATION_ATTEMPT_ALREADY_ACTIVE", raised.exception.detail)
        session.add.assert_not_called()

    def test_maps_database_uniqueness_race_to_a_safe_conflict(self) -> None:
        with patch.dict(os.environ, self.environment, clear=True):
            from app.core.oidc import VerifiedIdentity
            from app.domain.workflow import WorkflowState
            from app.routers.workflows import CreatePublicationAttemptRequest, create_publication_attempt
            from fastapi import HTTPException

        connection = SimpleNamespace(id=uuid.uuid4())
        session = MagicMock()
        session.scalar.side_effect = [
            SimpleNamespace(state=WorkflowState.FAILED.value),
            connection,
            SimpleNamespace(output_payload={"provider": "youtube", "failure_code": "UPLOAD_FAILED"}),
            None,
        ]
        session.scalars.return_value = []
        session.commit.side_effect = IntegrityError("insert", {}, Exception("unique index"))

        with patch("app.routers.workflows.AuthorizeOrganization"):
            with self.assertRaises(HTTPException) as raised:
                create_publication_attempt(
                    self.workflow_run_id,
                    CreatePublicationAttemptRequest(
                        organization_id=self.organization_id,
                        publisher_connection_id=connection.id,
                    ),
                    VerifiedIdentity("local|operator", None, None),
                    session,
                )

        self.assertEqual(409, raised.exception.status_code)
        self.assertEqual("PUBLICATION_ATTEMPT_ALREADY_ACTIVE", raised.exception.detail)
        session.rollback.assert_called_once()


if __name__ == "__main__":
    unittest.main()
