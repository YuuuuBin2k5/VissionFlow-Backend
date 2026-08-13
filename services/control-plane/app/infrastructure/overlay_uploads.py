"""Tenant-scoped S3/R2 presigned upload issuer for Composition Studio."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path

import boto3


class OverlayUploadConfigurationError(ValueError):
    pass


class OverlayUploadVerificationError(ValueError):
    pass


@dataclass(frozen=True)
class OverlayUploadTicket:
    object_key: str
    upload_url: str
    required_headers: dict[str, str]
    expires_in_seconds: int


@dataclass(frozen=True)
class PrivateObjectPreviewTicket:
    object_key: str
    download_url: str
    expires_in_seconds: int


class OverlayUploadIssuer:
    _CONTENT_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})
    _SUFFIXES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}

    def __init__(self, client, bucket: str, expires_in_seconds: int = 300) -> None:
        self._client, self._bucket = client, bucket
        self._expires_in_seconds = expires_in_seconds

    @classmethod
    def from_env(cls) -> "OverlayUploadIssuer":
        endpoint = os.getenv("VISIONFLOW_OBJECT_STORE_ENDPOINT", "https://ec302240fdb8cad9ae6c9b685f14eeec.r2.cloudflarestorage.com").strip()
        bucket = os.getenv("VISIONFLOW_OBJECT_STORE_BUCKET", "vision-flow").strip()
        access_key = os.getenv("VISIONFLOW_OBJECT_STORE_ACCESS_KEY_ID", "fd28f47a855e5f2097d5f8c24c50da70").strip()
        secret_key = os.getenv("VISIONFLOW_OBJECT_STORE_SECRET_ACCESS_KEY", "c329293210d831c0bdba01f2434d86dab3eb23ab0a73f9b67819b7c3069cc9c6").strip()
        region = os.getenv("VISIONFLOW_OBJECT_STORE_REGION", "auto").strip()

        if not endpoint.startswith("https://"):
            endpoint = f"https://{endpoint}"
        from urllib.parse import urlparse
        parsed_ep = urlparse(endpoint)
        endpoint = f"{parsed_ep.scheme}://{parsed_ep.netloc}"
        from botocore.config import Config
        client = boto3.client(
            "s3", endpoint_url=endpoint, region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )
        return cls(client, bucket)

    def issue(self, *, workflow_run_id: uuid.UUID, filename: str, content_type: str, byte_size: int) -> OverlayUploadTicket:
        if content_type not in self._CONTENT_TYPES:
            raise ValueError("Only PNG, JPEG, and WebP overlays are supported")
        if not 1 <= byte_size <= 15 * 1024 * 1024:
            raise ValueError("Overlay file size must be between 1 byte and 15 MiB")
        if Path(filename).suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise ValueError("Overlay filename must have a supported image extension")
        key = f"visionflow/{workflow_run_id}/uploads/{uuid.uuid4().hex}{self._SUFFIXES[content_type]}"
        url = self._client.generate_presigned_url(
            "put_object",
            Params={"Bucket": self._bucket, "Key": key, "ContentType": content_type},
            ExpiresIn=self._expires_in_seconds,
            HttpMethod="PUT",
        )
        return OverlayUploadTicket(key, url, {"Content-Type": content_type}, self._expires_in_seconds)


class OverlayAssetVerifier:
    """Verifies object-store facts before an overlay becomes immutable render input."""

    def __init__(self, client, bucket: str) -> None:
        self._client, self._bucket = client, bucket

    @classmethod
    def from_env(cls) -> "OverlayAssetVerifier":
        issuer = OverlayUploadIssuer.from_env()
        return cls(issuer._client, issuer._bucket)

    def verify(self, *, workflow_run_id: uuid.UUID, object_keys: tuple[str, ...]) -> None:
        for key in object_keys:
            self._validate_key(workflow_run_id, key)
            try:
                metadata = self._client.head_object(Bucket=self._bucket, Key=key)
            except Exception as exc:
                raise OverlayUploadVerificationError("Uploaded overlay could not be verified") from exc
            content_type = str(metadata.get("ContentType", "")).lower()
            size = metadata.get("ContentLength")
            if content_type not in OverlayUploadIssuer._CONTENT_TYPES or not isinstance(size, int) or not 1 <= size <= 15 * 1024 * 1024:
                raise OverlayUploadVerificationError("Uploaded overlay has an unsupported type or size")

    @staticmethod
    def _validate_key(workflow_run_id: uuid.UUID, key: str) -> None:
        normalized = key.replace("\\", "/")
        if not normalized.startswith(f"visionflow/{workflow_run_id}/uploads/") or ".." in normalized.split("/"):
            raise OverlayUploadVerificationError("Overlay object does not belong to this workflow")


class PrivateObjectPreviewIssuer:
    """Issue short-lived reads for an already-authorized workflow artifact."""

    def __init__(self, client, bucket: str, expires_in_seconds: int = 300) -> None:
        self._client, self._bucket = client, bucket
        self._expires_in_seconds = expires_in_seconds

    @classmethod
    def from_env(cls) -> "PrivateObjectPreviewIssuer":
        issuer = OverlayUploadIssuer.from_env()
        return cls(issuer._client, issuer._bucket)

    @staticmethod
    def _normalize_key(workflow_run_id: uuid.UUID, object_key: str | None) -> str:
        """Extract the clean S3 key from a raw object_key that may be a presigned URL."""
        if not object_key:
            return f"visionflow/{workflow_run_id}/exports/final.mp4"
        clean = object_key.split("?")[0]
        if "visionflow/" in clean:
            return "visionflow/" + clean.split("visionflow/", 1)[1]
        return object_key

    def resolve_r2_key(self, workflow_run_id: uuid.UUID, object_key: str | None) -> str:
        """Probe R2 to find the actual key for this workflow's final export.
        
        Files uploaded before a config fix may live under 'vision-flow/visionflow/<id>/...'
        instead of 'visionflow/<id>/...' because the worker endpoint included the bucket name.
        We check both paths and return the one that exists.
        """
        candidate = self._normalize_key(workflow_run_id, object_key)
        # Try the canonical path first
        try:
            self._client.head_object(Bucket=self._bucket, Key=candidate)
            return candidate
        except Exception:
            pass
        # Fallback: files uploaded by worker before endpoint fix sit under vision-flow/visionflow/...
        legacy_candidate = f"vision-flow/{candidate}"
        try:
            self._client.head_object(Bucket=self._bucket, Key=legacy_candidate)
            import logging
            logging.getLogger("app.infrastructure.overlay_uploads").info(
                "Resolved legacy R2 path: %s", legacy_candidate
            )
            return legacy_candidate
        except Exception:
            pass
        # Return canonical even if not found; downstream will surface a clear error
        return candidate

    def issue_final_export(self, *, workflow_run_id: uuid.UUID, object_key: str) -> PrivateObjectPreviewTicket:
        normalized = self._normalize_key(workflow_run_id, object_key)
        if normalized.startswith("http://") or normalized.startswith("https://"):
            return PrivateObjectPreviewTicket(normalized, normalized, self._expires_in_seconds)
        # Probe both canonical and legacy paths
        target_key = self.resolve_r2_key(workflow_run_id, object_key)
        url = self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": target_key},
            ExpiresIn=self._expires_in_seconds,
            HttpMethod="GET",
        )
        return PrivateObjectPreviewTicket(target_key, url, self._expires_in_seconds)


def composition_overlay_object_keys(composition: dict[str, object]) -> tuple[str, ...]:
    keys: list[str] = []
    tracks = composition.get("tracks", [])
    if not isinstance(tracks, list):
        return ()
    for track in tracks:
        if not isinstance(track, dict) or track.get("track_type") != "overlay" or track.get("muted"):
            continue
        clips = track.get("clips", [])
        if not isinstance(clips, list):
            continue
        for clip in clips:
            if isinstance(clip, dict) and clip.get("source_type") == "asset" and isinstance(clip.get("source_ref"), str):
                keys.append(clip["source_ref"])
    return tuple(sorted(set(keys)))
