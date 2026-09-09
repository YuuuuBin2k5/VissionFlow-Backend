"""Outbound-only render worker. Start with ``python -m worker.remote_render_worker``.

Coordination uses the worker API; media travels through scoped object-store URLs.
This module deliberately has no database or control-plane dependency.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import logging
import math
import multiprocessing
import os
import platform
import queue
import re
import shutil
import signal
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests
import httpx
from worker.control_plane_retry import ControlPlaneError, RetryPolicy, classify, retry_delay

from production.canonical_renderer import CanonicalFFmpegRenderer, CanonicalRenderSpec

logger = logging.getLogger("visionflow.remote_render_worker")
WORKER_VERSION = "canonical-v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_WORKER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
_MIME_EXTENSIONS = {
    "video/mp4": ".mp4", "video/webm": ".webm", "video/quicktime": ".mov",
    "video/x-matroska": ".mkv", "image/png": ".png", "image/jpeg": ".jpg",
    "image/webp": ".webp", "image/gif": ".gif", "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3", "audio/wav": ".wav", "audio/x-wav": ".wav",
    "audio/flac": ".flac", "audio/ogg": ".ogg", "audio/mp4": ".m4a",
    "audio/aac": ".aac", "text/x-ssa": ".ass", "text/x-ass": ".ass",
    "application/x-ass": ".ass", "text/plain": ".ass",
}


class WorkerError(RuntimeError):
    """Safe machine-readable error; never carries URLs, tokens or FFmpeg logs."""

    def __init__(self, code: str, retryable: bool = True):
        super().__init__(code)
        self.code = code
        self.retryable = retryable


def _validate_url(url: str, allow_loopback_http: bool = False) -> str:
    parsed = urlsplit(url)
    if parsed.username or parsed.password or parsed.fragment or not parsed.hostname:
        raise ValueError("Worker URLs must have a host and no credentials or fragment")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        address = None
    is_loopback = parsed.hostname.lower() == "localhost" or bool(address and address.is_loopback)
    if parsed.scheme != "https":
        if not (allow_loopback_http and parsed.scheme == "http" and is_loopback):
            raise ValueError("Worker transport requires HTTPS (HTTP is allowed only for explicit loopback tests)")
    if address and not address.is_global and not (allow_loopback_http and is_loopback):
        raise ValueError("Worker transport does not accept private network addresses")
    if parsed.hostname.lower() == "localhost" and not allow_loopback_http:
        raise ValueError("Worker transport does not accept localhost")
    return url


def _job_id(value: Any) -> str:
    value = str(value)
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError):
        raise WorkerError("WORKER_INTERNAL_ERROR", retryable=False) from None
    if value not in {str(parsed), parsed.hex}:
        raise WorkerError("WORKER_INTERNAL_ERROR", retryable=False)
    return value


@dataclass(frozen=True)
class WorkerConfig:
    api_base_url: str
    worker_id: str
    worker_token: str
    work_dir: Path
    poll_seconds: float = 20.0
    max_render_jobs: int = 1
    heartbeat_seconds: float = 25.0
    idle_heartbeat_seconds: float = 60.0
    connect_timeout_seconds: float = 10.0
    write_timeout_seconds: float = 15.0
    completion_timeout_seconds: float = 120.0
    rate_cooldown_seconds: float = 30.0
    rate_cooldown_max_seconds: float = 120.0
    http_timeout_seconds: float = 30.0
    allow_loopback_http: bool = False
    cache_max_bytes: int = 10 * 1024**3
    asset_max_bytes: int = 2 * 1024**3
    render_timeout_seconds: float = 3600.0

    def __post_init__(self) -> None:
        base = _validate_url(self.api_base_url.rstrip("/"), self.allow_loopback_http)
        parsed = urlsplit(base)
        if parsed.path not in {"", "/api/v1"} or parsed.query:
            raise ValueError("VISIONFLOW_API_BASE_URL must be an origin or end in /api/v1")
        if not _WORKER_ID.fullmatch(self.worker_id):
            raise ValueError("Invalid VISIONFLOW_WORKER_ID")
        if not self.worker_token or any(c.isspace() or ord(c) < 32 or ord(c) > 126 for c in self.worker_token) or len(self.worker_token) > 4096:
            raise ValueError("VISIONFLOW_WORKER_TOKEN is required and must not contain whitespace")
        if self.max_render_jobs != 1:
            raise ValueError("VISIONFLOW_MAX_RENDER_JOBS currently supports exactly 1")
        for value in (self.poll_seconds, self.heartbeat_seconds, self.idle_heartbeat_seconds,
                      self.connect_timeout_seconds, self.write_timeout_seconds, self.completion_timeout_seconds,
                      self.rate_cooldown_seconds, self.rate_cooldown_max_seconds,
                      self.http_timeout_seconds, self.render_timeout_seconds):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("Worker timeouts and intervals must be positive and finite")
        if self.heartbeat_seconds > 30 or self.idle_heartbeat_seconds > 60:
            raise ValueError("Heartbeat cadence must remain below lease/freshness expiry")
        if self.asset_max_bytes <= 0 or self.cache_max_bytes < self.asset_max_bytes:
            raise ValueError("Worker cache budget must accommodate at least one asset")
        object.__setattr__(self, "api_base_url", base if parsed.path else base + "/api/v1")
        object.__setattr__(self, "work_dir", Path(self.work_dir).resolve())

    @classmethod
    def from_env(cls) -> "WorkerConfig":
        default_id = re.sub(r"[^A-Za-z0-9_.-]", "-", platform.node()).strip("-._")[:100] or "desktop-main"
        return cls(
            api_base_url=os.environ.get("VISIONFLOW_API_BASE_URL", ""),
            worker_id=os.environ.get("VISIONFLOW_WORKER_ID", default_id),
            worker_token=os.environ.get("VISIONFLOW_WORKER_TOKEN", ""),
            work_dir=Path(os.environ.get("VISIONFLOW_WORKER_WORK_DIR", str(Path.cwd() / ".remote-render-worker"))),
            poll_seconds=max(15, float(os.environ.get("VISIONFLOW_WORKER_IDLE_POLL_SECONDS", "20"))),
            heartbeat_seconds=float(os.environ.get("VISIONFLOW_WORKER_ACTIVE_HEARTBEAT_SECONDS", "25")),
            idle_heartbeat_seconds=float(os.environ.get("VISIONFLOW_WORKER_IDLE_HEARTBEAT_SECONDS", "60")),
            connect_timeout_seconds=float(os.environ.get("VISIONFLOW_WORKER_CONNECT_TIMEOUT_SECONDS", "10")),
            write_timeout_seconds=float(os.environ.get("VISIONFLOW_WORKER_WRITE_TIMEOUT_SECONDS", "15")),
            http_timeout_seconds=float(os.environ.get("VISIONFLOW_WORKER_READ_TIMEOUT_SECONDS", "30")),
            completion_timeout_seconds=float(os.environ.get("VISIONFLOW_WORKER_COMPLETE_TIMEOUT_SECONDS", "120")),
            rate_cooldown_seconds=float(os.environ.get("VISIONFLOW_WORKER_RATE_COOLDOWN_SECONDS", "30")),
            rate_cooldown_max_seconds=float(os.environ.get("VISIONFLOW_WORKER_RATE_COOLDOWN_MAX_SECONDS", "120")),
            max_render_jobs=int(os.environ.get("VISIONFLOW_MAX_RENDER_JOBS", "1")),
            allow_loopback_http=os.environ.get("VISIONFLOW_WORKER_ALLOW_LOOPBACK_HTTP") == "1",
        )


class WorkerHttpClient:
    def __init__(self, config: WorkerConfig, session: Any = None, artifact_session: Any = None, policy=None):
        self.config = config
        self.session = session or httpx.Client(trust_env=False, follow_redirects=False)
        self.artifact_session = artifact_session or requests.Session()
        self.policy = policy or RetryPolicy(cooldown=config.rate_cooldown_seconds,
                                           cooldown_max=config.rate_cooldown_max_seconds)
        self._request_lock = threading.Lock()
        self._heartbeat_lock = threading.Lock()
        self.metrics = {"requests": 0, "heartbeats": 0, "heartbeat_success": 0,
                        "claims": 0, "http_429": 0, "circuit_open": 0, "retry_scheduled": 0}
        # Do not inherit ~/.netrc authentication or ambient proxy credentials.
        for transport in (self.session, self.artifact_session):
            if isinstance(transport, requests.Session):
                transport.trust_env = False

    def _request(self, method: str, path: str, payload: dict | None = None) -> Any:
        headers = {"Authorization": f"Bearer {self.config.worker_token}",
                   "X-VisionFlow-Worker-ID": self.config.worker_id, "User-Agent": "VisionFlow-RenderWorker/1.0"}
        # Serializing admission AND I/O prevents simultaneous half-open probes,
        # overlapping heartbeats and concurrent use of requests.Session.
        with self._request_lock:
            self.policy.admit()
            response = None
            try:
                self.metrics["requests"] += 1
                if path == "/heartbeat": self.metrics["heartbeats"] += 1
                if path == "/jobs/claim": self.metrics["claims"] += 1
                options = {"timeout": (self.config.connect_timeout_seconds,
                           self.config.completion_timeout_seconds if path.endswith("/complete") else self.config.http_timeout_seconds),
                           "allow_redirects": False}
                if isinstance(self.session, httpx.Client):
                    options = {"timeout": httpx.Timeout(connect=self.config.connect_timeout_seconds,
                               read=self.config.completion_timeout_seconds if path.endswith("/complete") else self.config.http_timeout_seconds,
                               write=self.config.write_timeout_seconds, pool=self.config.connect_timeout_seconds),
                               "follow_redirects": False}
                response = self.session.request(
                    method, self.config.api_base_url + "/render-workers" + path,
                    headers=headers, json=payload,
                    **options,
                )
                if not 200 <= response.status_code < 300:
                    raise classify(response)
                result = None if response.status_code == 204 else response.json()
                self.policy.success()
                response_headers = {str(k).lower(): str(v) for k, v in getattr(response, "headers", {}).items()}
                # A reset header alone does not mean a successful request exhausted quota.
                exhausted = any(response_headers.get(k) == "0" for k in ("ratelimit-remaining", "x-ratelimit-remaining"))
                self.policy.until = self.policy.clock() + retry_delay(response_headers if exhausted else {
                    "retry-after": response_headers.get("retry-after", "")})
                if path == "/heartbeat": self.metrics["heartbeat_success"] += 1
                return result
            except Exception as exc:
                error = exc if isinstance(exc, ControlPlaneError) else ControlPlaneError("TRANSIENT_NETWORK")
                before = self.policy.circuit
                self.policy.failure(error)
                if error.retryable: self.metrics["retry_scheduled"] += 1
                if error.status == 429: self.metrics["http_429"] += 1
                if self.policy.circuit == "OPEN" and before != "OPEN": self.metrics["circuit_open"] += 1
                logger.warning("Control Plane %s %s HTTP %s %s cf-ray=%s retry_in=%.1fs state=%s circuit=%s",
                               method, path.split("?")[0], error.status or "network", error.category,
                               error.cf_ray or "-", error.retry_after, self.policy.health, self.policy.circuit)
                raise error from None
            finally:
                if response is not None: response.close()

    def register(self, *, ffmpeg_version: str, renderer_version: str = WORKER_VERSION) -> dict:
        return self._request("POST", "/register", {
            "platform": platform.system(), "renderer_version": renderer_version,
            "ffmpeg_version": ffmpeg_version[:200], "capabilities": ["canonical-v1", "ffmpeg", "h264", "aac"],
            "max_concurrent_jobs": self.config.max_render_jobs,
        })

    def heartbeat(self, job: dict | None = None) -> dict:
        if not self._heartbeat_lock.acquire(blocking=False):
            return {"status": "COALESCED"}
        try:
            return self._request("POST", "/heartbeat", {} if job is None else {"job_id": job["job_id"], "attempt": job["attempt"]})
        finally:
            self._heartbeat_lock.release()

    def job_status(self, job: dict) -> dict:
        return self._request("GET", f"/jobs/{_job_id(job['job_id'])}/status?attempt={int(job['attempt'])}")

    def claim_job(self) -> dict | None:
        return self._request("POST", "/jobs/claim", {})

    def get_manifest(self, job: dict) -> dict:
        return self._request("GET", f"/jobs/{_job_id(job['job_id'])}/manifest?attempt={int(job['attempt'])}")

    def report_progress(self, job: dict, status: str) -> dict:
        return self._request("POST", f"/jobs/{_job_id(job['job_id'])}/progress", {"attempt": job["attempt"], "status": status})

    def request_output_upload(self, job: dict, checksum: str, size: int) -> dict:
        return self._request("POST", f"/jobs/{_job_id(job['job_id'])}/output-upload", {
            "attempt": job["attempt"], "checksum_sha256": checksum, "file_size_bytes": size,
        })

    def complete_job(self, job: dict, completion: dict) -> dict:
        return self._request("POST", f"/jobs/{_job_id(job['job_id'])}/complete", {**completion, "attempt": job["attempt"]})

    def fail_job(self, job: dict, error_code: str, retryable: bool) -> dict:
        return self._request("POST", f"/jobs/{_job_id(job['job_id'])}/fail", {
            "attempt": job["attempt"], "error_code": error_code, "retryable": retryable,
        })

    def upload(self, authorization: dict, output: Path) -> None:
        try:
            url = _validate_url(authorization["upload_url"], self.config.allow_loopback_http)
            headers = dict(authorization.get("headers") or {})
            allowed = {"content-type", "content-length", "x-amz-meta-sha256", "x-amz-checksum-sha256"}
            if any(str(key).lower() not in allowed for key in headers):
                raise ValueError("Unsupported object upload header")
            with output.open("rb") as stream:
                response = self.artifact_session.request("PUT", url, data=stream, headers=headers,
                    timeout=self.config.http_timeout_seconds, allow_redirects=False)
            if not 200 <= response.status_code < 300:
                raise ValueError("Upload rejected")
        except Exception:
            raise WorkerError("UPLOAD_FAILED") from None


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ArtifactCache:
    def __init__(self, config: WorkerConfig, session: Any = None):
        self.config = config
        self.directory = config.work_dir / "cache"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.session = session or requests.Session()
        if isinstance(self.session, requests.Session):
            self.session.trust_env = False

    def _make_room(self, size: int, keep: Path) -> None:
        entries = [p for p in self.directory.iterdir() if p.is_file() and not p.is_symlink() and _SHA256.fullmatch(p.name)]
        current = sum(p.stat().st_size for p in entries)
        for path in sorted(entries, key=lambda p: p.stat().st_mtime):
            if current + size <= self.config.cache_max_bytes:
                break
            if path != keep:
                current -= path.stat().st_size
                path.unlink()
        if current + size > self.config.cache_max_bytes or shutil.disk_usage(self.directory).free < size + 16 * 1024**2:
            raise WorkerError("ASSET_DOWNLOAD_FAILED")

    def obtain(self, artifact: Any, stopping: threading.Event | None = None) -> Path:
        checksum, expected_size = artifact.checksum_sha256, artifact.size_bytes
        if not _SHA256.fullmatch(checksum) or not 0 < expected_size <= self.config.asset_max_bytes:
            raise WorkerError("ASSET_DOWNLOAD_FAILED", False)
        target = self.directory / checksum
        if target.is_symlink():
            raise WorkerError("ASSET_DOWNLOAD_FAILED", False)
        if target.exists():
            if target.stat().st_size == expected_size and file_sha256(target) == checksum:
                target.touch()
                return target
            target.unlink()
        self._make_room(expected_size, target)
        temporary = self.directory / (checksum + "." + uuid.uuid4().hex + ".part")
        try:
            url = _validate_url(artifact.download_url or "", self.config.allow_loopback_http)
            response = self.session.request("GET", url, headers={}, stream=True,
                timeout=self.config.http_timeout_seconds, allow_redirects=False)
            try:
                if response.status_code != 200:
                    raise WorkerError("ASSET_DOWNLOAD_FAILED")
                received = 0
                digest = hashlib.sha256()
                with temporary.open("xb") as stream:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if stopping and stopping.is_set():
                            raise WorkerError("WORKER_INTERNAL_ERROR")
                        received += len(chunk)
                        if received > expected_size:
                            raise WorkerError("ASSET_CHECKSUM_MISMATCH", False)
                        digest.update(chunk)
                        stream.write(chunk)
                    stream.flush()
                    os.fsync(stream.fileno())
                if received != expected_size or digest.hexdigest() != checksum:
                    raise WorkerError("ASSET_CHECKSUM_MISMATCH", False)
                os.replace(temporary, target)
                return target
            finally:
                response.close()
        except WorkerError:
            raise
        except Exception:
            raise WorkerError("ASSET_DOWNLOAD_FAILED") from None
        finally:
            temporary.unlink(missing_ok=True)


def materialize_render_spec(manifest: Any, cache: ArtifactCache, job_dir: Path, stopping: threading.Event | None = None) -> CanonicalRenderSpec:
    from production.remote_manifest import materialize_spec

    work = job_dir / "work"
    work.mkdir(parents=True, exist_ok=True)
    output = job_dir / "output"
    output.mkdir(parents=True, exist_ok=True)
    local: dict[str, Path] = {}
    for artifact in manifest.artifacts:
        cached = cache.obtain(artifact, stopping)
        extension = _MIME_EXTENSIONS.get(artifact.mime_type, ".bin")
        # A locally assigned ordinal avoids using logical IDs as filesystem paths.
        destination = work / f"asset_{len(local):04d}{extension}"
        if destination.exists() or destination.is_symlink():
            destination.unlink()
        try:
            os.link(cached, destination)
        except OSError:
            shutil.copyfile(cached, destination)
        local[artifact.artifact_id] = destination.resolve()
    return materialize_spec(manifest, local, output / "final.mp4")


def _render_child(spec: CanonicalRenderSpec, ffmpeg: str, ffprobe: str, results: Any) -> None:
    # Keep child diagnostics away from protocol responses (which must not expose paths).
    if os.name != "nt":
        os.setsid()
    try:
        CanonicalFFmpegRenderer(ffmpeg, ffprobe).render(spec)
        results.put(True)
    except Exception:
        results.put(False)


class RemoteRenderWorker:
    def __init__(self, config: WorkerConfig, client: WorkerHttpClient | None = None):
        self.config = config
        self.client = client or WorkerHttpClient(config)
        self.renderer = CanonicalFFmpegRenderer()
        self.cache = ArtifactCache(config, self.client.artifact_session)
        self.stopping = threading.Event()
        self.heartbeat_stopping = threading.Event()
        self.lease_lost = threading.Event()
        self._active: dict | None = None
        self._lock = threading.Lock()
        self._heartbeat: threading.Thread | None = None
        self._render_process: Any = None
        self._started = False
        self._registered = False
        self._instance_file = None

    def _acquire_instance(self):
        if self._instance_file is not None:
            return
        self.config.work_dir.mkdir(parents=True, exist_ok=True)
        path = self.config.work_dir / "worker.lock"
        if path.is_symlink():
            raise WorkerError("UNSAFE_WORK_DIRECTORY", False)
        stream = path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                if path.stat().st_size == 0:
                    stream.write(b"0"); stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            stream.close()
            raise WorkerError("WORKER_ALREADY_RUNNING", False) from None
        self._instance_file = stream

    def _state_path(self, job):
        directory = self.config.work_dir / "jobs" / _job_id(job["job_id"])
        directory.mkdir(parents=True, exist_ok=True)
        if directory.is_symlink() or directory.resolve().parent != (self.config.work_dir / "jobs").resolve():
            raise WorkerError("WORKER_INTERNAL_ERROR", False)
        return directory / "state.json"

    def _save_state(self, state):
        """No credentials or signed URLs. Atomic replacement survives interrupted ack."""
        path = self._state_path(state["job"])
        temporary = path.with_name("state." + uuid.uuid4().hex + ".tmp")
        try:
            with temporary.open("x", encoding="utf-8") as stream:
                json.dump(state, stream, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _pending_states(self):
        states = []
        for path in sorted((self.config.work_dir / "jobs").glob("*/state.json")):
            try:
                if path.is_symlink() or path.parent.is_symlink():
                    raise ValueError("Unsafe state path")
                state = json.loads(path.read_text(encoding="utf-8"))
                if self._state_path(state["job"]) != path or state["worker_id"] != self.config.worker_id or state["api_base_url"] != self.config.api_base_url:
                    raise ValueError("State identity mismatch")
                if (state["phase"] not in {"RENDER_OUTPUT_READY", "UPLOAD_PENDING", "COMPLETION_PENDING",
                        "COMPLETION_UNKNOWN", "RECONCILIATION_REQUIRED", "COMPLETED"}
                        or type(state["job"].get("attempt")) is not int or state["job"]["attempt"] < 1
                        or type(state.get("upload_complete")) is not bool
                        or not _SHA256.fullmatch(state["completion"]["checksum_sha256"])
                        or (state["upload_complete"] and not state["completion"].get("storage_ref"))):
                    raise ValueError("Invalid checkpoint")
                if state["phase"] != "COMPLETED": states.append(state)
            except Exception:
                # Corrupt state may represent a successfully uploaded job. Fail closed.
                raise WorkerError("LOCAL_STATE_REQUIRES_REVIEW", False) from None
        return states

    def _resume_output(self, state):
        job, completion = state["job"], state["completion"]
        status = self.client.job_status(job)
        accepted = status.get("completion") or {}
        if status.get("status") == "COMPLETED":
            if (accepted.get("checksum_sha256") == completion["checksum_sha256"] and
                    accepted.get("storage_ref") == completion.get("storage_ref")):
                state["phase"] = "COMPLETED"
                self._save_state(state)
                return accepted
            state["phase"] = "RECONCILIATION_REQUIRED"
            self._save_state(state)
            raise WorkerError("COMPLETION_IDENTITY_CONFLICT", False)
        if not status.get("lease_valid"):
            # Never resurrect an expired/stolen attempt or overwrite another attempt.
            # Retain the checksum/ref for operator reconciliation, stop claiming.
            state["phase"] = "RECONCILIATION_REQUIRED"
            self._save_state(state)
            raise WorkerError("LEASE_EXPIRED_OUTPUT_PRESERVED", False)
        if not state["upload_complete"]:
            output = self._state_path(job).parent / "output" / "final.mp4"
            if output.is_symlink() or not output.is_file() or file_sha256(output) != completion["checksum_sha256"]:
                raise WorkerError("OUTPUT_INVALID", False)
            self.client.report_progress(job, "UPLOADING")
            auth = self.client.request_output_upload(job, completion["checksum_sha256"], completion["file_size_bytes"])
            if completion.get("storage_ref") and completion["storage_ref"] != auth["storage_ref"]:
                raise WorkerError("COMPLETION_IDENTITY_CONFLICT", False)
            completion["storage_ref"] = auth["storage_ref"]
            state["phase"] = "UPLOAD_PENDING"
            self._save_state(state)
            self.client.upload(auth, output)
            state["upload_complete"] = True
        state["phase"] = "COMPLETION_PENDING"
        self._save_state(state)
        try:
            result = self.client.complete_job(job, completion)
            if result.get("status") != "COMPLETED":
                raise ControlPlaneError("TRANSIENT_NETWORK")
        except Exception:
            state["phase"] = "COMPLETION_UNKNOWN"
            self._save_state(state)
            raise
        state["phase"] = "COMPLETED"
        self._save_state(state)
        return result

    def startup(self) -> None:
        if self._started:
            return
        self._acquire_instance()
        version = ""
        try:
            for binary in (self.renderer.ffmpeg_bin, self.renderer.ffprobe_bin):
                result = subprocess.run([binary, "-version"], capture_output=True, text=True, check=True, timeout=10)
                if binary == self.renderer.ffmpeg_bin:
                    version = result.stdout.splitlines()[0][:200]
            self.config.work_dir.mkdir(parents=True, exist_ok=True)
            sentinel = self.config.work_dir / (".write-check-" + uuid.uuid4().hex)
            with sentinel.open("xb"):
                pass
            sentinel.unlink()
        except Exception:
            raise WorkerError("FFMPEG_UNAVAILABLE", False) from None
        if not self._registered:
            registration = self.client.register(ffmpeg_version=version)
            revision = registration.get("backend_commit") or ""
            logger.info("Backend commit=%s", revision if re.fullmatch(r"[0-9a-fA-F]{40}", revision) else "unavailable")
            lease = registration.get("lease_seconds", 180)
            if self.config.heartbeat_seconds * 3 >= lease:
                raise WorkerError("UNSAFE_HEARTBEAT_CADENCE", False)
            self._registered = True
        self.client.heartbeat()
        self._heartbeat = threading.Thread(target=self._heartbeat_loop, name="render-worker-heartbeat", daemon=True)
        self._heartbeat.start()
        self._started = True

    def _heartbeat_loop(self) -> None:
        last_sent = time.monotonic()
        while not self.heartbeat_stopping.is_set():
            with self._lock:
                job = dict(self._active) if self._active else None
            interval = self.config.heartbeat_seconds if job else self.config.idle_heartbeat_seconds
            # Re-evaluate active/idle cadence without a second heartbeat path.
            due_in = max(0.01, interval - (time.monotonic() - last_sent))
            if self.heartbeat_stopping.wait(min(self.config.heartbeat_seconds, due_in)):
                break
            with self._lock:
                job = dict(self._active) if self._active else None
            interval = self.config.heartbeat_seconds if job else self.config.idle_heartbeat_seconds
            if time.monotonic() - last_sent < interval or self.client.policy.remaining():
                continue
            last_sent = time.monotonic()
            try:
                self.client.heartbeat(job)
            except ControlPlaneError as error:
                if job and error.category == "JOB_REJECTED":
                    self.lease_lost.set()
                if error.category == "AUTH_FAILURE":
                    self.heartbeat_stopping.set()
            except WorkerError as error:
                if job and not error.retryable:
                    self.lease_lost.set()
                logger.warning("Worker heartbeat failed: %s", error.code)

    def _kill_render(self) -> None:
        process = self._render_process
        if process is None or not process.is_alive():
            return
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=10)
        else:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        process.terminate()
        process.join(timeout=5)
        if process.is_alive():
            process.kill()

    def _render(self, spec: CanonicalRenderSpec) -> None:
        context = multiprocessing.get_context("spawn")
        results = context.Queue()
        process = context.Process(target=_render_child, args=(spec, self.renderer.ffmpeg_bin, self.renderer.ffprobe_bin, results))
        self._render_process = process
        process.start()
        deadline = time.monotonic() + self.config.render_timeout_seconds
        try:
            while process.is_alive():
                process.join(timeout=0.2)
                if self.stopping.is_set():
                    self._kill_render()
                    raise ControlPlaneError("TRANSIENT_NETWORK")
                if time.monotonic() > deadline:
                    self._kill_render()
                    raise WorkerError("RENDER_FAILED")
            try:
                success = results.get(timeout=2)
            except queue.Empty:
                success = False
            if process.exitcode != 0 or not success:
                raise WorkerError("RENDER_FAILED")
        finally:
            results.close()
            self._render_process = None

    def _process(self, job: dict) -> dict:
        from production.remote_manifest import PortableRenderManifest

        self.client.report_progress(job, "DOWNLOADING")
        payload = self.client.get_manifest(job)
        try:
            manifest = PortableRenderManifest.model_validate(payload)
            if str(manifest.job_id) != job["job_id"] or manifest.run_id != job["run_id"]:
                raise ValueError("Manifest does not match claim")
        except Exception:
            raise WorkerError("ASSET_DOWNLOAD_FAILED", False) from None
        job_dir = self.config.work_dir / "jobs" / _job_id(job["job_id"])
        if job_dir.is_symlink():
            raise WorkerError("WORKER_INTERNAL_ERROR", False)
        spec = materialize_render_spec(manifest, self.cache, job_dir, self.stopping)
        if self.stopping.is_set() or self.lease_lost.is_set():
            raise WorkerError("WORKER_INTERNAL_ERROR")
        self.client.report_progress(job, "RENDERING")
        started = time.monotonic()
        self._render(spec)
        probe = self.renderer.probe(spec.output_path)
        if not spec.output_path.is_file() or not probe.has_video or not probe.has_audio or any(
            not math.isfinite(value) or value <= 0 for value in (
                probe.duration_seconds, probe.width, probe.height, probe.fps, probe.file_size_bytes
            )
        ):
            raise WorkerError("OUTPUT_INVALID", False)
        checksum = file_sha256(spec.output_path)
        size = spec.output_path.stat().st_size
        completion = {
            "checksum_sha256": checksum,
            "file_size_bytes": size, "duration_seconds": probe.duration_seconds,
            "width": probe.width, "height": probe.height, "fps": probe.fps,
            "video_codec": probe.video_codec, "audio_codec": probe.audio_codec,
            "telemetry": {"renderer_version": WORKER_VERSION, "render_seconds": round(time.monotonic() - started, 3)},
        }
        state = {"job": job, "worker_id": self.config.worker_id, "api_base_url": self.config.api_base_url,
                 "phase": "RENDER_OUTPUT_READY", "upload_complete": False, "completion": completion}
        self._save_state(state)
        return self._resume_output(state)

    def run_once(self) -> bool:
        self.startup()
        if self.stopping.is_set():
            return False
        states = self._pending_states()
        if states:
            state = states[0]
            if state["phase"] == "RECONCILIATION_REQUIRED":
                raise WorkerError("LOCAL_STATE_REQUIRES_REVIEW", False)
            with self._lock:
                self._active = state["job"]
            self._resume_output(state)
            with self._lock:
                self._active = None
            return True
        job = self._active or self.client.claim_job()
        if not job:
            return False
        job["job_id"] = _job_id(job["job_id"])
        if not isinstance(job.get("attempt"), int) or job["attempt"] < 1:
            raise WorkerError("WORKER_INTERNAL_ERROR", False)
        self.lease_lost.clear()
        with self._lock:
            self._active = job
        try:
            self._process(job)
            logger.info("Render job %s completed", job["job_id"])
        except ControlPlaneError:
            # Transport delivery is not a render failure. Retain active work;
            # durable output, if present, takes precedence on the next iteration.
            raise
        except Exception as error:
            safe = error if isinstance(error, WorkerError) else WorkerError("WORKER_INTERNAL_ERROR")
            # Never release output-ready/uploaded jobs, including unknown local
            # exceptions after delivery. Only actual media failures use /fail.
            if self._state_path(job).exists():
                raise safe
            if safe.code not in {"ASSET_CHECKSUM_MISMATCH", "RENDER_FAILED", "OUTPUT_INVALID", "FFMPEG_UNAVAILABLE"}:
                raise safe
            self.client.fail_job(job, safe.code, safe.retryable)
            logger.warning("Render job %s failed: %s", job["job_id"], safe.code)
        else:
            with self._lock:
                self._active = None
        with self._lock:
            self._active = None
        return True

    def run_forever(self) -> None:
        try:
            while not self.stopping.is_set():
                try:
                    has_work = self.run_once()
                except ControlPlaneError as error:
                    if not error.retryable:
                        logger.error("Worker paused: %s; operator action required", error.category)
                        raise
                    has_work = False
                except WorkerError as error:
                    logger.warning("Worker polling failed: %s", error.code)
                    if not error.retryable or error.code == "WORKER_INTERNAL_ERROR":
                        raise
                    has_work = False
                self.stopping.wait(max(self.config.poll_seconds, self.client.policy.remaining()))
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        self.stopping.set()
        self._kill_render()
        self.heartbeat_stopping.set()
        if self._heartbeat and self._heartbeat is not threading.current_thread():
            self._heartbeat.join(timeout=self.config.completion_timeout_seconds + self.config.connect_timeout_seconds + 1)
        if self._instance_file is not None:
            self._instance_file.close()
            self._instance_file = None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify binaries/configuration and register, then exit without claiming")
    parser.add_argument("--soak-seconds", type=float, default=0, help="Bounded real worker run; may process queued production jobs")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    worker = None
    try:
        worker = RemoteRenderWorker(WorkerConfig.from_env())
        logger.info("[*] Ket noi Production Backend qua HTTPS")
        logger.info("[*] Render Queue: Remote Worker (no DATABASE_URL required)")
        if args.soak_seconds:
            if not math.isfinite(args.soak_seconds) or args.soak_seconds <= 0:
                raise ValueError("Invalid soak duration")
            timer = threading.Timer(args.soak_seconds, worker.stopping.set)
            timer.daemon = True
            timer.start()
        for event in (signal.SIGINT, signal.SIGTERM):
            signal.signal(event, lambda *_: worker.stopping.set())
        if args.check:
            worker.startup()
            logger.info("Worker configuration, FFmpeg, FFprobe and API registration verified")
        else:
            worker.run_forever()
        return 0
    except (ValueError, WorkerError, ControlPlaneError) as err:
        logger.error("Worker startup failed: %s", getattr(err, "code", type(err).__name__))
        return 1
    finally:
        if worker:
            worker.shutdown()
            logger.info("Worker health=%s metrics=%s", worker.client.policy.health, worker.client.metrics)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
