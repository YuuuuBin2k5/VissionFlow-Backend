"""Deterministic transport and restart tests. Never accesses production."""
import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import requests

from worker.control_plane_retry import ControlPlaneError, RetryPolicy, retry_delay
from worker.remote_render_worker import RemoteRenderWorker, WorkerConfig, WorkerHttpClient, WorkerError


class Clock:
    now = 0.0
    def __call__(self): return self.now
    def advance(self, seconds): self.now += seconds


class Reply:
    def __init__(self, status=200, payload=None, headers=None, text=''):
        self.status_code, self.payload = status, payload or {}
        self.headers, self.text = headers or {}, text
    def json(self): return self.payload
    def close(self): pass


class Session:
    def __init__(self, replies, clock): self.replies, self.clock, self.calls = list(replies), clock, []
    def request(self, method, url, **kw):
        self.calls.append((self.clock(), url, kw))
        reply = self.replies.pop(0) if self.replies else Reply(204)
        if isinstance(reply, Exception): raise reply
        return reply


def client(tmp_path, replies):
    clock = Clock()
    config = WorkerConfig('https://api.example.com', 'desktop-test', 'test-token', tmp_path)
    session = Session(replies, clock)
    policy = RetryPolicy(clock=clock, jitter=lambda: 0)
    return WorkerHttpClient(config, session=session, policy=policy), clock, session


def test_asset_download_failure_releases_slot_through_bounded_server_retry(tmp_path, monkeypatch):
    job = {'job_id': str(uuid.uuid4()), 'run_id': 'run_download_failure', 'attempt': 3}
    api, _, session = client(tmp_path, [Reply(payload=job), Reply(payload={'status': 'FAILED'}), Reply(204)])
    worker = RemoteRenderWorker(api.config, api)
    worker._started = True
    def fail_download(_):
        raise WorkerError('ASSET_DOWNLOAD_FAILED')
    monkeypatch.setattr(worker, '_process', fail_download)
    assert worker.run_once()
    assert worker._active is None
    failures = [kw['json'] for _, url, kw in session.calls if url.endswith('/fail')]
    assert len(failures) == 1
    assert failures[0]['attempt'] == 3
    assert not worker.run_once()


def test_failed_failure_delivery_retains_job_for_retry(tmp_path, monkeypatch):
    job = {'job_id': str(uuid.uuid4()), 'run_id': 'run_download_failure', 'attempt': 1}
    api, _, _ = client(tmp_path, [Reply(payload=job), requests.Timeout()])
    worker = RemoteRenderWorker(api.config, api)
    worker._started = True
    def fail_download(_):
        raise WorkerError('ASSET_DOWNLOAD_FAILED')
    monkeypatch.setattr(worker, '_process', fail_download)
    with pytest.raises(ControlPlaneError):
        worker.run_once()
    assert worker._active == job


def test_retry_after_shared_between_claim_and_heartbeat(tmp_path):
    api, clock, session = client(tmp_path, [Reply(429, headers={'Retry-After': '30'}), Reply(204)])
    with pytest.raises(ControlPlaneError, match='RATE_LIMITED'): api.claim_job()
    for t in (1, 10, 29.999):
        clock.now = t
        with pytest.raises(ControlPlaneError) as err: api.heartbeat()
        assert err.value.deferred
    assert len(session.calls) == 1
    clock.now = 30
    assert api.claim_job() is None


def test_circuit_three_limits_then_single_probe(tmp_path):
    api, clock, session = client(tmp_path, [Reply(429)] * 3 + [Reply(503), Reply(204)])
    for _ in range(3):
        with pytest.raises(ControlPlaneError): api.claim_job()
        clock.advance(api.policy.remaining())
    assert api.policy.circuit == 'OPEN'
    with pytest.raises(ControlPlaneError): api.claim_job()
    assert api.policy.circuit == 'OPEN'
    for _ in range(100):
        with pytest.raises(ControlPlaneError): api.claim_job()
    assert len(session.calls) == 4
    clock.advance(api.policy.remaining())
    api.claim_job()
    assert api.policy.circuit == 'CLOSED'


