"""Real PostgreSQL + TCP HTTP + remote worker + FFmpeg + final QC.

Only the cloud object store is substituted, with scoped HTTP PUT/GET grants.
All persistent test state is confined to pytest temp dirs and a random PG schema.
"""
from __future__ import annotations

import json
import importlib
import socket
import subprocess
import threading
import time
import uuid
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response
from sqlalchemy.orm import Session

from test_remote_render_repository import remote_pg_engine
from app.infrastructure.database import get_session
from app.infrastructure.models import RenderJob
from app.routers import render_workers
from app.routers.auth import require_identity
from production.artifact_storage import get_artifact_storage
from production.canonical_renderer import CanonicalFFmpegRenderer
from production.contracts import AutoVideoRequest, EditorPlan, ProductionRun, ScenePlan, ShotPlan, AudioTrackPlan, AudioClipPlan
from production.remote_manifest import PortableRenderManifest, sha256_file
from production.remote_render import enqueue_remote_render, load_remote_run
from production.remote_worker_auth import worker_scope_middleware
from production.render_handoff import render_handoff
from worker.remote_render_worker import RemoteRenderWorker, WorkerConfig, WorkerHttpClient

TOKEN_A = "test-only-desktop-a-" + "a" * 32
TOKEN_B = "test-only-desktop-b-" + "b" * 32


class HttpObjectStorage:
    def __init__(self):
        self.objects = {}
        self.grants = {}
        self.base = ""
        self.gets = 0
        self.puts = 0

    def put_file(self, ref, path, mime):
        self.objects[ref] = (path.read_bytes(), {"sha256": sha256_file(path)})

    def object_exists(self, ref):
        return ref in self.objects

    def metadata(self, ref):
        data, metadata = self.objects[ref]
        return {"ContentLength": len(data), "Metadata": metadata, 'ContentType': 'image/png' if ref.endswith('.png') else 'video/mp4'}

    def download_to(self, ref, path):
        path.write_bytes(self.objects[ref][0])

    def grant(self, method, ref, checksum=""):
        token = uuid.uuid4().hex
        self.grants[token] = (method, ref, checksum)
        return self.base + "/test-objects/" + token

    def presigned_download(self, ref):
        return self.grant("GET", ref)

    def presigned_upload(self, ref, checksum):
        return {"storage_ref": ref, "upload_url": self.grant("PUT", ref, checksum),
                "headers": {"Content-Type": "video/mp4", "x-amz-meta-sha256": checksum}}

    def mount(self, app):
        @app.api_route("/test-objects/{token}", methods=["GET", "PUT"])
        async def object_transport(token: str, request: Request):
            # Object transport must not receive API credentials.
            assert "authorization" not in request.headers
            assert "x-visionflow-worker-id" not in request.headers
            grant = self.grants.get(token)
            if grant is None or grant[0] != request.method:
                raise HTTPException(403)
            method, ref, checksum = grant
            if method == "GET":
                self.gets += 1
                data = self.objects[ref][0]
                mime = 'image/png' if ref.endswith('.png') else 'video/mp4'
                if request.headers.get('range', '').startswith('bytes='):
                    start, _, end = request.headers['range'][6:].partition('-')
                    start, end = int(start or 0), min(int(end) if end else len(data)-1, len(data)-1)
                    return Response(data[start:end+1], status_code=206, media_type=mime,
                        headers={'Content-Range': f'bytes {start}-{end}/{len(data)}', 'Accept-Ranges': 'bytes'})
                return Response(data, media_type=mime, headers={'Accept-Ranges': 'bytes'})
            assert request.headers.get("x-amz-meta-sha256") == checksum
            self.puts += 1
            self.objects[ref] = (await request.body(), {"sha256": checksum})
            return Response(status_code=200)


@contextmanager
def serve(app):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(.02)
    assert server.started, "Test HTTP server did not start"
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=15)
        sock.close()


