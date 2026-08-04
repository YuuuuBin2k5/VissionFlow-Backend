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
        values = {name: os.getenv(name, "").strip() for name in (
            "VISIONFLOW_OBJECT_STORE_ENDPOINT", "VISIONFLOW_OBJECT_STORE_BUCKET",
            "VISIONFLOW_OBJECT_STORE_ACCESS_KEY_ID", "VISIONFLOW_OBJECT_STORE_SECRET_ACCESS_KEY",
        )}
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise OverlayUploadConfigurationError(f"Missing object storage setting: {', '.join(missing)}")
        endpoint = values["VISIONFLOW_OBJECT_STORE_ENDPOINT"]
        if not endpoint.startswith("https://"):
            raise OverlayUploadConfigurationError("VISIONFLOW_OBJECT_STORE_ENDPOINT must use HTTPS")
        from botocore.config import Config
        client = boto3.client(
            "s3", endpoint_url=endpoint, region_name=os.getenv("VISIONFLOW_OBJECT_STORE_REGION", "auto"),
            aws_access_key_id=values["VISIONFLOW_OBJECT_STORE_ACCESS_KEY_ID"],
            aws_secret_access_key=values["VISIONFLOW_OBJECT_STORE_SECRET_ACCESS_KEY"],
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )
        return cls(client, values["VISIONFLOW_OBJECT_STORE_BUCKET"])

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

    def issue_final_export(self, *, workflow_run_id: uuid.UUID, object_key: str) -> PrivateObjectPreviewTicket:
        target_key = object_key if (object_key and object_key.startswith("visionflow/")) else f"visionflow/{workflow_run_id}/exports/final.mp4"
        if object_key and (object_key.startswith("http://") or object_key.startswith("https://")):
            return PrivateObjectPreviewTicket(object_key, object_key, self._expires_in_seconds)
        expected_prefix = f"visionflow/{workflow_run_id}/"
        if not target_key.startswith(expected_prefix) or ".." in target_key.split("/"):
            raise OverlayUploadVerificationError("Preview object does not belong to this workflow")
        try:
            self._client.head_object(Bucket=self._bucket, Key=target_key)
        except Exception as exc:
            import logging
            logging.getLogger("app.infrastructure.overlay_uploads").warning(
                "head_object verification failed for %s: %s; proceeding with presigned URL generation", target_key, exc
            )
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
