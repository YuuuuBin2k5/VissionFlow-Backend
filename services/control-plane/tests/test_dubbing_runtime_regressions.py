"""Real PostgreSQL regressions; opt in only with an isolated local test DB."""
import os
import sys
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / 'services/control-plane')]
from app.infrastructure.models import Base, Organization, VideoProject, WorkflowRun, MediaAsset, User, OrganizationMembership
from app.core.dubbing_claim import claim_next_dubbing_workflow
from app.core.dubbing_bridge import sync_dubbing_job_to_control_plane
from app.routers.dubbing import get_dubbing_job_status, dispatch_dubbing_job, DubbingDispatchRequest
from app.core.oidc import VerifiedIdentity
from worker.domain.dubbing_contract import build_dubbing_workflow_package, legacy_seo_to_publish_metadata
from worker.domain.publish_metadata import resolve_publish_metadata

DB = os.getenv('DUBBING_TEST_DATABASE_URL')

@unittest.skipUnless(DB, 'DUBBING_TEST_DATABASE_URL not configured')
class DubbingPostgresRegressionTests(unittest.TestCase):
    def setUp(self):
        url = make_url(DB)
        if url.host not in ('127.0.0.1', 'localhost') or not url.database.startswith('dubbing_e2e'):
            self.fail('Only an isolated local dubbing_e2e database is allowed')
        schema = 'case_' + uuid.uuid4().hex
        admin = create_engine(DB)
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA {schema}'))
        admin.dispose()
        self.engine = create_engine(DB, connect_args={'options':f'-c search_path={schema}'})
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.org_id = uuid.uuid4()
        self.project_id = uuid.uuid4()
        with Session(self.engine) as session:
            session.add(Organization(id=self.org_id, slug='e2e', name='E2E'))
            session.flush()
            session.add(VideoProject(id=self.project_id, organization_id=self.org_id, title='Test', brief='Test', format_profile='short_vertical', timezone='UTC'))
            session.commit()

    def workflow(self, state='QUEUED', expires=None, manifest=None):
        payload = {'render_mode':'TRANSLATE_DUB'}
        if expires:
            payload['dubbing_claim'] = {'expires_at':expires.isoformat()}
        with Session(self.engine) as session:
            wf = WorkflowRun(project_id=self.project_id, state=state, idempotency_key=uuid.uuid4().hex,
                             input_payload=payload, prompt_manifest=manifest or payload)
            session.add(wf)
            session.commit()
            return wf.id

    def test_active_leases_do_not_starve_queued_work(self):
        for _ in range(51):
            self.workflow('RENDERING', datetime.now(timezone.utc) + timedelta(hours=1))
        queued = self.workflow()
        with Session(self.engine) as session:
            claimed = claim_next_dubbing_workflow(session, worker_id='test')
            self.assertIsNotNone(claimed)
            self.assertEqual(queued, claimed.id)

    def test_two_claimers_and_lease_expiry(self):
        wf_id = self.workflow()
        barrier = Barrier(2)
        def claim(worker):
            with Session(self.engine) as session:
                barrier.wait(timeout=10)
                found = claim_next_dubbing_workflow(session, worker_id=worker)
                return str(found.id) if found else None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(claim, ['one','two']))
        self.assertEqual([str(wf_id)], [result for result in results if result])
        with Session(self.engine) as session:
            self.assertIsNone(claim_next_dubbing_workflow(session, worker_id='active'))
            wf = session.get(WorkflowRun, wf_id)
            wf.input_payload = {**wf.input_payload, 'dubbing_claim':{'expires_at':(datetime.now(timezone.utc)-timedelta(seconds=5)).isoformat()}}
            session.commit()
            self.assertEqual(wf_id, claim_next_dubbing_workflow(session, worker_id='expired').id)

    def test_rendering_without_explicit_expired_lease_is_not_claimed(self):
        self.workflow('RENDERING')
        with Session(self.engine) as session:
            self.assertIsNone(claim_next_dubbing_workflow(session, worker_id='test'))

    def test_dispatch_idempotency_with_ready_fixture_and_real_membership(self):
        # A DB fixture verifies dispatch only, never upload/content verification.
        with Session(self.engine) as session:
            user = User(identity_subject='test-dispatch',email='dispatch@example.invalid')
            session.add(user)
            session.flush()
            session.add(OrganizationMembership(organization_id=self.org_id,user_id=user.id,role='administrator'))
            asset = MediaAsset(organization_id=self.org_id,object_key='fixture/source.mp4',media_kind='source_video',content_type='video/mp4',byte_size=1,checksum_sha256='0'*64,metadata_json={'status':'READY'})
            session.add(asset)
            session.commit()
            identity = VerifiedIdentity(subject=user.identity_subject,email=None,display_name=None,scopes=[])
            payload = DubbingDispatchRequest(organization_id=self.org_id,source_asset_id=asset.id,target_language='vi',translation_mode='faithful')
            with patch.dict(os.environ, {'ENABLE_WEB_DUBBING':'true'}):
                first = dispatch_dubbing_job(payload,'same-key',identity,session)
                second = dispatch_dubbing_job(payload,'same-key',identity,session)
            self.assertEqual(first['workflow_run_id'],second['workflow_run_id'])

    def test_bridge_preserves_review_timeline_and_user_override_after_retry(self):
        wf_id = self.workflow(manifest={'publish_metadata':{'youtube':{'description':'A'}}})
        # Save the operator edit in a separate transaction, then reload/retry.
        with Session(self.engine) as session:
            wf = session.get(WorkflowRun, wf_id)
            wf.prompt_manifest = {**wf.prompt_manifest,'publish_metadata_user':{'youtube':{'description':'B'}}}
            session.commit()
        package = build_dubbing_workflow_package({})
        package['translation']['timeline'] = [{'source_text':'Hello', 'translated_text':'Xin chào', 'start':0,'end':1}]
        package['dubbing']['timing_qc'] = {'status':'PASSED','segments':[{'target_duration_ms':1000,'rendered_audio_duration_ms':1000}]}
        generated = {'title':'Title','caption_seo':'A'*700,'hashtags':['test'],'pinned_comment':'Comment'}
        stale = {'seo':generated,'dubbing_workflow':package, 'publish_metadata_user':{'youtube':{'description':'OLD'}}}
        with patch('app.infrastructure.database.get_engine', return_value=self.engine), patch.dict(os.environ, {'DATABASE_URL':DB}):
            for _ in range(2):
                sync_dubbing_job_to_control_plane(str(wf_id),'Title',stale,workflow_run_id=str(wf_id))
        with Session(self.engine) as session:
            wf = session.get(WorkflowRun, wf_id)
            self.assertEqual(package['translation']['timeline'],wf.prompt_manifest['dubbing_workflow']['translation']['timeline'])
            self.assertEqual(package['dubbing']['timing_qc'],wf.prompt_manifest['dubbing_workflow']['dubbing']['timing_qc'])
            self.assertEqual('B',wf.prompt_manifest['publish_metadata_user']['youtube']['description'])
            resolved = resolve_publish_metadata(content_metadata=wf.prompt_manifest['publish_metadata'],user_metadata=wf.prompt_manifest['publish_metadata_user'])
            self.assertEqual('B',resolved.description.value)

    def test_status_and_publisher_resolve_same_complete_legacy_metadata(self):
        seo = {'title':'Daniel','caption_seo':'A'*700,'hashtags':['test'],'pinned_comment':'Comment'}
        wf_id = self.workflow(manifest={'publish_metadata':legacy_seo_to_publish_metadata(seo), 'burn_subtitles':True, 'mute_original_audio':True})
        identity = VerifiedIdentity(subject='test',email=None,display_name=None,scopes=[])
        with Session(self.engine) as session, patch('app.routers.dubbing.AuthorizeOrganization.require'):
            preview = get_dubbing_job_status(str(wf_id), self.org_id, identity, session)
            resolved = resolve_publish_metadata(content_metadata=session.get(WorkflowRun,wf_id).prompt_manifest['publish_metadata'])
            self.assertEqual(resolved.description.value, preview['video_description'])
            self.assertEqual(700,len(preview['video_description']))
            self.assertEqual('Comment', resolved.pinned_comment.value)
            self.assertTrue(preview['review']['subtitle_settings']['burn_subtitles'])
            self.assertTrue(preview['review']['audio_settings']['mute_original_audio'])