@pytest.fixture
def http_runtime(remote_pg_engine, tmp_path, monkeypatch):
    runs = importlib.import_module("production.repositories.run_repository")
    import app.infrastructure.database as database
    monkeypatch.setattr(runs, "STORAGE_DIR", tmp_path / "runs")
    runs.STORAGE_DIR.mkdir()
    monkeypatch.setattr(runs.run_repository, "_runs", {})
    monkeypatch.setattr(database, "get_engine", lambda: remote_pg_engine)
    monkeypatch.setenv("VISIONFLOW_RENDER_POLICY", "LOCAL_ONLY")
    monkeypatch.setenv("VISIONFLOW_RENDER_JOB_BACKEND", "postgres")
    monkeypatch.setenv("VISIONFLOW_WORKER_TOKENS", json.dumps({"desktop-a": TOKEN_A, "desktop-b": TOKEN_B}))
    app = FastAPI()
    app.include_router(render_workers.router, prefix="/api/v1")
    app.middleware("http")(worker_scope_middleware)
    storage = HttpObjectStorage()
    storage.mount(app)
    def sessions():
        with Session(remote_pg_engine) as session:
            yield session
    app.dependency_overrides[get_session] = sessions
    app.dependency_overrides[get_artifact_storage] = lambda: storage
    app.dependency_overrides[require_identity] = lambda: SimpleNamespace(subject="operator-test")
    @app.post("/api/v1/production/review")
    def protected_general_route():
        return {"not_called_with_worker_token": True}
    from production.production_controller import _handle_get_run, _handle_get_video
    app.add_api_route("/api/v1/production/runs/{run_id}", _handle_get_run, methods=["GET"])
    app.add_api_route("/api/v1/production/runs/{run_id}/video", _handle_get_video, methods=["GET"])
    import production.artifact_storage as artifacts
    monkeypatch.setattr(artifacts, "get_artifact_storage", lambda: storage)
    monkeypatch.setattr('production.remote_render.get_artifact_storage', lambda: storage)
    with serve(app) as base:
        storage.base = base
        yield SimpleNamespace(base=base, app=app, storage=storage, engine=remote_pg_engine, tmp=tmp_path)


