"""Worker transport, cache-integrity, startup and lease tests; no database access."""
from __future__ import annotations

import hashlib
import subprocess
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from production.canonical_renderer import CanonicalRenderSpec
from production.remote_manifest import PortableArtifact, PortableRenderManifest
from worker.remote_render_worker import (
    ArtifactCache, RemoteRenderWorker, WorkerConfig, WorkerError, WorkerHttpClient,
    _job_id, materialize_render_spec,
)


class Response:
    def __init__(self, status=200, payload=None, body=b""):
        self.status_code = status
        self.payload = payload if payload is not None else {}
        self.body = body
        self.closed = False

    def json(self):
        return self.payload

    def iter_content(self, chunk_size):
        yield self.body

    def close(self):
        self.closed = True


class Session:
    def __init__(self, responses=()):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if not self.responses:
            return Response()
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture
def config(tmp_path):
    return WorkerConfig(
        api_base_url="https://api.example.com", worker_id="test-worker", worker_token="dedicated-test-token",
        work_dir=tmp_path, heartbeat_seconds=.02,
    )


def artifact(body=b"media", **updates):
    data = dict(
        artifact_id="asset_1", role="IMAGE", storage_ref="visionflow/runs/run_1/assets/image.png",
        checksum_sha256=hashlib.sha256(body).hexdigest(), size_bytes=len(body),
        mime_type="image/png", download_url="https://objects.example.com/input?signature=scoped",
    )
    return PortableArtifact.model_validate({**data, **updates})


