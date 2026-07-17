import os
import sys
import unittest
import uuid
from datetime import datetime, timedelta, UTC
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.main import app
from app.core.oidc import VerifiedIdentity
from app.routers.auth import require_identity
from app.infrastructure.database import get_session
from app.infrastructure.models import (
    Base,
    Organization,
    User,
    OrganizationMembership,
    CreativeSession,
    CreativeMessage,
    CreativeProposal,
    CreativeTurn,
    CreativeCommandReceipt,
    ProviderCredential,
    PromptTemplate,
    PromptVersion,
    WorkflowRun,
)
from app.application.ports.creative_planning_provider import CreativePlanningProvider
from app.domain.authorization import OrganizationRole
from app.core.credential_cipher import ProviderCredentialCipher


class MockCreativePlanningProvider(CreativePlanningProvider):
    def __init__(self):
        self.mock_generate = MagicMock()

    def generate_proposal(self, **kwargs):
        return self.mock_generate(**kwargs)


class CreativeSessionsApiTests(unittest.TestCase):
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

        # Setup mock provider
        self.mock_provider = MockCreativePlanningProvider()

        # Identity defaults
        self.user_subject = "usr-test-12345"
        self.org_id = uuid.uuid4()

        # Setup tenant organization, user and membership
        org = Organization(id=self.org_id, slug=f"org-slug-{self.org_id}", name="Test Gemini Org")
        self.session.add(org)

        user_id = uuid.uuid4()
        user = User(id=user_id, identity_subject=self.user_subject, email="test@example.com", display_name="testuser")
        self.session.add(user)
        self.session.flush() # Force flush to ensure user exists before membership constraint check

        membership = OrganizationMembership(
            organization_id=self.org_id,
            user_id=user_id,
            role=OrganizationRole.PRODUCER.value,
        )
        self.session.add(membership)
        self.session.flush()

        # Setup prompt baselines
        self._setup_prompt_baselines()

        self.session.commit()

        # FastAPI dependency overrides
        app.dependency_overrides[require_identity] = lambda: VerifiedIdentity(
            subject=self.user_subject,
            email="test@example.com",
            display_name="testuser",
        )
        app.dependency_overrides[get_session] = lambda: self.session

        # Inject mock session maker and provider adapter into the router manager factory
        # We patch _get_manager function in app.routers.creative_sessions
        from app.application.manage_creative_session import ManageCreativeSession
        self.manager = ManageCreativeSession(
            session_maker=self.Session,
            provider_adapter=self.mock_provider,
            env_fallback_enabled=True,
            env_fallback_key="env-fallback-key-value",
        )

        # Overwrite _get_manager function mapping
        from app.routers import creative_sessions
        self.original_get_manager = creative_sessions._get_manager
        creative_sessions._get_manager = lambda session: self.manager

        self.client = TestClient(app)

    def tearDown(self) -> None:
        from app.routers import creative_sessions
        creative_sessions._get_manager = self.original_get_manager
        app.dependency_overrides.clear()
        self.session.rollback()
        self.session.close()

    def _clear_tables(self) -> None:
        self.session.execute(text("TRUNCATE TABLE creative_command_receipts CASCADE;"))
        self.session.execute(text("TRUNCATE TABLE creative_turns CASCADE;"))
        self.session.execute(text("TRUNCATE TABLE creative_proposals CASCADE;"))
        self.session.execute(text("TRUNCATE TABLE creative_messages CASCADE;"))
        self.session.execute(text("TRUNCATE TABLE creative_sessions CASCADE;"))
        self.session.execute(text("TRUNCATE TABLE provider_credentials CASCADE;"))
        self.session.execute(text("TRUNCATE TABLE prompt_versions CASCADE;"))
        self.session.execute(text("TRUNCATE TABLE prompt_templates CASCADE;"))
        self.session.execute(text("TRUNCATE TABLE workflow_runs CASCADE;"))
        self.session.execute(text("TRUNCATE TABLE video_projects CASCADE;"))
        self.session.execute(text("TRUNCATE TABLE organization_memberships CASCADE;"))
        self.session.execute(text("TRUNCATE TABLE users CASCADE;"))
        self.session.execute(text("TRUNCATE TABLE organizations CASCADE;"))
        self.session.commit()

    def _setup_prompt_baselines(self) -> None:
        p_template = PromptTemplate(
            id=uuid.uuid4(),
            organization_id=self.org_id,
            prompt_key="short_video_scene_planner",
            name="Scene Planner",
            description="Planner",
            production_version=1,
        )
        self.session.add(p_template)

        p_ver = PromptVersion(
            prompt_template_id=p_template.id,
            version=1,
            content="Planner content instruction",
        )
        self.session.add(p_ver)

        d_template = PromptTemplate(
            id=uuid.uuid4(),
            organization_id=self.org_id,
            prompt_key="short_video_visual_art_director",
            name="Art Director",
            description="Director",
            production_version=1,
        )
        self.session.add(d_template)

        d_ver = PromptVersion(
            prompt_template_id=d_template.id,
            version=1,
            content="Director content instruction",
        )
        self.session.add(d_ver)

    def _create_test_session(self) -> uuid.UUID:
        spec = {
            "title": "Stoic Advice",
            "brief": "Visual guide",
            "format_profile": "short_vertical",
            "timezone": "Asia/Bangkok",
            "language": "vi",
            "voice": "edge-nam-minh",
            "caption_preset": "clean_news",
            "visual_preset": "clean_explainer",
            "duration_seconds": 30,
        }
        sess = CreativeSession(
            organization_id=self.org_id,
            creation_spec=spec,
            revision=0,
        )
        self.session.add(sess)
        self.session.flush()
        self.session.commit()
        return sess.id

    def test_create_session_endpoint_success_and_idempotency(self) -> None:
        spec = {
            "title": "stoic rule",
            "brief": "stoic rule brief",
            "format_profile": "short_vertical",
            "timezone": "Asia/Bangkok",
            "language": "vi",
            "voice": "edge-nam-minh",
            "caption_preset": "clean_news",
            "visual_preset": "clean_explainer",
            "duration_seconds": 30,
        }

        # Success creation
        res = self.client.post(
            f"/api/v1/organizations/{self.org_id}/creative-sessions",
            json={"creation_spec": spec, "idempotency_key": "session-idemp-unique-12345"},
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        sess_id = res.json()["session_id"]
        self.assertIsNotNone(sess_id)

        # Idempotent replay
        res_replay = self.client.post(
            f"/api/v1/organizations/{self.org_id}/creative-sessions",
            json={"creation_spec": spec, "idempotency_key": "session-idemp-unique-12345"},
        )
        self.assertEqual(res_replay.status_code, status.HTTP_200_OK)
        self.assertEqual(res_replay.json()["session_id"], sess_id)

        # Mismatch payload error
        spec_diff = spec.copy()
        spec_diff["duration_seconds"] = 60
        res_mismatch = self.client.post(
            f"/api/v1/organizations/{self.org_id}/creative-sessions",
            json={"creation_spec": spec_diff, "idempotency_key": "session-idemp-unique-12345"},
        )
        self.assertEqual(res_mismatch.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(res_mismatch.json()["type"], "IDEMPOTENCY_PAYLOAD_MISMATCH")

    def test_get_session_details_isolation_and_not_found(self) -> None:
        sess_id = self._create_test_session()

        # Tenant isolation validation: access with different org_id query must return 404
        other_org_id = uuid.uuid4()

        # Seed other organization and membership so the user passes organization check,
        # but fails on session tenant-safe verification (since session belongs to org_id)
        other_org = Organization(id=other_org_id, slug=f"org-slug-{other_org_id}", name="Other Org")
        self.session.add(other_org)

        user_id = self.session.scalars(select(User.id).where(User.identity_subject == self.user_subject)).first()
        other_membership = OrganizationMembership(
            organization_id=other_org_id,
            user_id=user_id,
            role=OrganizationRole.PRODUCER.value,
        )
        self.session.add(other_membership)
        self.session.flush()
        self.session.commit()

        res_isolation = self.client.get(
            f"/api/v1/creative-sessions/{sess_id}?organization_id={other_org_id}"
        )
        # Even if membership of other_org_id passes,
        # session details fetch yields 404 to avoid leaking cross-tenant session metadata existence.
        self.assertEqual(res_isolation.status_code, status.HTTP_404_NOT_FOUND)

        # Successful fetch
        res_success = self.client.get(
            f"/api/v1/creative-sessions/{sess_id}?organization_id={self.org_id}"
        )
        self.assertEqual(res_success.status_code, status.HTTP_200_OK)
        self.assertEqual(res_success.json()["id"], str(sess_id))

    def test_update_creation_spec_success_and_failures(self) -> None:
        sess_id = self._create_test_session()

        spec_update = {
            "title": "stoic rule updated",
            "brief": "updated stoic brief",
            "format_profile": "short_vertical",
            "timezone": "Asia/Bangkok",
            "language": "vi",
            "voice": "edge-nam-minh",
            "caption_preset": "clean_news",
            "visual_preset": "clean_explainer",
            "duration_seconds": 45,
        }

        # Success update
        res = self.client.patch(
            f"/api/v1/creative-sessions/{sess_id}/creation-spec",
            json={
                "organization_id": str(self.org_id),
                "expected_revision": 0,
                "idempotency_key": "spec-update-idemp-unique-1111",
                "creation_spec": spec_update,
            }
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.json()["revision"], 1)

        # Stale revision conflict check
        res_conflict = self.client.patch(
            f"/api/v1/creative-sessions/{sess_id}/creation-spec",
            json={
                "organization_id": str(self.org_id),
                "expected_revision": 0, # Should be 1 now
                "idempotency_key": "spec-update-idemp-unique-2222",
                "creation_spec": spec_update,
            }
        )
        self.assertEqual(res_conflict.status_code, status.HTTP_409_CONFLICT)

    def test_send_message_flow_expired_reclaims_and_late_response(self) -> None:
        sess_id = self._create_test_session()

        # Mock LLM provider success output
        mock_scenes = [
            {"narration": "Scene 1 voiceover", "visual_prompt": "Visual prompt 1", "duration_seconds": 15, "transition": "cut", "caption": "Cap 1"}
        ]
        self.mock_provider.mock_generate.return_value = ("Plan details...", {
            "title": "Gemini Stoic Plan",
            "brief": "Visual guide by Gemini",
            "script": "Script voiceover detail stoic Marcus Aurelius",
            "scenes": mock_scenes,
        })

        # 1. Success Message generation turn
        res = self.client.post(
            f"/api/v1/creative-sessions/{sess_id}/messages",
            json={
                "organization_id": str(self.org_id),
                "message": "Stoic meditations",
                "expected_session_revision": 0,
                "idempotency_key": "msg-idemp-key-unique-3333",
            }
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.json()["revision"], 1)
        self.assertEqual(res.json()["assistant_message"], "Plan details...")

        # 2. Replay cached result payload
        res_replay = self.client.post(
            f"/api/v1/creative-sessions/{sess_id}/messages",
            json={
                "organization_id": str(self.org_id),
                "message": "Stoic meditations",
                "expected_session_revision": 0,
                "idempotency_key": "msg-idemp-key-unique-3333",
            }
        )
        self.assertEqual(res_replay.status_code, status.HTTP_200_OK)
        self.assertEqual(res_replay.json()["proposal"]["title"], "Gemini Stoic Plan")

        # 3. Simulate Generating In-Progress (Unexpired lease block)
        # Directly insert a generating turn in DB
        sess_ref = self.session.get(CreativeSession, sess_id)
        msg_user = CreativeMessage(session_id=sess_id, actor="user", content="Next message")
        self.session.add(msg_user)
        self.session.flush()

        active_turn = CreativeTurn(
            session_id=sess_id,
            idempotency_key="msg-idemp-active-generating",
            request_fingerprint="fingerprint-abc",
            status="generating",
            lease_token=uuid.uuid4(),
            lease_expires_at=datetime.now(UTC) + timedelta(seconds=120),
            expected_revision=1,
            user_message_id=msg_user.id,
        )
        self.session.add(active_turn)
        self.session.commit()

        res_generating = self.client.post(
            f"/api/v1/creative-sessions/{sess_id}/messages",
            json={
                "organization_id": str(self.org_id),
                "message": "Active progress test",
                "expected_session_revision": 1,
                "idempotency_key": "msg-idemp-key-another-4444",
            }
        )
        # Blocked as there is an active generating turn unexpired
        self.assertEqual(res_generating.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(res_generating.json()["type"], "CREATIVE_SESSION_CONFLICT")

    def test_manual_proposal_and_operator_revision_lineage(self) -> None:
        sess_id = self._create_test_session()

        # 1. Create manual proposal
        scenes_manual = [
            {"narration": "Manual voiceover 1", "visual_prompt": "Visual description", "duration_seconds": 10, "transition": "cut", "caption": "Sub 1"},
            {"narration": "Manual voiceover 2", "visual_prompt": "Visual description", "duration_seconds": 15, "transition": "cut", "caption": "Sub 2"},
            {"narration": "Manual voiceover 3", "visual_prompt": "Visual description", "duration_seconds": 10, "transition": "cut", "caption": "Sub 3"},
        ]
        res_manual = self.client.post(
            f"/api/v1/creative-sessions/{sess_id}/proposals",
            json={
                "organization_id": str(self.org_id),
                "expected_session_revision": 0,
                "idempotency_key": "manual-proposal-idemp-unique-8888",
                "title": "Stoic Meditations Book",
                "brief": "Meditations manually drafted",
                "script": "Calmness Stoic meditator thinking deep at late night hours.", # length > 40
                "scenes": scenes_manual,
            }
        )
        self.assertEqual(res_manual.status_code, status.HTTP_200_OK)
        proposal_id = res_manual.json()["proposal_id"]

        # Verify manual lineage: User message summarizes manual script creation
        prop = self.session.get(CreativeProposal, uuid.UUID(proposal_id))
        self.assertIsNotNone(prop)
        self.assertEqual(prop.generation_manifest["source"], "manual")
        msg = self.session.get(CreativeMessage, prop.message_id)
        self.assertEqual(msg.actor, "user")
        self.assertIn("[Manual script creation]", msg.content)

        # 2. Create operator revision
        res_revision = self.client.post(
            f"/api/v1/creative-sessions/{sess_id}/proposals/{proposal_id}/revisions",
            json={
                "organization_id": str(self.org_id),
                "expected_session_revision": 1,
                "idempotency_key": "revision-idemp-unique-9999",
                "title": "Stoic Meditations Book (Revised)",
                "brief": "Meditations manually edited",
                "script": "Calmness Stoic meditator thinking deep at late night hours updated.",
                "scenes": scenes_manual,
            }
        )
        self.assertEqual(res_revision.status_code, status.HTTP_200_OK)
        rev_id = res_revision.json()["proposal_id"]

        # Verify revision lineage: Revision proposal inherits parent message_id
        rev_prop = self.session.get(CreativeProposal, uuid.UUID(rev_id))
        self.assertIsNotNone(rev_prop)
        self.assertEqual(rev_prop.parent_proposal_id, prop.id)
        self.assertEqual(rev_prop.message_id, prop.message_id)
        self.assertEqual(rev_prop.generation_manifest["source"], "operator_edit")

    def test_one_session_one_workflow_run_invariant_and_accept_proposal(self) -> None:
        sess_id = self._create_test_session()

        # Setup accepted proposal
        msg = CreativeMessage(session_id=sess_id, actor="user", content="Brief input")
        self.session.add(msg)
        self.session.flush()

        proposal = CreativeProposal(
            session_id=sess_id,
            message_id=msg.id,
            state="proposed",
            title="Stoic Meditations",
            brief="Meditations manual brief",
            script="Be calm and content in everything you do during late night coding.",
            scenes=[
                {"narration": "Text 1", "visual_prompt": "Visual 1", "duration_seconds": 15, "transition": "cut", "caption": "Cap 1"},
                {"narration": "Text 2", "visual_prompt": "Visual 2", "duration_seconds": 15, "transition": "cut", "caption": "Cap 2"},
                {"narration": "Text 3", "visual_prompt": "Visual 3", "duration_seconds": 15, "transition": "cut", "caption": "Cap 3"},
            ],
            version=1,
            trace_id=str(uuid.uuid4()),
            generation_manifest={"source": "manual"},
        )
        self.session.add(proposal)
        self.session.commit()

        # 1. Accept Proposal
        res_accept = self.client.post(
            f"/api/v1/creative-sessions/{sess_id}/proposals/{proposal.id}/accept",
            json={
                "organization_id": str(self.org_id),
                "expected_revision": 0,
                "idempotency_key": "accept-idemp-unique-5555",
            }
        )
        self.assertEqual(res_accept.status_code, status.HTTP_200_OK)
        self.assertEqual(res_accept.json()["accepted_proposal_id"], str(proposal.id))

        # 2. Create Workflow Draft
        res_draft = self.client.post(
            f"/api/v1/creative-sessions/{sess_id}/create-workflow-draft",
            json={
                "organization_id": str(self.org_id),
                "accepted_proposal_id": str(proposal.id),
                "idempotency_key": "draft-creation-idemp-unique-6666",
            }
        )
        self.assertEqual(res_draft.status_code, status.HTTP_200_OK)
        wf_run_id = res_draft.json()["workflow_run_id"]
        doc_version_id = res_draft.json()["creative_document_version_id"]
        self.assertIsNotNone(wf_run_id)

        # Verify Session workflow_run_id mapping
        sess_ref = self.session.get(CreativeSession, sess_id)
        self.assertEqual(str(sess_ref.workflow_run_id), wf_run_id)

        # 3. Idempotent draft replay
        res_replay = self.client.post(
            f"/api/v1/creative-sessions/{sess_id}/create-workflow-draft",
            json={
                "organization_id": str(self.org_id),
                "accepted_proposal_id": str(proposal.id),
                "idempotency_key": "draft-creation-idemp-unique-6666",
            }
        )
        self.assertEqual(res_replay.status_code, status.HTTP_200_OK)
        self.assertEqual(res_replay.json()["workflow_run_id"], wf_run_id)
        self.assertTrue(res_replay.json()["idempotent_replay"])

        # 4. Conflict: session has already been finalized and bound
        res_conflict = self.client.post(
            f"/api/v1/creative-sessions/{sess_id}/create-workflow-draft",
            json={
                "organization_id": str(self.org_id),
                "accepted_proposal_id": str(proposal.id),
                "idempotency_key": "draft-creation-idemp-unique-7777", # New idempotency key
            }
        )
        self.assertEqual(res_conflict.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(res_conflict.json()["type"], "CREATIVE_SESSION_ALREADY_BOUND")