def make_run(runtime):
    renderer = CanonicalFFmpegRenderer()
    video = runtime.tmp / "source.mp4"
    voice = runtime.tmp / "voice.wav"
    subprocess.run([renderer.ffmpeg_bin, "-y", "-f", "lavfi", "-i", "testsrc2=size=360x640:rate=30:duration=2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)], check=True, capture_output=True)
    subprocess.run([renderer.ffmpeg_bin, "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                    str(voice)], check=True, capture_output=True)
    run_id = "run_remote_" + uuid.uuid4().hex[:10]
    shot = ShotPlan(shot_id="shot_1", asset_id="test_moving_source", media_url=str(video), duration_sec=2,
                    timeline_end=2, visual_role="HOOK", match_score=1)
    scene = ScenePlan(scene_id="scene_1", narration="Integration test narration", shots=[shot],
                      audio_file_path=str(voice), duration_seconds=2, actual_duration_seconds=2, timeline_end=2)
    plan = EditorPlan(plan_id="plan_" + run_id, run_id=run_id, plan_type="FINAL", is_render_ready=True,
                      scenes=[scene], duration_seconds=2, total_duration_sec=2,
                      audio_track=AudioTrackPlan(clips=[AudioClipPlan(clip_id="voice_1", file_path=str(voice), duration_sec=2)]))
    run = ProductionRun(id=run_id, request=AutoVideoRequest(request_id=run_id, instruction="Test"), editor_plan=plan)
    spec = render_handoff.build_spec(plan, run_id, strict_inputs=True)
    spec.width, spec.height = 360, 640
    with Session(runtime.engine) as session:
        job = enqueue_remote_render(run, session=session, storage=runtime.storage, spec=spec)
        job_id = job.id
    return run, job_id, video, voice


def config(runtime, worker="desktop-a", token=TOKEN_A):
    return WorkerConfig(api_base_url=runtime.base, worker_id=worker, worker_token=token,
                        work_dir=runtime.tmp / worker, heartbeat_seconds=.25, poll_seconds=.1,
                        allow_loopback_http=True)


def headers(worker="desktop-a", token=TOKEN_A):
    return {"Authorization": f"Bearer {token}", "X-VisionFlow-Worker-ID": worker}


def test_real_ffmpeg_vertical_slice_and_completion_replay(http_runtime, monkeypatch):
    runtime = http_runtime
    run, job_id, video, voice = make_run(runtime)
    with Session(runtime.engine) as session:
        job = session.get(RenderJob, job_id)
        assert job.status == "WAITING_FOR_WORKER"
        manifest_json = json.dumps(job.render_spec_json["manifest"])
        assert str(video) not in manifest_json and "download_url" not in manifest_json
        assert len(PortableRenderManifest.model_validate(job.render_spec_json["manifest"]).artifacts) == 2
    # Prove that the worker is not sharing the producer's input files.
    video.unlink()
    voice.unlink()
    runtime.engine.dispose()
    worker = RemoteRenderWorker(config(runtime))
    from production.quality_orchestrator import quality_orchestrator
    actual_qc = quality_orchestrator.run_post_render_qc
    qc_calls = []
    def counted_qc(*args, **kwargs):
        qc_calls.append(1)
        return actual_qc(*args, **kwargs)
    monkeypatch.setattr(quality_orchestrator, "run_post_render_qc", counted_qc)
    completion_payloads = []
    original = worker.client.complete_job
    def capture(job, payload):
        completion_payloads.append((dict(job), dict(payload)))
        # Two independent HTTP requests race on the actual PostgreSQL row lock.
        another = WorkerHttpClient(config(runtime))
        with ThreadPoolExecutor(max_workers=2) as pool:
            one = pool.submit(original, job, payload)
            two = pool.submit(another.complete_job, job, payload)
            result = one.result()
            assert result == two.result()
            return result
    worker.client.complete_job = capture
    try:
        assert worker.run_once()
        assert not worker.run_once()
    finally:
        worker.shutdown()
    with Session(runtime.engine) as session:
        job = session.get(RenderJob, job_id)
        assert job.status == "COMPLETED", job.error_code
        restored = load_remote_run(run.id, session)
        assert restored.status.value == "HUMAN_REVIEW_PENDING", restored.quality_report
        assert restored.quality_report.blocker_count == 0
        assert "technical" in restored.quality_report.evaluated_axes
        assert restored.render_artifact.internal_file_path is None
        assert restored.render_artifact.storage_ref == job.output_artifact_ref
        assert job.output_artifact_ref.startswith("visionflow/production/outputs/")
        qc_id = restored.quality_report.report_id
    assert runtime.storage.gets == 2 and runtime.storage.puts == 1
    assert len(completion_payloads) == 1
    job, payload = completion_payloads[0]
    replay = original(job, payload)
    assert replay["qc_report_id"] == qc_id
    assert len(qc_calls) == 1
    bad = dict(payload, checksum_sha256="f" * 64)
    response = requests.post(runtime.base + f"/api/v1/render-workers/jobs/{job_id}/complete",
                             headers=headers(), json={"attempt": job["attempt"], **bad})
    assert response.status_code == 422
    # Browser projection survives discarding local run cache/files.
    runs = importlib.import_module("production.repositories.run_repository")
    runs.run_repository._runs.clear()
    for local in runs.STORAGE_DIR.glob("*.json"):
        local.unlink()
    response = requests.get(runtime.base + f"/api/v1/production/runs/{run.id}")
    assert response.json()["status"] == "HUMAN_REVIEW_PENDING"
    output = requests.get(runtime.base + f"/api/v1/production/runs/{run.id}/video", allow_redirects=True)
    assert output.status_code == 200 and len(output.content) > 16384
    final = runtime.tmp / "verified-final.mp4"
    final.write_bytes(output.content)
    probe = CanonicalFFmpegRenderer().probe(final)
    assert probe.has_audio and probe.has_video and abs(probe.duration_seconds - 2) <= .1
    assert (probe.width, probe.height, probe.fps) == (360, 640, 30)
    # A still-valid old presigned PUT cannot mutate the promoted final artifact.
    runtime.storage.objects[payload["storage_ref"]] = (b"late overwrite", {"sha256": payload["checksum_sha256"]})
    safe_output = requests.get(runtime.base + f"/api/v1/production/runs/{run.id}/video")
    assert safe_output.content == output.content


def test_worker_http_auth_ownership_upload_guards_and_failure(http_runtime):
    runtime = http_runtime
    run, job_id, _, _ = make_run(runtime)
    path = runtime.base + "/api/v1/render-workers"
    assert requests.post(path + "/jobs/claim", headers=headers(token="invalid"), json={}).status_code == 401
    assert requests.post(path + "/jobs/claim", headers=headers(worker="desktop-b"), json={}).status_code == 401
    assert requests.post(runtime.base + "/api/v1/production/review", headers=headers(), json={}).status_code == 403
    assert requests.post(runtime.base + "/api/v1/production/review", headers={"Authorization": f"Bearer {TOKEN_A}"}, json={}).status_code == 403
    a, b = WorkerHttpClient(config(runtime)), WorkerHttpClient(config(runtime, "desktop-b", TOKEN_B))
    for client in (a, b):
        client.register(ffmpeg_version="verified-test")
        client.heartbeat()
    status = requests.get(path + "/status").json()
    assert status["configured"] and len(status["workers"]) == 2
    assert TOKEN_A not in json.dumps(status)
    job = a.claim_job()
    assert job["job_id"] == str(job_id) and b.claim_job() is None
    lookup = a.job_status(job)
    assert lookup['lease_valid'] and lookup['status'] == 'CLAIMED'
    assert 'manifest' not in lookup and 'download_url' not in json.dumps(lookup)
    assert requests.get(path + f'/jobs/{job_id}/status?attempt=1', headers=headers('desktop-b', TOKEN_B)).status_code == 409
    assert requests.get(path + f'/jobs/{job_id}/status?attempt=2', headers=headers()).status_code == 409
    assert requests.get(path + f"/jobs/{job_id}/manifest?attempt=1", headers=headers("desktop-b", TOKEN_B)).status_code == 409
    assert requests.get(path + f"/jobs/{job_id}/manifest?attempt=2", headers=headers()).status_code == 409
    a.heartbeat(job)
    manifest = a.get_manifest(job)
    assert all(item["download_url"].startswith(runtime.base) for item in manifest["artifacts"])
    for state in ("DOWNLOADING", "RENDERING", "UPLOADING"):
        a.report_progress(job, state)
    checksum = "a" * 64
    upload = a.request_output_upload(job, checksum, 100)
    payload = {"attempt": 1, "storage_ref": upload["storage_ref"], "checksum_sha256": checksum,
               "file_size_bytes": 100, "duration_seconds": 2, "width": 360, "height": 640,
               "fps": 30, "video_codec": "h264", "audio_codec": "aac"}
    assert requests.post(path + f"/jobs/{job_id}/complete", headers=headers(), json=payload).json()["detail"] == "OUTPUT_NOT_FOUND"
    # Object metadata lies; completion must still hash the actual uploaded bytes.
    runtime.storage.objects[upload["storage_ref"]] = (b"x" * 100, {"sha256": checksum})
    assert requests.post(path + f"/jobs/{job_id}/complete", headers=headers(), json=payload).json()["detail"] == "OUTPUT_CHECKSUM_MISMATCH"
    payload["storage_ref"] = "visionflow/unrelated/output.mp4"
    assert requests.post(path + f"/jobs/{job_id}/complete", headers=headers(), json=payload).json()["detail"] == "OUTPUT_NOT_AUTHORIZED"
    assert a.fail_job(job, "RENDER_FAILED", True)["status"] == "RETRYING"
    reclaimed = b.claim_job()
    assert reclaimed["attempt"] == 2
    assert requests.get(path + f"/jobs/{job_id}/manifest?attempt=1", headers=headers()).status_code == 409


def test_real_uploaded_completion_ack_loss_restart_reconciles(http_runtime, monkeypatch):
    from worker.control_plane_retry import ControlPlaneError
    runtime = http_runtime
    _, job_id, _, _ = make_run(runtime)
    worker = RemoteRenderWorker(config(runtime))
    actual = worker.client.complete_job
    def lost_ack(job, payload):
        actual(job, payload)
        raise ControlPlaneError('TRANSIENT_NETWORK')
    monkeypatch.setattr(worker.client, 'complete_job', lost_ack)
    try:
        with pytest.raises(ControlPlaneError): worker.run_once()
    finally:
        worker.shutdown()
    state_path = worker.config.work_dir / 'jobs' / str(job_id) / 'state.json'
    assert json.loads(state_path.read_text())['phase'] == 'COMPLETION_UNKNOWN'
    assert (state_path.parent / 'output' / 'final.mp4').is_file()
    restarted = RemoteRenderWorker(config(runtime))
    monkeypatch.setattr(restarted, '_render', lambda _: pytest.fail('No duplicate render'))
    try:
        assert restarted.run_once()
        assert json.loads(state_path.read_text())['phase'] == 'COMPLETED'
        assert runtime.storage.puts == 1
        with Session(runtime.engine) as session:
            assert session.get(RenderJob, job_id).attempt == 1
    finally:
        restarted.shutdown()


def test_real_render_survives_virtual_60_second_control_plane_outage(http_runtime, monkeypatch):
    from worker.control_plane_retry import ControlPlaneError, RetryPolicy
    runtime = http_runtime
    _, job_id, _, _ = make_run(runtime)
    worker = RemoteRenderWorker(config(runtime))
    now = [0.0]
    worker.client.policy = RetryPolicy(clock=lambda: now[0], jitter=lambda: 0)
    actual_render = worker._render
    def render_during_outage(spec):
        worker.client.policy.failure(ControlPlaneError('SERVER_UNAVAILABLE', status=503, retry_after=60))
        actual_render(spec)
    monkeypatch.setattr(worker, '_render', render_during_outage)
    try:
        with pytest.raises(ControlPlaneError): worker.run_once()
        state_path = worker.config.work_dir / 'jobs' / str(job_id) / 'state.json'
        assert json.loads(state_path.read_text())['phase'] == 'RENDER_OUTPUT_READY'
        assert (state_path.parent / 'output' / 'final.mp4').is_file()
        now[0] = 60
        monkeypatch.setattr(worker, '_render', lambda _: pytest.fail('Output must not be rendered twice'))
        monkeypatch.setattr(worker.client, 'fail_job', lambda *a: pytest.fail('Outage is not render failure'))
        assert worker.run_once()
        assert json.loads(state_path.read_text())['phase'] == 'COMPLETED'
        assert runtime.storage.puts == 1
    finally:
        worker.shutdown()


def test_offline_wait_restart_resume_stale_claim_and_cancellation(http_runtime):
    from production.orchestrator import orchestrator
    runtime = http_runtime
    run, job_id, _, _ = make_run(runtime)
    # No registered worker: durable wait, including resuming after backend restart.
    restored = asyncio.run(orchestrator.resume_run(run.id))
    assert restored.status.value == "WAITING_FOR_RENDER_WORKER"
    assert restored.render_artifact is None
    a, b = WorkerHttpClient(config(runtime)), WorkerHttpClient(config(runtime, "desktop-b", TOKEN_B))
    for client in (a, b):
        client.register(ffmpeg_version="verified-test")
    claimed = a.claim_job()
    with Session(runtime.engine) as session:
        session.get(RenderJob, job_id).lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()
    reclaimed = b.claim_job()  # The real HTTP claim path runs recovery.
    assert reclaimed["job_id"] == claimed["job_id"] and reclaimed["attempt"] == 2
    assert asyncio.run(orchestrator.cancel_run(run.id))
    with Session(runtime.engine) as session:
        assert load_remote_run(run.id, session).status.value == "CANCELLED"
        assert session.get(RenderJob, job_id).retryable is False
    response = requests.get(runtime.base + f"/api/v1/render-workers/jobs/{job_id}/manifest?attempt=2",
                             headers=headers("desktop-b", TOKEN_B))
    assert response.status_code == 409
    assert b.claim_job() is None


def test_portable_boundary_all_canonical_dependencies_and_guard(http_runtime):
    from production.canonical_renderer import CanonicalRenderSpec
    from production.remote_render import build_portable_manifest
    from production.remote_manifest import materialize_spec
    runtime = http_runtime
    files = {}
    for filename in ("video.mp4", "image.png", "voice.wav", "music.mp3", "subtitles.ass"):
        path = runtime.tmp / filename
        path.write_bytes((filename * 10).encode())
        files[filename] = path
    spec = CanonicalRenderSpec(run_id="run_all_inputs", output_path=runtime.tmp / "final.mp4", duration_seconds=2,
        video_sources=[{"file_path": str(files["video.mp4"]), "duration": 1}, {"file_path": str(files["image.png"]), "duration": 1}],
        audio_sources=[str(files["voice.wav"])], bgm_path=str(files["music.mp3"]), subtitles_ass_path=str(files["subtitles.ass"]))
    manifest = build_portable_manifest(spec, uuid.uuid4(), runtime.storage)
    assert {a.role for a in manifest.artifacts} == {"VIDEO", "IMAGE", "TTS", "MUSIC", "SUBTITLE"}
    serialized = json.dumps(manifest.persisted())
    assert str(runtime.tmp) not in serialized and "download_url" not in serialized
    local = {a.artifact_id: runtime.tmp / (a.artifact_id + ".local") for a in manifest.artifacts}
    materialized = materialize_spec(manifest, local, runtime.tmp / "out.mp4")
    assert materialized.bgm_path and materialized.subtitles_ass_path and len(materialized.video_sources) == 2
    spec.audio_sources = ["C:\\missing\\tts.wav"]
    with pytest.raises(ValueError, match="REMOTE_RENDER_INPUT_NOT_PORTABLE"):
        build_portable_manifest(spec, uuid.uuid4(), runtime.storage)
    hostile = manifest.persisted()
    hostile["artifacts"][0]["storage_ref"] = "file:///tmp/source.mp4"
    with pytest.raises(ValueError):
        PortableRenderManifest.model_validate(hostile)