@pytest.mark.parametrize('status,category', [(401,'AUTH_FAILURE'),(403,'AUTH_FAILURE'),(400,'PERMANENT_REQUEST_ERROR'),
    (409,'JOB_REJECTED'),(429,'RATE_LIMITED'),(502,'SERVER_UNAVAILABLE'),(503,'SERVER_UNAVAILABLE'),(504,'SERVER_UNAVAILABLE')])
def test_categories(tmp_path, status, category):
    api, _, _ = client(tmp_path, [Reply(status)])
    with pytest.raises(ControlPlaneError) as error: api.claim_job()
    assert error.value.category == category


@pytest.mark.parametrize('status', [403,429])
def test_edge_html_is_not_logged(tmp_path, caplog, status):
    api, _, _ = client(tmp_path, [Reply(status, headers={'Content-Type':'text/html','CF-Ray':'abc-HKG'},
        text='<html>Just a moment cloudflare SENSITIVE_BODY</html>')])
    with pytest.raises(ControlPlaneError) as error: api.claim_job()
    assert error.value.category == 'EDGE_CHALLENGE'
    assert 'abc-HKG' in caplog.text and 'SENSITIVE_BODY' not in caplog.text


def test_retry_after_date_and_rate_headers():
    assert retry_delay({'Retry-After':'Thu, 01 Jan 1970 00:02:00 GMT'}, wall_time=lambda: 100) == 20
    assert retry_delay({'Retry-After':'900','RateLimit-Reset':'30'}) == 900
    assert retry_delay({'X-RateLimit-Reset':'130'}, wall_time=lambda:100) == 30
    assert retry_delay({'Retry-After':'NaN'}) == 0


def test_success_reset_header_only_defers_when_quota_exhausted(tmp_path):
    api, clock, session = client(tmp_path, [Reply(204, headers={'RateLimit-Reset':'30','RateLimit-Remaining':'5'}),
        Reply(204, headers={'RateLimit-Reset':'30','RateLimit-Remaining':'0'})])
    api.claim_job()
    assert api.policy.remaining() == 0
    api.claim_job()
    assert api.policy.remaining() == 30


def test_auth_failure_stops_all_further_requests(tmp_path):
    api, clock, session = client(tmp_path, [Reply(401)])
    with pytest.raises(ControlPlaneError): api.claim_job()
    clock.advance(3600)
    with pytest.raises(ControlPlaneError): api.heartbeat()
    assert api.policy.health == 'AUTH_FAILED' and len(session.calls) == 1


def test_single_instance_lock_released_on_shutdown(tmp_path):
    api, _, _ = client(tmp_path, [])
    first, second = RemoteRenderWorker(api.config, api), RemoteRenderWorker(api.config, api)
    first._acquire_instance()
    try:
        with pytest.raises(WorkerError, match='WORKER_ALREADY_RUNNING'): second._acquire_instance()
    finally:
        first.shutdown()
    second._acquire_instance()
    second.shutdown()


def test_heartbeat_coalesces(tmp_path):
    api, _, session = client(tmp_path, [])
    entered, release = threading.Event(), threading.Event()
    def request(*a, **kw):
        entered.set(); release.wait(2); return Reply()
    session.request = request
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(api.heartbeat)
        assert entered.wait(1)
        assert api.heartbeat() == {'status':'COALESCED'}
        release.set(); first.result()
    assert api.metrics['heartbeats'] == 1


def ready_state(worker):
    job = {'job_id':str(uuid.uuid4()),'run_id':'run_test','attempt':1}
    state = {'job':job,'worker_id':worker.config.worker_id,'api_base_url':worker.config.api_base_url,
        'phase':'COMPLETION_PENDING','upload_complete':True,
        'completion':{'checksum_sha256':'a'*64,'storage_ref':'visionflow/production/attempts/test.mp4',
                      'file_size_bytes':3}}
    path = worker._state_path(job).parent / 'output' / 'final.mp4'
    path.parent.mkdir(); path.write_bytes(b'mp4')
    worker._save_state(state)
    return state, path


