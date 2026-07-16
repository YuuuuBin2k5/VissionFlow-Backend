"""Tenant-scoped S3/R2 presigned upload issuer for Composition Studio."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path

import boto3


class OverlayUploadConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class OverlayUploadTicket:
    object_key: str
    upload_url: str
    required_headers: dict[str, str]
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
        client = boto3.client(
            "s3", endpoint_url=endpoint, region_name=os.getenv("VISIONFLOW_OBJECT_STORE_REGION", "auto"),
            aws_access_key_id=values["VISIONFLOW_OBJECT_STORE_ACCESS_KEY_ID"],
            aws_secret_access_key=values["VISIONFLOW_OBJECT_STORE_SECRET_ACCESS_KEY"],
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
