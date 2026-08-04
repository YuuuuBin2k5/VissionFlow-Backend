import concurrent.futures
import os
import sys
import unittest
import uuid
from pathlib import Path

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from alembic.config import Config
from alembic import command as alembic_command

from app.application.record_narration_generated import (
    ActiveNarrationAttemptMissing,
    RecordNarrationGeneratedCommand,
    SceneCommandPayload,
    StaleNarrationAttempt,
    WorkflowStateConflict,
    IdempotencyKeyConflict,
    SourceMetadataPayload,
)
from app.domain.workflow import WorkflowState
from app.infrastructure.models import (
    Organization,
    CreativeDocument,
    CreativeDocumentVersion,
    CreativeScene,
    VideoProject,
    WorkflowRun,
    WorkflowStep,
    OutboxEvent,
    CommandReceipt,
    WorkflowAuditEvent,
)
from app.infrastructure.repositories import SqlAlchemyNarrationResultRepository


class SqlAlchemyNarrationResultRepositoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # Use the disposable PostgreSQL container running on port 5433
        cls.db_url = "postgresql+psycopg://postgres:postgres@localhost:5433/visionflow_test"
        os.environ["VISIONFLOW_ALLOW_INSECURE_DB"] = "true"
        os.environ["DATABASE_URL"] = cls.db_url
        os.environ["MIGRATION_DATABASE_URL"] = cls.db_url

        cls.engine = create_engine(cls.db_url)
        cls.Session = sessionmaker(bind=cls.engine)

        # Run Alembic migrations programmatically to set up the DB schema
        alembic_cfg = Config(str(SERVICE_ROOT / "alembic.ini"))
        alembic_cfg.set_main_option("sqlalchemy.url", cls.db_url)

        # Clean slate: recreate public schema
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
        self.repository = SqlAlchemyNarrationResultRepository(self.session)

        # Truncate tables between tests to keep them isolated
        self._clear_tables()

        self.org_id = uuid.uuid4()
        self.organization = Organization(
            id=self.org_id,
            slug=f"org-{self.org_id.hex[:8]}",
            name="Test Org",
        )
        self.session.add(self.organization)
        self.session.flush()

        self.project = VideoProject(
            organization_id=self.org_id,
            title="Test Project",
            brief="Test Brief",
        )
        self.session.add(self.project)
        self.session.flush()

        self.run = WorkflowRun(
            project_id=self.project.id,
            state=WorkflowState.PLANNING.value,
            idempotency_key="initial-run-creation-key-16-chars",
        )
        self.session.add(self.run)
        self.session.flush()

        self.step = WorkflowStep(
            workflow_run_id=self.run.id,
            step_key="script",
            state=WorkflowState.PLANNING.value,
            attempt_count=1,
        )
        self.session.add(self.step)
        self.session.commit()

        self.valid_scenes = [
            SceneCommandPayload("Narration 1", "Visual prompt 1", 5),
            SceneCommandPayload("Narration 2", "Visual prompt 2", 10),
            SceneCommandPayload("Narration 3", "Visual prompt 3", 15),
        ]
        self.valid_script = "This is a valid script that contains more than forty characters."

    def tearDown(self) -> None:
        self.session.close()

    def _clear_tables(self) -> None:
        # Truncate all tables containing test data to clean up the DB
        with self.engine.connect() as conn:
            conn.execute(
                text(
                    "TRUNCATE TABLE workflow_audit_events, command_receipts, outbox_events, "
                    "workflow_steps, creative_scenes, creative_document_versions, "
                    "creative_documents, workflow_runs, video_projects, organizations CASCADE;"
                )
            )
            conn.commit()

    def test_record_valid_narration_result(self) -> None:
        command = RecordNarrationGeneratedCommand(
            organization_id=self.org_id,
            workflow_run_id=self.run.id,
            idempotency_key="idempotency-key-narration-01",
            script=self.valid_script,
            scenes=self.valid_scenes,
            source_metadata=SourceMetadataPayload(provider="google", model="gemini-1.5-pro"),
            narration_attempt_id=f"narration-{self.run.id}-attempt-1",
            trace_id=uuid.uuid4().hex,
        )

        result = self.repository.record_narration_result(command)
        self.assertEqual(WorkflowState.SCRIPTED, result.state)
        self.assertTrue(result.changed)
        self.assertEqual(1, result.version)

        # Verify changes in DB
        db_session = self.Session()
        run = db_session.get(WorkflowRun, self.run.id)
        self.assertEqual(WorkflowState.SCRIPTED.value, run.state)

        doc = db_session.scalar(select(CreativeDocument).where(CreativeDocument.workflow_run_id == self.run.id))
        self.assertIsNotNone(doc)
        self.assertEqual(1, doc.revision)
        self.assertEqual(result.version_id, doc.active_version_id)

        version = db_session.get(CreativeDocumentVersion, result.version_id)
        self.assertEqual("locked", version.state)
        self.assertEqual("worker", version.source)
        self.assertEqual(self.valid_script, version.script)

        scenes = db_session.scalars(
            select(CreativeScene).where(CreativeScene.creative_document_version_id == version.id)
        ).all()
        self.assertEqual(3, len(scenes))
        self.assertEqual("Narration 1", scenes[0].narration)
        self.assertEqual("Visual prompt 2", scenes[1].visual_prompt)
        self.assertEqual(15, scenes[2].duration_seconds)

        step = db_session.scalar(
            select(WorkflowStep).where(
                WorkflowStep.workflow_run_id == self.run.id,
                WorkflowStep.step_key == "script",
            )
        )
        self.assertIsNotNone(step)
        # SCRIPTED step was updated from step_key="script" in DB
        self.assertEqual(WorkflowState.SCRIPTED.value, step.state)
        self.assertEqual("idempotency-key-narration-01", step.output_payload["idempotency_key"])

        event = db_session.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_id == self.run.id))
        self.assertIsNotNone(event)
        self.assertEqual("visionflow.workflow_run.state_changed.v1", event.event_type)
        self.assertEqual(WorkflowState.SCRIPTED.value, event.payload["to_state"])

        # Verify audit event in DB
        audit = db_session.scalar(select(WorkflowAuditEvent).where(WorkflowAuditEvent.workflow_run_id == self.run.id))
        self.assertIsNotNone(audit)
        self.assertEqual("complete_narration", audit.action)
        self.assertEqual(command.actor_subject, audit.actor_subject)
        self.assertEqual(result.version_id, audit.target_version_id)
        self.assertEqual(command.trace_id, audit.trace_id)

        # Verify command receipt in DB
        receipt = db_session.scalar(select(CommandReceipt).where(CommandReceipt.idempotency_key == command.idempotency_key))
        self.assertIsNotNone(receipt)
        self.assertEqual(command.organization_id, receipt.organization_id)
        self.assertEqual("complete_narration", receipt.operation_type)
        self.assertEqual(str(result.version_id), receipt.result_payload["version_id"])

        db_session.close()

    def test_duplicate_idempotency_returns_cached_summary(self) -> None:
        command = RecordNarrationGeneratedCommand(
            organization_id=self.org_id,
            workflow_run_id=self.run.id,
            idempotency_key="idempotency-key-narration-02",
            script=self.valid_script,
            scenes=self.valid_scenes,
            source_metadata=SourceMetadataPayload(provider="google", model="gemini-1.5-pro"),
            narration_attempt_id=f"narration-{self.run.id}-attempt-1",
            trace_id=uuid.uuid4().hex,
        )

        result1 = self.repository.record_narration_result(command)
        self.assertTrue(result1.changed)

        # Second execution with same idempotency key
        result2 = self.repository.record_narration_result(command)
        self.assertFalse(result2.changed)
        self.assertEqual(result1.version_id, result2.version_id)
        self.assertEqual(result1.version, result2.version)
        self.assertEqual(result1.state, result2.state)

    def test_global_idempotency_conflict_across_runs(self) -> None:
        command1 = RecordNarrationGeneratedCommand(
            organization_id=self.org_id,
            workflow_run_id=self.run.id,
            idempotency_key="shared-idempotency-key-999",
            script=self.valid_script,
            scenes=self.valid_scenes,
            source_metadata=SourceMetadataPayload(provider="google", model="gemini-1.5-pro"),
            narration_attempt_id=f"narration-{self.run.id}-attempt-1",
            trace_id=uuid.uuid4().hex,
        )
        self.repository.record_narration_result(command1)

        # Create second workflow run and step
        run2 = WorkflowRun(
            project_id=self.project.id,
            state=WorkflowState.PLANNING.value,
            idempotency_key="run-2-creation-key-16-chars",
        )
        self.session.add(run2)
        self.session.flush()
        step2 = WorkflowStep(
            workflow_run_id=run2.id,
            step_key="script",
            state=WorkflowState.PLANNING.value,
            attempt_count=1,
        )
        self.session.add(step2)
        self.session.commit()

        command2 = RecordNarrationGeneratedCommand(
            organization_id=self.org_id,
            workflow_run_id=run2.id,
            idempotency_key="shared-idempotency-key-999",
            script=self.valid_script,
            scenes=self.valid_scenes,
            source_metadata=SourceMetadataPayload(provider="google", model="gemini-1.5-pro"),
            narration_attempt_id=f"narration-{run2.id}-attempt-1",
            trace_id=uuid.uuid4().hex,
        )
        with self.assertRaisesRegex(IdempotencyKeyConflict, "already associated with a different operation"):
            self.repository.record_narration_result(command2)

    def test_rejects_non_planning_workflow_state(self) -> None:
        run2 = WorkflowRun(
            project_id=self.project.id,
            state=WorkflowState.READY.value,
            idempotency_key="run-ready-creation-key-16-chars",
        )
        self.session.add(run2)
        self.session.flush()
        step2 = WorkflowStep(
            workflow_run_id=run2.id,
            step_key="script",
            state=WorkflowState.READY.value,
            attempt_count=1,
        )
        self.session.add(step2)
        self.session.commit()

        command = RecordNarrationGeneratedCommand(
            organization_id=self.org_id,
            workflow_run_id=run2.id,
            idempotency_key="idempotency-key-ready-run-99",
            script=self.valid_script,
            scenes=self.valid_scenes,
            source_metadata=SourceMetadataPayload(provider="google", model="gemini-1.5-pro"),
            narration_attempt_id=f"narration-{run2.id}-attempt-1",
        )
        with self.assertRaisesRegex(WorkflowStateConflict, "expected 'PLANNING'"):
            self.repository.record_narration_result(command)

    def test_transactional_rollback_on_error(self) -> None:
        from unittest.mock import patch
        from sqlalchemy.exc import IntegrityError

        command = RecordNarrationGeneratedCommand(
            organization_id=self.org_id,
            workflow_run_id=self.run.id,
            idempotency_key="idempotency-key-failure-99",
            script=self.valid_script,
            scenes=self.valid_scenes,
            source_metadata=SourceMetadataPayload(provider="google", model="gemini-1.5-pro"),
            narration_attempt_id=f"narration-{self.run.id}-attempt-1",
        )

        with patch.object(self.session, "flush", side_effect=IntegrityError("mock fail", None, None)):
            with self.assertRaises(Exception):
                self.repository.record_narration_result(command)

        # Verify run state did not transition and no partial records were written
        db_session = self.Session()
        run = db_session.get(WorkflowRun, self.run.id)
        self.assertEqual(WorkflowState.PLANNING.value, run.state)

        doc = db_session.scalar(select(CreativeDocument).where(CreativeDocument.workflow_run_id == self.run.id))
        self.assertIsNone(doc)

        step = db_session.scalar(
            select(WorkflowStep).where(
                WorkflowStep.workflow_run_id == self.run.id,
                WorkflowStep.step_key == "script",
            )
        )
        # The step should remain PLANNING state since transaction rolled back
        self.assertEqual(WorkflowState.PLANNING.value, step.state)

        db_session.close()

    def test_concurrent_requests_idempotency(self) -> None:
        command = RecordNarrationGeneratedCommand(
            organization_id=self.org_id,
            workflow_run_id=self.run.id,
            idempotency_key="idempotency-key-concurrent-999",
            script=self.valid_script,
            scenes=self.valid_scenes,
            source_metadata=SourceMetadataPayload(provider="google", model="gemini-1.5-pro"),
            narration_attempt_id=f"narration-{self.run.id}-attempt-1",
            trace_id=uuid.uuid4().hex,
        )

        def run_command_in_thread():
            session = self.Session()
            repository = SqlAlchemyNarrationResultRepository(session)
            try:
                res = repository.record_narration_result(command)
                return res
            finally:
                session.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(run_command_in_thread) for _ in range(5)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        # Exactly one execution should have changed=True
        changed_count = sum(1 for r in results if r.changed)
        self.assertEqual(1, changed_count)

        # Verify database state: only 1 version and 1 audit event created
        db_session = self.Session()
        versions = db_session.scalars(select(CreativeDocumentVersion)).all()
        self.assertEqual(1, len(versions))

        audits = db_session.scalars(
            select(WorkflowAuditEvent).where(WorkflowAuditEvent.workflow_run_id == self.run.id)
        ).all()
        self.assertEqual(1, len(audits))
        db_session.close()

    def test_rejects_stale_narration_attempt(self) -> None:
        command = RecordNarrationGeneratedCommand(
            organization_id=self.org_id,
            workflow_run_id=self.run.id,
            idempotency_key="idempotency-key-stale-attempt-99",
            script=self.valid_script,
            scenes=self.valid_scenes,
            source_metadata=SourceMetadataPayload(provider="google", model="gemini-1.5-pro"),
            narration_attempt_id=f"narration-{self.run.id}-attempt-999", # Wrong attempt_count!
        )
        with self.assertRaises(StaleNarrationAttempt):
            self.repository.record_narration_result(command)

    def test_rejects_missing_active_attempt(self) -> None:
        # Delete step to simulate missing active attempt
        self.session.delete(self.step)
        self.session.commit()

        command = RecordNarrationGeneratedCommand(
            organization_id=self.org_id,
            workflow_run_id=self.run.id,
            idempotency_key="idempotency-key-missing-attempt-99",
            script=self.valid_script,
            scenes=self.valid_scenes,
            source_metadata=SourceMetadataPayload(provider="google", model="gemini-1.5-pro"),
            narration_attempt_id=f"narration-{self.run.id}-attempt-1",
        )
        with self.assertRaises(ActiveNarrationAttemptMissing):
            self.repository.record_narration_result(command)


if __name__ == "__main__":
    unittest.main()