def test_config_defaults_and_no_database_dependency(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("VISIONFLOW_API_BASE_URL", "https://api.example.com/api/v1/")
    monkeypatch.setenv("VISIONFLOW_WORKER_TOKEN", "token")
    monkeypatch.setenv("VISIONFLOW_WORKER_WORK_DIR", str(tmp_path))
    parsed = WorkerConfig.from_env()
    assert parsed.api_base_url == "https://api.example.com/api/v1"
    assert parsed.poll_seconds > 0
    assert parsed.max_render_jobs == 1


@pytest.mark.parametrize("url", [
    "http://api.example.com", "http://127.0.0.1:8000", "https://user:secret@api.example.com",
    "https://api.example.com/arbitrary", "https://api.example.com?token=x", "https://127.0.0.1",
    "https://169.254.169.254", "file:///tmp/api", "https://api.example.com/#bad",
])
def test_config_rejects_unsafe_api_urls(tmp_path, url):
    with pytest.raises(ValueError):
        WorkerConfig(url, "worker", "token", tmp_path)


def test_loopback_http_requires_explicit_test_config(tmp_path):
    parsed = WorkerConfig("http://127.0.0.1:9999", "worker", "token", tmp_path, allow_loopback_http=True)
    assert parsed.api_base_url == "http://127.0.0.1:9999/api/v1"
    with pytest.raises(ValueError):
        WorkerConfig("http://api.example.com", "worker", "token", tmp_path, allow_loopback_http=True)
    with pytest.raises(ValueError):
        WorkerConfig("https://api.example.com", "worker", "token", tmp_path, max_render_jobs=2)


def test_http_client_uses_identity_headers_and_no_job_is_normal(config):
    session = Session([Response(204)])
    client = WorkerHttpClient(config, session=session)
    assert client.claim_job() is None
    method, url, options = session.calls[0]
    assert method == "POST"
    assert url == "https://api.example.com/api/v1/render-workers/jobs/claim"
    assert options["headers"] == {"Authorization": "Bearer dedicated-test-token", "X-VisionFlow-Worker-ID": "test-worker"}
    assert options["allow_redirects"] is False


@pytest.mark.parametrize("status", [301, 302, 307, 308, 401, 403])
def test_worker_client_rejects_redirects_and_auth_errors_without_secrets(config, status):
    client = WorkerHttpClient(config, session=Session([Response(status)]))
    with pytest.raises(WorkerError) as error:
        client.claim_job()
    assert not error.value.retryable
    assert "token" not in str(error.value)


def test_client_methods_match_protocol_and_complete_allows_backend_qc(config):
    session = Session()
    client = WorkerHttpClient(config, session=session)
    job = {"job_id": str(uuid.uuid4()), "run_id": "run_1", "attempt": 2}
    client.register(ffmpeg_version="ffmpeg 7")
    client.heartbeat(job)
    client.get_manifest(job)
    client.report_progress(job, "DOWNLOADING")
    client.request_output_upload(job, "a" * 64, 100)
    client.complete_job(job, {"storage_ref": "visionflow/output/final.mp4"})
    client.fail_job(job, "RENDER_FAILED", True)
    assert "worker_id" not in session.calls[0][2]["json"]
    assert session.calls[1][2]["json"] == {"job_id": job["job_id"], "attempt": 2}
    assert session.calls[2][1].endswith("/manifest?attempt=2")
    assert session.calls[5][2]["timeout"] >= 180
    assert session.calls[6][2]["json"] == {"attempt": 2, "error_code": "RENDER_FAILED", "retryable": True}


def test_cache_download_checksums_and_reuses_without_credentials(config):
    payload = b"verified media"
    reply = Response(body=payload)
    session = Session([reply])
    cache = ArtifactCache(config, session)
    dependency = artifact(payload)
    path = cache.obtain(dependency)
    assert path == config.work_dir / "cache" / dependency.checksum_sha256
    assert path.read_bytes() == payload
    assert cache.obtain(dependency) == path
    assert len(session.calls) == 1
    assert session.calls[0][2]["headers"] == {}
    assert session.calls[0][2]["allow_redirects"] is False
    assert reply.closed
    assert not list(cache.directory.glob("*.part"))


def test_corrupt_cache_is_replaced_and_corrupt_download_is_never_cached(config):
    expected = b"good"
    dependency = artifact(expected)
    session = Session([Response(body=expected), Response(body=b"evil")])
    cache = ArtifactCache(config, session)
    target = cache.directory / dependency.checksum_sha256
    target.write_bytes(b"bad!")
    assert cache.obtain(dependency).read_bytes() == expected
    target.unlink()
    with pytest.raises(WorkerError, match="ASSET_CHECKSUM_MISMATCH") as error:
        cache.obtain(dependency)
    assert not error.value.retryable
    assert not target.exists()
    assert not list(cache.directory.glob("*.part"))


@pytest.mark.parametrize("status,url", [(302, "https://objects.example.com/input"), (200, "http://objects.example.com/input"), (200, "https://169.254.169.254/token")])
def test_cache_rejects_redirects_and_unsafe_downloads(config, status, url):
    cache = ArtifactCache(config, Session([Response(status, body=b"media")]))
    with pytest.raises(WorkerError, match="ASSET_DOWNLOAD_FAILED"):
        cache.obtain(artifact(download_url=url))
    assert not list(cache.directory.iterdir())


def test_cache_enforces_budget_and_discards_old_entries(tmp_path):
    config = WorkerConfig("https://api.example.com", "worker", "token", tmp_path, cache_max_bytes=8, asset_max_bytes=4)
    cache = ArtifactCache(config, Session([Response(body=b"new!")]))
    first, second = cache.directory / ("a" * 64), cache.directory / ("b" * 64)
    first.write_bytes(b"old1")
    second.write_bytes(b"old2")
    target = cache.obtain(artifact(b"new!"))
    assert target.exists()
    assert sum(path.stat().st_size for path in cache.directory.iterdir()) <= 8
    with pytest.raises(WorkerError):
        cache.obtain(artifact(b"too much data"))


def test_materialization_preserves_image_and_audio_extensions(config):
    image = artifact(b"image")
    audio = artifact(b"audio", artifact_id="tts_1", role="TTS", mime_type="audio/wav", storage_ref="visionflow/runs/run_1/assets/tts.wav")
    manifest = PortableRenderManifest(
        job_id=uuid.uuid4(), run_id="run_1",
        render_spec={"duration_seconds": 1, "video_sources": [{"artifact_id": image.artifact_id, "duration": 1}], "audio_sources": [audio.artifact_id]},
        artifacts=[image, audio],
    )
    cache = ArtifactCache(config, Session([Response(body=b"image"), Response(body=b"audio")]))
    local = materialize_render_spec(manifest, cache, config.work_dir / "jobs" / str(manifest.job_id))
    assert Path(local.video_sources[0]["file_path"]).suffix == ".png"
    assert Path(local.audio_sources[0]).suffix == ".wav"
    assert Path(local.audio_sources[0]).read_bytes() == b"audio"
    assert local.output_path.name == "final.mp4"
    assert not local.output_path.exists()


@pytest.mark.parametrize("bad", ["../../escape", "C:\\Windows", "/tmp/evil", "?anything", "{12345678-1234-1234-1234-123456789000}"])
def test_job_ids_cannot_escape_work_directory(bad):
    with pytest.raises(WorkerError):
        _job_id(bad)


def test_manifest_rejects_commands_unknown_fields_and_missing_assets():
    base = {"job_id": str(uuid.uuid4()), "run_id": "run_1", "render_spec": {"duration_seconds": 1}, "artifacts": []}
    with pytest.raises(ValidationError):
        PortableRenderManifest.model_validate({**base, "shell_command": "echo bad"})
    with pytest.raises(ValidationError):
        PortableRenderManifest.model_validate({**base, "render_spec": {"duration_seconds": 1, "ffmpeg_command": "-y"}})
    with pytest.raises(ValidationError):
        PortableRenderManifest.model_validate({**base, "render_spec": {"duration_seconds": 1, "audio_sources": ["missing"]}})


def test_upload_scoped_authorization_never_receives_worker_token(config, tmp_path):
    output = tmp_path / "final.mp4"
    output.write_bytes(b"mp4")
    transport = Session([Response(200)])
    client = WorkerHttpClient(config, artifact_session=transport)
    client.upload({"upload_url": "https://objects.example.com/output?signature=scope", "headers": {"Content-Type": "video/mp4"}}, output)
    method, _, options = transport.calls[0]
    assert method == "PUT"
    assert options["headers"] == {"Content-Type": "video/mp4"}
    assert options["allow_redirects"] is False
    with pytest.raises(WorkerError, match="UPLOAD_FAILED"):
        client.upload({"upload_url": "https://objects.example.com/output", "headers": {"Authorization": "unsafe"}}, output)
    assert len(transport.calls) == 1


def test_missing_ffmpeg_prevents_registration_and_claim(config):
    session = Session()
    worker = RemoteRenderWorker(config, WorkerHttpClient(config, session=session))
    worker.renderer.ffmpeg_bin = str(config.work_dir / "ffmpeg-does-not-exist")
    with pytest.raises(WorkerError, match="FFMPEG_UNAVAILABLE"):
        worker.run_once()
    assert session.calls == []


def test_heartbeat_runs_independently_with_active_attempt(config):
    session = Session()
    worker = RemoteRenderWorker(config, WorkerHttpClient(config, session=session))
    job = {"job_id": str(uuid.uuid4()), "run_id": "run_1", "attempt": 3}
    worker._active = job
    thread = threading.Thread(target=worker._heartbeat_loop)
    thread.start()
    deadline = time.monotonic() + 2
    while len(session.calls) < 2 and time.monotonic() < deadline:
        time.sleep(.01)
    worker.heartbeat_stopping.set()
    thread.join(timeout=1)
    assert len(session.calls) >= 2
    assert all(call[2]["json"] == {"job_id": job["job_id"], "attempt": 3} for call in session.calls)


def test_worker_reports_safe_error_and_releases_active_job(config, monkeypatch):
    job = {"job_id": str(uuid.uuid4()), "run_id": "run_1", "attempt": 1}
    session = Session([Response(payload=job), Response(), Response()])
    worker = RemoteRenderWorker(config, WorkerHttpClient(config, session=session))
    worker._started = True
    def broken(_):
        raise RuntimeError("https://signed.example.com?secret=must-not-leak")
    monkeypatch.setattr(worker, "_process", broken)
    assert worker.run_once()
    assert worker._active is None
    assert session.calls[-1][2]["json"] == {"attempt": 1, "error_code": "WORKER_INTERNAL_ERROR", "retryable": True}


def test_no_work_returns_without_busy_loop(config):
    session = Session([Response(204)])
    worker = RemoteRenderWorker(config, WorkerHttpClient(config, session=session))
    worker._started = True
    assert not worker.run_once()
    assert len(session.calls) == 1


@pytest.mark.parametrize("with_music", [False, True])
def test_worker_spawn_executes_real_canonical_ffmpeg_and_heartbeats(config, with_music):
    """Small real MP4 catches Windows spawn/FFmpeg defects before the DB E2E."""
    session = Session()
    worker = RemoteRenderWorker(config, WorkerHttpClient(config, session=session))
    worker.startup()
    job = {"job_id": str(uuid.uuid4()), "run_id": "run_real_ffmpeg_worker", "attempt": 1}
    worker._active = job
    spec = CanonicalRenderSpec(
        run_id=job["run_id"], output_path=config.work_dir / "real-output" / "final.mp4",
        duration_seconds=1, width=64, height=64, fps=10,
    )
    if with_music:
        voice = config.work_dir / "voice.wav"
        subprocess.run([worker.renderer.ffmpeg_bin, "-y", "-f", "lavfi", "-i",
                        "sine=frequency=440:duration=1", str(voice)], check=True, capture_output=True)
        spec.audio_sources = [str(voice)]
        spec.bgm_path = str(voice)
    try:
        worker._render(spec)
        probe = worker.renderer.probe(spec.output_path)
        assert probe.has_video and probe.has_audio
        assert probe.file_size_bytes > 0
        assert probe.duration_seconds >= 1
        assert (probe.width, probe.height, probe.fps) == (64, 64, 10)
        assert any(call[1].endswith("/heartbeat") and call[2]["json"].get("job_id") == job["job_id"] for call in session.calls)
    finally:
        worker._active = None
        worker.shutdown()


def test_editor_plan_type_and_graphic_fallback_portable_boundary(tmp_path):
    import uuid
    from production.contracts import EditorPlan, EditorPlanType, ScenePlan, ShotPlan
    from production.remote_render import build_portable_manifest
    from production.render_handoff import render_handoff

    class MockStorage:
        def __init__(self):
            self.saved = {}
        def put_file(self, ref, path, mime):
            self.saved[ref] = path.read_bytes()

    storage = MockStorage()
    audio_file = tmp_path / "narration.mp3"
    audio_file.write_bytes(b"mock-mp3-narration-audio")

    # Final plan with lowercase 'final'
    editor_plan = EditorPlan(
        plan_id="plan_test_01",
        run_id="run_test_01",
        plan_type="final",
        duration_seconds=5.0,
        scenes=[
            ScenePlan(
                scene_id="scene_001",
                narration="Hello world",
                audio_file_path=str(audio_file),
                actual_duration_seconds=5.0,
                timeline_start=0.0,
                timeline_end=5.0,
                shots=[
                    ShotPlan(
                        shot_id="shot_001_01",
                        asset_id="gfx_01",
                        media_url="/static/motion_typography_backdrop.mp4",
                        is_graphic_fallback=True,
                        timeline_start=0.0,
                        timeline_end=5.0,
                        duration_sec=5.0,
                    )
                ]
            )
        ]
    )

    spec = render_handoff.build_spec(editor_plan, "run_test_01", strict_inputs=True)
    assert spec.is_graphic_fallback is True
    assert len(spec.video_sources) == 0
    assert spec.audio_sources == [str(audio_file)]

    manifest = build_portable_manifest(spec, uuid.uuid4(), storage)
    assert len(manifest.artifacts) == 1
    assert manifest.artifacts[0].role == "TTS"

