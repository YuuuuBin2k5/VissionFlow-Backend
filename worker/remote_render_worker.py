"""Outbound-only render worker. Start with ``python -m worker.remote_render_worker``.

Coordination uses the worker API; media travels through scoped object-store URLs.
This module deliberately has no database or control-plane dependency.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
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
    poll_seconds: float = 5.0
    max_render_jobs: int = 1
    heartbeat_seconds: float = 10.0
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
        if not self.worker_token or any(c.isspace() for c in self.worker_token) or len(self.worker_token) > 4096:
            raise ValueError("VISIONFLOW_WORKER_TOKEN is required and must not contain whitespace")
        if self.max_render_jobs != 1:
            raise ValueError("VISIONFLOW_MAX_RENDER_JOBS currently supports exactly 1")
        for value in (self.poll_seconds, self.heartbeat_seconds, self.http_timeout_seconds, self.render_timeout_seconds):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("Worker timeouts and intervals must be positive and finite")
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
            poll_seconds=float(os.environ.get("VISIONFLOW_WORKER_POLL_SECONDS", "5")),
            max_render_jobs=int(os.environ.get("VISIONFLOW_MAX_RENDER_JOBS", "1")),
            allow_loopback_http=os.environ.get("VISIONFLOW_WORKER_ALLOW_LOOPBACK_HTTP") == "1",
        )


class WorkerHttpClient:
    def __init__(self, config: WorkerConfig, session: Any = None, artifact_session: Any = None):
        self.config = config
        self.session = session or requests.Session()
        self.artifact_session = artifact_session or requests.Session()
        # Do not inherit ~/.netrc authentication or ambient proxy credentials.
        for transport in (self.session, self.artifact_session):
            if isinstance(transport, requests.Session):
                transport.trust_env = False

    def _request(self, method: str, path: str, payload: dict | None = None) -> Any:
        headers = {"Authorization": f"Bearer {self.config.worker_token}", "X-VisionFlow-Worker-ID": self.config.worker_id}
        try:
            response = self.session.request(
                method, self.config.api_base_url + "/render-workers" + path,
                headers=headers, json=payload,
                timeout=max(180.0, self.config.http_timeout_seconds) if path.endswith("/complete") else self.config.http_timeout_seconds,
                allow_redirects=False,
            )
            if response.status_code == 204:
                return None
            if not 200 <= response.status_code < 300:
                # Redirections must never forward the worker credential.
                raise WorkerError("WORKER_API_REJECTED", retryable=response.status_code >= 500 or response.status_code == 429)
            return response.json()
        except WorkerError:
            raise
        except Exception:
            raise WorkerError("WORKER_API_UNAVAILABLE") from None

    def register(self, *, ffmpeg_version: str, renderer_version: str = WORKER_VERSION) -> dict:
        return self._request("POST", "/register", {
            "platform": platform.system(), "renderer_version": renderer_version,
            "ffmpeg_version": ffmpeg_version[:200], "capabilities": ["canonical-v1", "ffmpeg", "h264", "aac"],
            "max_concurrent_jobs": self.config.max_render_jobs,
        })

    def heartbeat(self, job: dict | None = None) -> dict:
        return self._request("POST", "/heartbeat", {} if job is None else {"job_id": job["job_id"], "attempt": job["attempt"]})

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

    def startup(self) -> None:
        if self._started:
            return
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
        self.client.register(ffmpeg_version=version)
        self.client.heartbeat()
        self._heartbeat = threading.Thread(target=self._heartbeat_loop, name="render-worker-heartbeat", daemon=True)
        self._heartbeat.start()
        self._started = True

    def _heartbeat_loop(self) -> None:
        while not self.heartbeat_stopping.wait(self.config.heartbeat_seconds):
            with self._lock:
                job = dict(self._active) if self._active else None
            try:
                self.client.heartbeat(job)
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
                if self.stopping.is_set() or self.lease_lost.is_set() or time.monotonic() > deadline:
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
        self.client.report_progress(job, "UPLOADING")
        authorization = self.client.request_output_upload(job, checksum, size)
        self.client.upload(authorization, spec.output_path)
        completion = {
            "storage_ref": authorization["storage_ref"], "checksum_sha256": checksum,
            "file_size_bytes": size, "duration_seconds": probe.duration_seconds,
            "width": probe.width, "height": probe.height, "fps": probe.fps,
            "video_codec": probe.video_codec, "audio_codec": probe.audio_codec,
            "telemetry": {"renderer_version": WORKER_VERSION, "render_seconds": round(time.monotonic() - started, 3)},
        }
        # Retry the identical completion payload after an ambiguous network result.
        # The backend owns completion/QC idempotency.
        for attempt in range(3):
            try:
                return self.client.complete_job(job, completion)
            except WorkerError as error:
                if not error.retryable or attempt == 2:
                    raise
                if self.stopping.wait(min(self.config.poll_seconds, 2)):
                    raise WorkerError("WORKER_INTERNAL_ERROR") from None
        raise WorkerError("WORKER_INTERNAL_ERROR")

    def run_once(self) -> bool:
        self.startup()
        if self.stopping.is_set():
            return False
        job = self.client.claim_job()
        if not job:
            return False
        job["job_id"] = _job_id(job["job_id"])
        if not isinstance(job.get("attempt"), int) or job["attempt"] < 1:
            raise WorkerError("WORKER_INTERNAL_ERROR", False)
        self.lease_lost.clear()
        with self._lock:
            self._active = job
        try:
            self.client.heartbeat(job)
            self._process(job)
            logger.info("Render job %s completed", job["job_id"])
        except Exception as error:
            safe = error if isinstance(error, WorkerError) else WorkerError("WORKER_INTERNAL_ERROR")
            report_code = safe.code if safe.code in {
                "ASSET_DOWNLOAD_FAILED", "ASSET_CHECKSUM_MISMATCH", "FFMPEG_UNAVAILABLE", "RENDER_FAILED",
                "OUTPUT_INVALID", "UPLOAD_FAILED", "WORKER_INTERNAL_ERROR",
            } else "WORKER_INTERNAL_ERROR"
            try:
                self.client.fail_job(job, report_code, safe.retryable)
            except WorkerError:
                # Durable lease recovery handles a disconnected/dead worker.
                logger.warning("Could not release render lease for %s", job["job_id"])
            logger.warning("Render job %s failed: %s", job["job_id"], report_code)
        finally:
            with self._lock:
                self._active = None
        return True

    def run_forever(self) -> None:
        self.startup()
        try:
            while not self.stopping.is_set():
                try:
                    has_work = self.run_once()
                except WorkerError as error:
                    logger.warning("Worker polling failed: %s", error.code)
                    has_work = False
                if not has_work:
                    self.stopping.wait(self.config.poll_seconds)
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        self.stopping.set()
        self._kill_render()
        self.heartbeat_stopping.set()
        if self._heartbeat and self._heartbeat is not threading.current_thread():
            self._heartbeat.join(timeout=self.config.http_timeout_seconds + 1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify binaries/configuration and register, then exit without claiming")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    worker = None
    try:
        worker = RemoteRenderWorker(WorkerConfig.from_env())
        for event in (signal.SIGINT, signal.SIGTERM):
            signal.signal(event, lambda *_: worker.stopping.set())
        if args.check:
            worker.startup()
            logger.info("Worker configuration, FFmpeg, FFprobe and API registration verified")
        else:
            worker.run_forever()
        return 0
    except (ValueError, WorkerError):
        logger.error("Worker startup failed; check required configuration, binaries and worker API credentials")
        return 1
    finally:
        if worker:
            worker.shutdown()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
