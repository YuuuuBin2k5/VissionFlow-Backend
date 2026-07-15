import sys
import unittest
import uuid
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.application.record_narration_generated import (
    RecordNarrationGeneratedCommand,
    SceneCommandPayload,
    WorkflowStateConflict,
    IdempotencyKeyConflict,
)
from app.domain.workflow import WorkflowState
from app.infrastructure.models import (
    Base,
    CreativeDocument,
    CreativeDocumentVersion,
    CreativeScene,
    VideoProject,
    WorkflowRun,
    WorkflowStep,
    OutboxEvent,
)
from app.infrastructure.repositories import SqlAlchemyNarrationResultRepository

from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB

@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"


class SqlAlchemyNarrationResultRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        # Use an in-memory SQLite database for testing repository transactions
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.session = self.Session()
        self.repository = SqlAlchemyNarrationResultRepository(self.session)

        self.org_id = uuid.uuid4()
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
        self.session.commit()

        self.valid_scenes = [
            SceneCommandPayload("Narration 1", "Visual prompt 1", 5),
            SceneCommandPayload("Narration 2", "Visual prompt 2", 10),
            SceneCommandPayload("Narration 3", "Visual prompt 3", 15),
        ]
        self.valid_script = "This is a valid script that contains more than forty characters."

    def tearDown(self) -> None:
        self.session.close()
        Base.metadata.drop_all(self.engine)

    def test_record_valid_narration_result(self) -> None:
        command = RecordNarrationGeneratedCommand(
            organization_id=self.org_id,
            workflow_run_id=self.run.id,
            idempotency_key="idempotency-key-narration-01",
            script=self.valid_script,
            scenes=self.valid_scenes,
            source_metadata={"model": "gpt-4"},
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
        self.assertEqual(WorkflowState.SCRIPTED.value, step.state)
        self.assertEqual("idempotency-key-narration-01", step.output_payload["idempotency_key"])

        event = db_session.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_id == self.run.id))
        self.assertIsNotNone(event)
        self.assertEqual("visionflow.workflow_run.state_changed.v1", event.event_type)
        self.assertEqual(WorkflowState.SCRIPTED.value, event.payload["to_state"])

        db_session.close()

    def test_duplicate_idempotency_returns_cached_summary(self) -> None:
        command = RecordNarrationGeneratedCommand(
            organization_id=self.org_id,
            workflow_run_id=self.run.id,
            idempotency_key="idempotency-key-narration-02",
            script=self.valid_script,
            scenes=self.valid_scenes,
            source_metadata={"model": "gpt-4"},
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
            source_metadata={"model": "gpt-4"},
            trace_id=uuid.uuid4().hex,
        )
        self.repository.record_narration_result(command1)

        # Create second workflow run
        run2 = WorkflowRun(
            project_id=self.project.id,
            state=WorkflowState.PLANNING.value,
            idempotency_key="run-2-creation-key-16-chars",
        )
        self.session.add(run2)
        self.session.commit()

        command2 = RecordNarrationGeneratedCommand(
            organization_id=self.org_id,
            workflow_run_id=run2.id,
            idempotency_key="shared-idempotency-key-999",
            script=self.valid_script,
            scenes=self.valid_scenes,
            source_metadata={"model": "gpt-4"},
            trace_id=uuid.uuid4().hex,
        )
        with self.assertRaisesRegex(IdempotencyKeyConflict, "already associated with a different workflow run"):
            self.repository.record_narration_result(command2)

    def test_rejects_non_planning_workflow_state(self) -> None:
        run2 = WorkflowRun(
            project_id=self.project.id,
            state=WorkflowState.READY.value,
            idempotency_key="run-ready-creation-key-16-chars",
        )
        self.session.add(run2)
        self.session.commit()

        command = RecordNarrationGeneratedCommand(
            organization_id=self.org_id,
            workflow_run_id=run2.id,
            idempotency_key="idempotency-key-ready-run-99",
            script=self.valid_script,
            scenes=self.valid_scenes,
            source_metadata={},
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
            source_metadata={},
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

        step = db_session.scalar(select(WorkflowStep).where(WorkflowStep.workflow_run_id == self.run.id))
        self.assertIsNone(step)

        db_session.close()


if __name__ == "__main__":
    unittest.main()
