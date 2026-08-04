import os
import sys
import unittest
import uuid
from datetime import datetime, timedelta, UTC
from pathlib import Path
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.infrastructure.models import (
    Organization,
    CreativeSession,
    CreativeMessage,
    CreativeProposal,
    CreativeTurn,
    CreativeCommandReceipt,
    WorkflowRun,
    VideoProject,
    CreativeDocument,
)
from app.infrastructure.repositories import SqlAlchemyShortFormWorkflowRepository
from app.infrastructure.creative_document_repository import (
    SqlAlchemyCreativeDocumentRepository,
)
from app.application.create_short_form import CreateShortFormCommand


class SessionsPersistenceTests(unittest.TestCase):
    db_url = "postgresql+psycopg://postgres:postgres@localhost:5433/visionflow_test"

    @classmethod
    def setUpClass(cls) -> None:
        os.environ["VISIONFLOW_ALLOW_INSECURE_DB"] = "true"
        os.environ["DATABASE_URL"] = cls.db_url
        os.environ["MIGRATION_DATABASE_URL"] = cls.db_url

        cls.engine = create_engine(cls.db_url)
        cls.Session = sessionmaker(bind=cls.engine)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()

    def setUp(self) -> None:
        self.session = self.Session()
        self._clear_tables()

    def tearDown(self) -> None:
        self.session.rollback()
        self.session.close()

    def _clear_tables(self) -> None:
        # Clear test-specific tables to prevent cross-test contamination
        self.session.execute(text("TRUNCATE TABLE creative_command_receipts CASCADE;"))
        self.session.execute(text("TRUNCATE TABLE creative_turns CASCADE;"))
        self.session.execute(text("TRUNCATE TABLE creative_proposals CASCADE;"))
        self.session.execute(text("TRUNCATE TABLE creative_messages CASCADE;"))
        self.session.execute(text("TRUNCATE TABLE creative_sessions CASCADE;"))
        self.session.execute(text("TRUNCATE TABLE creative_scenes CASCADE;"))
        self.session.execute(text("TRUNCATE TABLE creative_document_versions CASCADE;"))
        self.session.execute(text("TRUNCATE TABLE creative_documents CASCADE;"))
        self.session.execute(text("TRUNCATE TABLE workflow_runs CASCADE;"))
        self.session.execute(text("TRUNCATE TABLE video_projects CASCADE;"))
        self.session.execute(text("TRUNCATE TABLE organizations CASCADE;"))
        self.session.commit()

    def _create_test_organization(self) -> uuid.UUID:
        org_id = uuid.uuid4()
        org = Organization(id=org_id, slug=f"org-slug-{org_id}", name="Test Session Org")
        self.session.add(org)
        self.session.flush()
        return org_id

    def test_migration_and_models_inserted_successfully(self) -> None:
        org_id = self._create_test_organization()

        creation_spec = {
            "title": "Stoic Philosophy in 60s",
            "brief": "A brief about Marcus Aurelius",
            "format_profile": "short_vertical",
            "timezone": "Asia/Bangkok",
            "language": "vi",
            "voice": "edge-nam-minh",
            "caption_preset": "clean_news",
            "visual_preset": "clean_explainer",
            "duration_seconds": 60,
        }

        # 1. Insert Session
        session = CreativeSession(
            organization_id=org_id,
            creation_spec=creation_spec,
            revision=0,
        )
        self.session.add(session)
        self.session.flush()

        self.assertIsNotNone(session.id)

        # 2. Insert Message
        user_msg = CreativeMessage(
            session_id=session.id,
            actor="user",
            content="Write a script",
        )
        self.session.add(user_msg)
        self.session.flush()
        self.assertIsNotNone(user_msg.id)

        # 3. Insert Proposal
        manifest = {
            "source": "gemini",
            "provider": "gemini",
            "model": "gemini-2.5-flash",
            "provider_credential_id": str(uuid.uuid4()),
            "prompt_templates": {},
            "schema_version": 1,
            "trace_id": "trace-12345",
        }
        proposal = CreativeProposal(
            session_id=session.id,
            message_id=user_msg.id,
            parent_proposal_id=None,
            state="proposed",
            title="Marcus Aurelius Meditations",
            brief="Meditations summary",
            script="Be content with what you are...",
            scenes=[],
            version=1,
            trace_id="trace-12345",
            generation_manifest=manifest,
        )
        self.session.add(proposal)
        self.session.flush()
        self.assertIsNotNone(proposal.id)

        # 4. Insert Turn
        turn = CreativeTurn(
            session_id=session.id,
            idempotency_key="idemp-key-1111",
            request_fingerprint="fingerprint-1111",
            status="generating",
            lease_token=uuid.uuid4(),
            lease_expires_at=datetime.now(UTC) + timedelta(seconds=150),
            expected_revision=0,
            user_message_id=user_msg.id,
        )
        self.session.add(turn)
        self.session.flush()
        self.assertIsNotNone(turn.id)

        # 5. Insert Command Receipt
        receipt = CreativeCommandReceipt(
            organization_id=org_id,
            session_id=session.id,
            operation_type="create_session",
            idempotency_key="receipt-key-1111",
            request_fingerprint="fingerprint-1111",
            result_payload={"session_id": str(session.id)},
        )
        self.session.add(receipt)
        self.session.flush()
        self.assertIsNotNone(receipt.id)

    def test_short_form_workflow_repository_compatibility(self) -> None:
        org_id = self._create_test_organization()
        repo = SqlAlchemyShortFormWorkflowRepository(self.session)

        cmd = CreateShortFormCommand(
            organization_id=org_id,
            title="Philosopher Mindset",
            brief="Stoic advice",
            idempotency_key="idemp-workflow-unique-123456",
            format_profile="short_vertical",
            timezone="Asia/Bangkok",
        )

        summary = repo.create_or_get_initial_run(cmd)
        self.assertTrue(summary.created)

        run = self.session.scalar(select(WorkflowRun).where(WorkflowRun.id == summary.workflow_run_id))
        self.assertIsNotNone(run)
        self.assertEqual(run.idempotency_key, "idemp-workflow-unique-123456")

    def test_creative_document_repository_compatibility(self) -> None:
        org_id = self._create_test_organization()
        repo = SqlAlchemyShortFormWorkflowRepository(self.session)
        doc_repo = SqlAlchemyCreativeDocumentRepository(self.session)

        cmd = CreateShortFormCommand(
            organization_id=org_id,
            title="Philosopher Mindset 2",
            brief="Stoic advice",
            idempotency_key="idemp-workflow-unique-654321",
            format_profile="short_vertical",
            timezone="Asia/Bangkok",
        )
        summary = repo.create_or_get_initial_run(cmd)

        snapshot = doc_repo.save(
            organization_id=org_id,
            workflow_run_id=summary.workflow_run_id,
            expected_revision=0,
            script="Be happy and calm",
            scenes=[
                {
                    "narration": "Narration 1",
                    "visual_prompt": "Visual prompt 1",
                    "duration_seconds": 15,
                    "transition": "cut",
                    "caption": "Caption 1"
                }
            ],
            actor_subject="user-123",
        )

        self.assertEqual(snapshot.version, 1)
        self.assertEqual(snapshot.script, "Be happy and calm")

        doc = self.session.scalar(select(CreativeDocument).where(CreativeDocument.workflow_run_id == summary.workflow_run_id))
        self.assertIsNotNone(doc)
        self.assertEqual(doc.revision, 1)

    def test_create_workflow_draft_atomic_rollback_on_failure(self) -> None:
        org_id = self._create_test_organization()
        repo = SqlAlchemyShortFormWorkflowRepository(self.session)

        idempotency_key = "idemp-workflow-rollback-test-9999"
        cmd = CreateShortFormCommand(
            organization_id=org_id,
            title="Rollback Test",
            brief="Will fail on save",
            idempotency_key=idempotency_key,
            format_profile="short_vertical",
            timezone="Asia/Bangkok",
        )

        self.session.begin_nested()

        # 1. First step succeeds in transaction
        workflow_run, created = repo._create_or_get_initial_run_in_transaction(cmd)
        self.assertTrue(created)

        # 2. Insert an invalid model directly into session to trigger database IntegrityError upon flush/commit
        invalid_project = VideoProject(
            organization_id=None, # Causes NotNullViolation
            title="Invalid",
            brief="Invalid project",
        )
        self.session.add(invalid_project)

        with self.assertRaises(Exception):
            self.session.flush()

        self.session.rollback()

        # Verify no records were persisted
        run = self.session.scalar(select(WorkflowRun).where(WorkflowRun.idempotency_key == idempotency_key))
        self.assertIsNone(run)


if __name__ == "__main__":
    unittest.main()
