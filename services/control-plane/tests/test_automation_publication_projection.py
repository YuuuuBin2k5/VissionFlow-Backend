from __future__ import annotations

import os
import sys
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from pydantic import ValidationError


SERVICE_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SERVICE_ROOT))
sys.path.insert(0, str(BACKEND_ROOT))


class AutomationPublicationProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.environment = {
            "DATABASE_URL": "postgresql+psycopg://placeholder:placeholder@localhost:5432/visionflow?sslmode=require"
        }

    def reconcile(self, workflow_state: str, approval_policy: str = "REVIEW_REQUIRED"):
        with patch.dict(os.environ, self.environment, clear=True):
            from app.routers.automation_batches import _reconcile

        job = SimpleNamespace(
            id=uuid.uuid4(),
            production_run_id=str(uuid.uuid4()),
            state="PROCESSING",
            auto_publish_policy="AUTO_SCHEDULE",
            thumbnail_urls=[],
            selected_thumbnail_url=None,
            error_code=None,
            error_message=None,
        )
        workflow = SimpleNamespace(
            state=workflow_state,
            failure_code="YOUTUBE_UPLOAD_FAILED" if workflow_state == "FAILED" else None,
            failure_detail="upload failed" if workflow_state == "FAILED" else None,
        )
        batch = SimpleNamespace(id=uuid.uuid4(), state="RUNNING", approval_policy=approval_policy)
        session = MagicMock()
        session.scalars.return_value = [job]
        session.get.return_value = workflow

        projection = _reconcile(session, batch)[0]
        return projection, batch

    def test_approved_workflow_is_ready_for_auto_publish(self) -> None:
        (job, _, _, publication_state), batch = self.reconcile("APPROVED")

        self.assertEqual("COMPLETED", job.state)
        self.assertEqual("READY", publication_state)
        self.assertEqual("COMPLETED", batch.state)

    def test_approval_pending_workflow_is_not_publishable(self) -> None:
        (job, _, _, publication_state), _ = self.reconcile("APPROVAL_PENDING")

        self.assertEqual("REVIEW_PENDING", job.state)
        self.assertEqual("NOT_REQUESTED", publication_state)

    def test_active_publish_keeps_batch_non_terminal(self) -> None:
        (job, _, _, publication_state), batch = self.reconcile("PUBLISHING")

        self.assertEqual("PUBLISHING", job.state)
        self.assertEqual("PUBLISHING", publication_state)
        self.assertEqual("RUNNING", batch.state)

    def test_publish_failure_is_visible_on_automation_job(self) -> None:
        (job, _, _, publication_state), batch = self.reconcile("FAILED")

        self.assertEqual("FAILED", job.state)
        self.assertEqual("FAILED", publication_state)
        self.assertEqual("FAILED", batch.state)

    def test_rejects_unsupported_automatic_publish_platform(self) -> None:
        with patch.dict(os.environ, self.environment, clear=True):
            from app.routers.automation_batches import CreateAutomationBatchRequest

        with self.assertRaisesRegex(ValidationError, "supports YouTube only"):
            CreateAutomationBatchRequest(
                name="TikTok batch",
                approval_policy="AUTO_APPROVE",
                items=[{
                    "payload": {
                        "title": "Test",
                        "scenes": [
                            {"narration": "one"},
                            {"narration": "two"},
                            {"narration": "three"},
                        ],
                    }
                }],
                auto_schedule=True,
                schedule_platform="TIKTOK",
            )


if __name__ == "__main__":
    unittest.main()
