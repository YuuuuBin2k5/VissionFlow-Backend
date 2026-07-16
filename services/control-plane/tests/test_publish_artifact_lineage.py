from __future__ import annotations

import os
import sys
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from alembic import command as alembic_command
from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker


SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.application.advance_workflow import AdvanceWorkflow
from app.application.begin_manual_publish import BeginManualPublish, BeginManualPublishCommand
from app.application.manual_approval import ApproveManualReviewCommand, ManualApproval
from app.domain.workflow import WorkflowState
from app.infrastructure.models import MediaAsset, Organization, OutboxEvent, PublishApproval, PublisherConnection, VideoProject, WorkflowRun
from app.infrastructure.workflow_progression_repository import SqlAlchemyWorkflowProgressionRepository


class PublishArtifactLineageTests(unittest.TestCase):
    """Approval and publish events must remain pinned to one persisted export."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.db_url = "postgresql+psycopg://postgres:postgres@localhost:5433/visionflow_test"
        os.environ.update({
            "VISIONFLOW_ALLOW_INSECURE_DB": "true",
            "DATABASE_URL": cls.db_url,
            "MIGRATION_DATABASE_URL": cls.db_url,
        })
        cls.engine = create_engine(cls.db_url)
        cls.Session = sessionmaker(bind=cls.engine)
        with cls.engine.connect() as connection:
            connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
            connection.commit()
        config = Config(str(SERVICE_ROOT / "alembic.ini"))
        config.set_main_option("sqlalchemy.url", cls.db_url)
        alembic_command.upgrade(config, "head")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()

    def setUp(self) -> None:
        self.session = self.Session()
        organization = Organization(slug=f"org-{uuid.uuid4().hex[:12]}", name="Lineage test")
        self.session.add(organization)
        self.session.flush()
        project = VideoProject(organization_id=organization.id, title="Export", brief="Review export")
        self.session.add(project)
        self.session.flush()
        self.organization_id = organization.id
        self.workflow_run = WorkflowRun(
            project_id=project.id,
            state=WorkflowState.APPROVAL_PENDING.value,
            idempotency_key=f"lineage-{uuid.uuid4().hex}",
        )
        self.session.add(self.workflow_run)
        self.session.commit()

    def tearDown(self) -> None:
        self.session.close()

    def test_approval_pins_export_and_publish_event_reuses_it(self) -> None:
        asset = MediaAsset(
            organization_id=self.organization_id,
            workflow_run_id=self.workflow_run.id,
            object_key=f"visionflow/{self.workflow_run.id}/exports/final.mp4",
            media_kind="final_export",
            content_type="video/mp4",
            byte_size=1024,
            checksum_sha256="a" * 64,
            metadata_json={"render_plan_hash": "b" * 64},
        )
        self.session.add(asset)
        self.session.commit()

        workflow = AdvanceWorkflow(SqlAlchemyWorkflowProgressionRepository(self.session))
        ManualApproval(workflow).approve(
            ApproveManualReviewCommand(self.organization_id, self.workflow_run.id, "reviewer-1", "looks good", "c" * 32)
        )
        BeginManualPublish(workflow).execute(
            BeginManualPublishCommand(
                self.organization_id, self.workflow_run.id, uuid.uuid4(), "youtube", "UC_test", "operator-1", trace_id="d" * 32
            )
        )

        approval = self.session.scalar(select(PublishApproval).where(PublishApproval.workflow_run_id == self.workflow_run.id))
        self.assertIsNotNone(approval)
        self.assertEqual(asset.id, approval.export_asset_id)
        event = self.session.scalar(
            select(OutboxEvent)
            .where(OutboxEvent.aggregate_id == self.workflow_run.id)
            .order_by(OutboxEvent.created_at.desc())
        )
        self.assertEqual(str(asset.id), event.payload["publish_artifact"]["asset_id"])
        self.assertEqual(asset.object_key, event.payload["publish_artifact"]["object_key"])

        connection = PublisherConnection(
            organization_id=self.organization_id,
            provider="youtube",
            provider_account_id="UC_lineage",
            display_name="Lineage channel",
            encrypted_refresh_token="encrypted",
            scopes={"granted": "youtube.upload"},
            status="active",
            connected_by_subject="operator-1",
        )
        self.session.add(connection)
        self.session.commit()
        from app.routers.integrations import _issue_youtube_manifest

        with patch("app.routers.integrations.PrivateObjectPreviewIssuer.from_env") as previews, patch(
            "app.routers.integrations.PublisherTokenCipher.from_env"
        ), patch("app.routers.integrations.YouTubePublisherSettings.from_env"), patch(
            "app.routers.integrations.YouTubeAccessTokenRefresher"
        ) as refresher:
            previews.return_value.issue_final_export.return_value = SimpleNamespace(download_url="https://object.example/final.mp4", expires_in_seconds=300)
            refresher.return_value.refresh.return_value = SimpleNamespace(value="access-token", expires_in_seconds=300)
            manifest = _issue_youtube_manifest(self.session, self.session.get(WorkflowRun, self.workflow_run.id), self.organization_id, connection.id)

        self.assertEqual("https://object.example/final.mp4", manifest.artifact_download_url)
        self.assertEqual(asset.byte_size, manifest.artifact_byte_size)
        self.assertEqual(asset.checksum_sha256, manifest.artifact_checksum_sha256)
        previews.return_value.issue_final_export.assert_called_once_with(workflow_run_id=self.workflow_run.id, object_key=asset.object_key)

    def test_approval_without_a_final_export_is_rejected(self) -> None:
        workflow = AdvanceWorkflow(SqlAlchemyWorkflowProgressionRepository(self.session))
        with self.assertRaisesRegex(ValueError, "persisted final export"):
            ManualApproval(workflow).approve(
                ApproveManualReviewCommand(self.organization_id, self.workflow_run.id, "reviewer-1", trace_id="e" * 32)
            )
        self.session.rollback()
        self.assertEqual(WorkflowState.APPROVAL_PENDING.value, self.session.get(WorkflowRun, self.workflow_run.id).state)
