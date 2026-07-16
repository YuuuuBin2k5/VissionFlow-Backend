from __future__ import annotations

import os
import sys
import unittest
import uuid
from pathlib import Path

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker


SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from alembic import command as alembic_command  # noqa: E402
from alembic.config import Config  # noqa: E402
from app.application.request_legacy_job import (  # noqa: E402
    LegacyJobRequestConflict,
    RequestLegacyJobCommand,
)
from app.domain.workflow import WorkflowState  # noqa: E402
from app.infrastructure.legacy_job_request_repository import SqlAlchemyLegacyJobRequestRepository  # noqa: E402
from app.infrastructure.models import (  # noqa: E402
    CommandReceipt,
    Organization,
    OutboxEvent,
    VideoProject,
    WorkflowRun,
    WorkflowStep,
)


class LegacyJobRequestRepositoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.db_url = "postgresql+psycopg://postgres:postgres@localhost:5433/visionflow_test"
        os.environ["VISIONFLOW_ALLOW_INSECURE_DB"] = "true"
        os.environ["DATABASE_URL"] = cls.db_url
        os.environ["MIGRATION_DATABASE_URL"] = cls.db_url
        cls.engine = create_engine(cls.db_url)
        cls.Session = sessionmaker(bind=cls.engine)
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
        self.session = self.Session()
        self._clear_tables()
        self.organization = Organization(slug=f"org-{uuid.uuid4().hex[:8]}", name="Test organization")
        self.session.add(self.organization)
        self.session.flush()
        self.project = VideoProject(organization_id=self.organization.id, title="Test", brief="Brief")
        self.session.add(self.project)
        self.session.flush()
        self.run = WorkflowRun(
            project_id=self.project.id,
            state=WorkflowState.READY.value,
            idempotency_key=f"create-{uuid.uuid4().hex}",
        )
        self.session.add(self.run)
        self.session.commit()

    def tearDown(self) -> None:
        self.session.close()

    def test_atomically_queues_run_and_writes_canonical_legacy_request_event(self) -> None:
        command = self._command()
        result = SqlAlchemyLegacyJobRequestRepository(self.session).request(command)

        self.assertTrue(result.changed)
        self.assertEqual(WorkflowState.QUEUED, result.state)
        verification = self.Session()
        run = verification.get(WorkflowRun, self.run.id)
        self.assertEqual(WorkflowState.QUEUED.value, run.state)
        event = verification.get(OutboxEvent, result.event_id)
        self.assertIsNotNone(event)
        self.assertEqual("visionflow.legacy_job.requested.v1", event.event_type)
        self.assertEqual(str(result.event_id), event.payload["event_id"])
        self.assertEqual(str(command.source_command_id), event.payload["source_command_id"])
        self.assertEqual(str(self.organization.id), event.payload["organization_id"])
        self.assertEqual(str(self.run.id), event.payload["workflow_run_id"])
        self.assertEqual(1, event.payload["event_version"])
        queue_step = verification.scalar(
            select(WorkflowStep).where(WorkflowStep.workflow_run_id == self.run.id, WorkflowStep.step_key == "queue")
        )
        self.assertEqual(1, queue_step.attempt_count)
        receipt = verification.scalar(select(CommandReceipt).where(CommandReceipt.idempotency_key == str(command.source_command_id)))
        self.assertEqual(str(result.event_id), receipt.result_payload["event_id"])
        verification.close()

    def test_identical_source_command_replays_without_extra_event(self) -> None:
        command = self._command()
        repository = SqlAlchemyLegacyJobRequestRepository(self.session)
        first = repository.request(command)
        replay = repository.request(command)
        self.assertTrue(first.changed)
        self.assertFalse(replay.changed)
        self.assertEqual(first.event_id, replay.event_id)
        verification = self.Session()
        events = verification.scalars(
            select(OutboxEvent).where(OutboxEvent.event_type == "visionflow.legacy_job.requested.v1")
        ).all()
        self.assertEqual(1, len(events))
        verification.close()

    def test_source_command_cannot_be_reused_for_another_workflow(self) -> None:
        command = self._command()
        repository = SqlAlchemyLegacyJobRequestRepository(self.session)
        repository.request(command)
        second_run = WorkflowRun(
            project_id=self.project.id,
            state=WorkflowState.READY.value,
            idempotency_key=f"create-{uuid.uuid4().hex}",
        )
        self.session.add(second_run)
        self.session.commit()
        conflicting = RequestLegacyJobCommand(
            organization_id=self.organization.id,
            workflow_run_id=second_run.id,
            source_command_id=command.source_command_id,
            actor_subject=command.actor_subject,
            trace_id=command.trace_id,
        )
        with self.assertRaisesRegex(LegacyJobRequestConflict, "source_command_id"):
            repository.request(conflicting)

    def _command(self) -> RequestLegacyJobCommand:
        return RequestLegacyJobCommand(
            organization_id=self.organization.id,
            workflow_run_id=self.run.id,
            source_command_id=uuid.uuid4(),
            actor_subject="service|visionflow-control-plane",
            trace_id=uuid.uuid4().hex,
        )

    def _clear_tables(self) -> None:
        with self.engine.connect() as conn:
            conn.execute(
                text(
                    "TRUNCATE TABLE workflow_audit_events, command_receipts, outbox_events, "
                    "workflow_steps, creative_scenes, creative_document_versions, creative_documents, "
                    "workflow_runs, video_projects, organizations CASCADE;"
                )
            )
            conn.commit()