def test_complete_429_then_restart_already_completed_no_render_or_fail(tmp_path, monkeypatch):
    api, clock, session = client(tmp_path, [Reply(payload={'status':'UPLOADING','lease_valid':True}),
                                          Reply(429,headers={'Retry-After':'30'})])
    w = RemoteRenderWorker(api.config, api); w._started=True
    state, path = ready_state(w)
    with pytest.raises(ControlPlaneError): w.run_once()
    saved=json.loads(w._state_path(state['job']).read_text())
    assert saved['phase']=='COMPLETION_UNKNOWN' and saved['upload_complete']
    assert path.read_bytes()==b'mp4'
    session.replies.append(Reply(payload={'status':'COMPLETED','completion':state['completion']}))
    clock.advance(30)
    restarted=RemoteRenderWorker(api.config,api); restarted._started=True
    monkeypatch.setattr(restarted,'_render',lambda _:pytest.fail('Must not rerender'))
    assert restarted.run_once()
    assert json.loads(restarted._state_path(state['job']).read_text())['phase']=='COMPLETED'
    assert not any(url.endswith(('/fail','/claim')) for _,url,_ in session.calls)


def test_completion_timeout_retry_same_payload(tmp_path):
    api, clock, session=client(tmp_path,[Reply(payload={'status':'UPLOADING','lease_valid':True}),requests.Timeout(),
        Reply(payload={'status':'UPLOADING','lease_valid':True}),Reply(payload={'status':'COMPLETED'})])
    w=RemoteRenderWorker(api.config,api);w._started=True
    state,_=ready_state(w)
    with pytest.raises(ControlPlaneError):w.run_once()
    clock.advance(api.policy.remaining())
    assert w.run_once()
    completes=[kw['json'] for _,url,kw in session.calls if url.endswith('/complete')]
    assert len(completes)==2 and completes[0]==completes[1]
    assert not any(url.endswith('/fail') for _,url,_ in session.calls)


def test_expired_lease_preserves_output_and_blocks_claim(tmp_path):
    api, _, session=client(tmp_path,[Reply(payload={'status':'UPLOADING','lease_valid':False})])
    w=RemoteRenderWorker(api.config,api);w._started=True
    state,path=ready_state(w)
    with pytest.raises(WorkerError,match='LEASE_EXPIRED'):w.run_once()
    with pytest.raises(WorkerError,match='LOCAL_STATE_REQUIRES_REVIEW'):w.run_once()
    assert path.exists() and len(session.calls)==1


def test_virtual_hour_idle_no_storm_with_one_pending_job(tmp_path):
    api, clock, session=client(tmp_path,[])
    w=RemoteRenderWorker(api.config,api);w._started=True
    next_heartbeat=60
    inserted=False
    while clock.now<3600:
        if 1000<=clock.now and not inserted:
            state,_=ready_state(w)
            session.replies.append(Reply(payload={'status':'COMPLETED','completion':state['completion']}))
            inserted=True
        elif int(clock.now)%300==0:
            session.replies.append(Reply(429,headers={'Retry-After':'30'}))
        elif int(clock.now)%220==0:
            session.replies.append(Reply(503))
        else:session.replies.append(Reply(204))
        try:w.run_once()
        except ControlPlaneError:pass
        if clock.now>=next_heartbeat:
            try:api.heartbeat()
            except ControlPlaneError:pass
            next_heartbeat=clock.now+60
        clock.advance(max(w.config.poll_seconds,api.policy.remaining()))
    assert inserted and len(session.calls)<250
    assert not any(url.endswith('/fail') for _,url,_ in session.calls)
    assert len(list(tmp_path.glob('jobs/*/state.json')))==1
