"""
Source Ingestion Service for VisionFlow Scene Library (Phase 2 - Section 5, 6, 7)
Implements:
- Strict SSRF protection (loopback, RFC 1918, link-local metadata 169.254.169.254, redirect destination revalidation).
- Safe argument-array ffprobe metadata extraction (width, height, fps, duration, codec).
- Versioned source and scene fingerprinting for robust deduplication.
- Pluggable provider architecture (UploadedFileProvider, GenericHTTPProvider).
- Persistence to SourceRepository.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import uuid

from production.contracts import (
    RightsState,
    SourceAssetRecord,
    SourceIngestState,
    SourceInput,
    WatermarkState,
)
from production.repositories.source_repository import get_source_repository

MEDIA_CACHE_DIR = Path(__file__).resolve().parent.parent / ".media_cache"
MEDIA_CACHE_DIR.mkdir(exist_ok=True, parents=True)

MAX_DOWNLOAD_BYTES = 500 * 1024 * 1024  # 500 MB max
DOWNLOAD_TIMEOUT_SECONDS = 30
MAX_REDIRECTS = 3


class SecurityValidationError(ValueError):
    """Raised when an ingest source violates security boundaries."""


# ---------------------------------------------------------------------------
# Security Validations (Section 6)
# ---------------------------------------------------------------------------

def is_ip_private_or_restricted(ip_str: str) -> bool:
    """Checks if IP is private, loopback, link-local, or multicast."""
    try:
        ip = ipaddress.ip_address(ip_str)
        return (
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or str(ip) in ("169.254.169.254", "0.0.0.0", "::", "::1")
        )
    except ValueError:
        return True


def validate_remote_url_safety(url: str) -> str:
    """
    Validates URL safety against SSRF attacks:
    - Rejects non-http(s) schemes (e.g. file://, gopher://, ftp://).
    - Resolves host DNS and verifies none of the IPs are private/loopback/cloud metadata.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme.lower() not in ("http", "https"):
        raise SecurityValidationError(f"Forbidden URL scheme '{parsed.scheme}'. Only http and https are permitted.")

    hostname = parsed.hostname
    if not hostname:
        raise SecurityValidationError("Invalid URL: missing hostname.")

    # Reject localhost directly
    if hostname.lower() in ("localhost", "127.0.0.1", "::1"):
        raise SecurityValidationError("Target host 'localhost' / loopback is rejected for security.")

    # Resolve all IPs for hostname
    port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    try:
        addr_info = socket.getaddrinfo(hostname, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise SecurityValidationError(f"Failed to resolve hostname '{hostname}': {e}")

    for item in addr_info:
        sockaddr = item[4]
        ip_addr = sockaddr[0]
        if is_ip_private_or_restricted(ip_addr):
            raise SecurityValidationError(
                f"Resolved target IP '{ip_addr}' for '{hostname}' is private, loopback, or cloud-internal."
            )

    return url


def sanitize_safe_filename(raw_name: str, default_ext: str = ".mp4") -> str:
    """Strips directory paths and dangerous characters to prevent path traversal."""
    base = os.path.basename(raw_name)
    cleaned = re.sub(r"[^a-zA-Z0-9_.-]", "_", base)
    if not cleaned or cleaned.startswith("."):
        cleaned = f"media_{uuid.uuid4().hex[:8]}{default_ext}"
    return cleaned


# ---------------------------------------------------------------------------
# FFprobe Metadata Extraction
# ---------------------------------------------------------------------------

def get_ffprobe_binary() -> str:
    # First check system PATH
    sys_probe = shutil.which("ffprobe")
    if sys_probe and os.path.exists(sys_probe):
        return sys_probe
    try:
        import imageio_ffmpeg
        ffmpeg_dir = os.path.dirname(imageio_ffmpeg.get_ffmpeg_exe())
        ffprobe_cand = os.path.join(ffmpeg_dir, "ffprobe.exe")
        if os.path.exists(ffprobe_cand):
            return ffprobe_cand
    except Exception:
        pass
    return "ffprobe"


def probe_media(file_path: Path) -> Dict[str, Any]:
    """
    Executes ffprobe via argument-array subprocess without shell interpolation.
    Extracts duration, width, height, fps, and video codec.
    """
    if not file_path.exists():
        raise FileNotFoundError(f"Media file not found: {file_path}")

    probe_bin = get_ffprobe_binary()
    cmd = [
        probe_bin,
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(file_path),
    ]

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=15)
        info = json.loads(res.stdout)
    except subprocess.CalledProcessError as e:
        raise ValueError(f"ffprobe failed on {file_path}: {e.stderr}")
    except Exception as e:
        raise ValueError(f"ffprobe execution error: {e}")

    streams = info.get("streams", [])
    format_info = info.get("format", {})

    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    width = int(video_stream.get("width", 0)) if video_stream else 0
    height = int(video_stream.get("height", 0)) if video_stream else 0
    codec = video_stream.get("codec_name", "unknown") if video_stream else "unknown"

    # FPS calculation
    fps = 0.0
    if video_stream:
        r_frame_rate = video_stream.get("r_frame_rate", "0/0")
        try:
            num, den = map(int, r_frame_rate.split("/"))
            fps = round(num / den, 2) if den != 0 else 0.0
        except Exception:
            fps = 25.0

    duration = float(format_info.get("duration", 0.0))
    if duration <= 0.0 and video_stream:
        duration = float(video_stream.get("duration", 0.0))

    has_audio = audio_stream is not None

    return {
        "width": width,
        "height": height,
        "fps": fps,
        "codec": codec,
        "duration": duration,
        "has_audio": has_audio,
        "bitrate": int(format_info.get("bit_rate", 0)),
        "size_bytes": file_path.stat().st_size,
    }


# ---------------------------------------------------------------------------
# Fingerprint Strategy (Phase 2.5 - Section 12 & 13)
# ---------------------------------------------------------------------------

def compute_fast_fingerprint(file_path: Path, metadata: Dict[str, Any]) -> str:
    """
    Tier 1 Fast Fingerprint:
    Combines sample chunk hashes (head, mid, tail 512KB) + file size + duration and resolution.
    Used for rapid candidate duplicate lookup without scanning gigabytes.
    Format: 'fast:<32-hex>'
    """
    file_size = file_path.stat().st_size
    h = hashlib.sha256()
    h.update(str(file_size).encode("utf-8"))

    with open(file_path, "rb") as f:
        # Head 512KB
        h.update(f.read(512 * 1024))
        # Middle 512KB
        if file_size > 1024 * 1024:
            f.seek(file_size // 2)
            h.update(f.read(512 * 1024))
        # Tail 512KB
        if file_size > 1536 * 1024:
            f.seek(max(0, file_size - 512 * 1024))
            h.update(f.read(512 * 1024))

    stream_sig = f"{metadata.get('duration', 0):.2f}:{metadata.get('width', 0)}x{metadata.get('height', 0)}"
    h.update(stream_sig.encode("utf-8"))
    return f"fast:{h.hexdigest()[:32]}"


def compute_canonical_fingerprint(file_path: Path) -> str:
    """
    Tier 2 Canonical Fingerprint:
    Cryptographic full SHA-256 over entire file content.
    Format: 'v1:<64-hex-sha256>'
    Guarantees 100% exact deduplication without chunk collision risk.
    """
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    digest = h.hexdigest()
    assert len(digest) == 64, f"Invalid SHA-256 digest length: {len(digest)}"
    return f"v1:{digest}"


def compute_source_fingerprint(file_path: Path, metadata: Dict[str, Any]) -> str:
    """
    Canonical source fingerprint entrypoint.
    Returns full 64-hex SHA-256 canonical identity.
    """
    return compute_canonical_fingerprint(file_path)


def compute_scene_fingerprint(source_fingerprint: str, start_sec: float, end_sec: float) -> str:
    """Computes stable scene fingerprint based on source identity and cut timestamps."""
    # Use short hash of source_fingerprint in scene id for brevity
    src_clean = source_fingerprint.split(":")[-1][:12]
    return f"scn_{src_clean}_{start_sec:.2f}_{end_sec:.2f}"


# ---------------------------------------------------------------------------
# Providers Architecture (Section 5)
# ---------------------------------------------------------------------------

class SourceProvider(ABC):
    @abstractmethod
    def can_handle(self, source_input: SourceInput) -> bool:
        pass

    @abstractmethod
    def resolve_to_local_file(self, source_input: SourceInput) -> Path:
        pass


class UploadedFileProvider(SourceProvider):
    def can_handle(self, source_input: SourceInput) -> bool:
        if source_input.file_ref:
            return True
        if source_input.uri and (source_input.uri.startswith("/") or re.match(r"^[a-zA-Z]:\\", source_input.uri)):
            return True
        return False

    def resolve_to_local_file(self, source_input: SourceInput) -> Path:
        target_path = Path(source_input.file_ref or source_input.uri)
        if not target_path.exists():
            raise FileNotFoundError(f"Local file does not exist: {target_path}")
        return target_path


class GenericHTTPProvider(SourceProvider):
    def can_handle(self, source_input: SourceInput) -> bool:
        if not source_input.uri:
            return False
        return source_input.uri.startswith(("http://", "https://"))

    def resolve_to_local_file(self, source_input: SourceInput) -> Path:
        raw_url = source_input.uri
        validated_url = validate_remote_url_safety(raw_url)

        # Download with redirect protection and size bounds
        curr_url = validated_url
        downloaded_bytes = 0
        dest_filename = sanitize_safe_filename(curr_url.split("?")[0])
        dest_path = MEDIA_CACHE_DIR / f"dl_{uuid.uuid4().hex[:8]}_{dest_filename}"

        redirect_count = 0
        req = urllib.request.Request(
            curr_url,
            headers={"User-Agent": "VisionFlow-Ingest/1.0", "Accept": "video/*,application/octet-stream"},
        )

        with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
            # Check redirect URL safety if redirected
            final_url = response.geturl()
            if final_url != curr_url:
                validate_remote_url_safety(final_url)

            # Check content length header if provided
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_DOWNLOAD_BYTES:
                raise SecurityValidationError(
                    f"Remote content size {content_length} bytes exceeds maximum allowed {MAX_DOWNLOAD_BYTES} bytes."
                )

            with open(dest_path, "wb") as out_fp:
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    downloaded_bytes += len(chunk)
                    if downloaded_bytes > MAX_DOWNLOAD_BYTES:
                        out_fp.close()
                        dest_path.unlink(missing_ok=True)
                        raise SecurityValidationError("Download exceeded maximum allowed size of 500MB.")
                    out_fp.write(chunk)

        return dest_path


# ---------------------------------------------------------------------------
# Source Ingest Service (Section 5)
# ---------------------------------------------------------------------------

class SourceIngestService:
    def __init__(self):
        self.providers: List[SourceProvider] = [
            UploadedFileProvider(),
            GenericHTTPProvider(),
        ]
        self.repository = get_source_repository()

    def ingest_source(self, source_input: SourceInput) -> SourceAssetRecord:
        """
        Executes complete ingestion pipeline:
        1. Identifies capable provider.
        2. Resolves media to local verified file.
        3. Probes media via ffprobe.
        4. Computes source fingerprint & checks deduplication.
        5. Persists SourceAssetRecord and returns it.
        """
        provider = next((p for p in self.providers if p.can_handle(source_input)), None)
        if not provider:
            raise ValueError(f"No suitable provider found for source input: {source_input}")

        # Ingest state update
        source_input.ingest_state = SourceIngestState.INGESTING

        local_file = provider.resolve_to_local_file(source_input)
        metadata = probe_media(local_file)

        fast_fp = compute_fast_fingerprint(local_file, metadata)
        canonical_fp = compute_canonical_fingerprint(local_file)

        # Deduplication check: Tier 1 fast lookup + Tier 2 full canonical verification
        existing = self.repository.get_by_fingerprint(canonical_fp)
        if not existing and hasattr(self.repository, "get_by_fast_fingerprint"):
            candidate = self.repository.get_by_fast_fingerprint(fast_fp)
            if candidate and candidate.fingerprint == canonical_fp:
                existing = candidate

        if existing:
            source_input.ingest_state = SourceIngestState.READY
            return existing

        source_id = f"src_{uuid.uuid4().hex[:12]}"
        record = SourceAssetRecord(
            id=source_id,
            source_type="video",
            original_uri=source_input.uri or str(local_file),
            storage_ref=str(local_file),
            fingerprint=canonical_fp,
            fast_fingerprint=fast_fp,
            duration=metadata["duration"],
            width=metadata["width"],
            height=metadata["height"],
            fps=metadata["fps"],
            codec=metadata["codec"],
            language=None,
            transcript_state="PENDING",
            rights_state=source_input.rights_state,
            watermark_state=WatermarkState.NONE,
            ingest_status=SourceIngestState.READY,
            analysis_version="v1",
            metadata_json={**metadata, "provenance": source_input.provenance},
        )

        saved = self.repository.save(record)
        source_input.ingest_state = SourceIngestState.READY
        return saved


source_ingest_service = SourceIngestService()
