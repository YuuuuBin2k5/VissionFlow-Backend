"""S3-compatible asset storage adapter (Cloudflare R2 or AWS S3)."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

import boto3


@dataclass(frozen=True)
class VisionFlowObjectStorageSettings:
    endpoint: str
    bucket: str
    access_key_id: str
    secret_access_key: str
    region: str

    @classmethod
    def from_env(cls) -> "VisionFlowObjectStorageSettings":
        values = {name: os.getenv(name, "").strip() for name in (
            "VISIONFLOW_OBJECT_STORE_ENDPOINT", "VISIONFLOW_OBJECT_STORE_BUCKET",
            "VISIONFLOW_OBJECT_STORE_ACCESS_KEY_ID", "VISIONFLOW_OBJECT_STORE_SECRET_ACCESS_KEY",
        )}
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise ValueError(f"Missing VisionFlow object storage settings: {', '.join(missing)}")
        if not values["VISIONFLOW_OBJECT_STORE_ENDPOINT"].startswith("https://"):
            raise ValueError("VISIONFLOW_OBJECT_STORE_ENDPOINT must use HTTPS")
        return cls(
            endpoint=values["VISIONFLOW_OBJECT_STORE_ENDPOINT"], bucket=values["VISIONFLOW_OBJECT_STORE_BUCKET"],
            access_key_id=values["VISIONFLOW_OBJECT_STORE_ACCESS_KEY_ID"], secret_access_key=values["VISIONFLOW_OBJECT_STORE_SECRET_ACCESS_KEY"],
            region=os.getenv("VISIONFLOW_OBJECT_STORE_REGION", "auto").strip() or "auto",
        )


class S3CompatibleObjectStorage:
    def __init__(self, settings: VisionFlowObjectStorageSettings) -> None:
        self._settings = settings
        self._client = boto3.client(
            "s3", endpoint_url=settings.endpoint, region_name=settings.region,
            aws_access_key_id=settings.access_key_id, aws_secret_access_key=settings.secret_access_key,
        )

    def upload_asset(self, workflow_run_id: str, scene_id: int, source_path: str) -> dict[str, object]:
        path = Path(source_path)
        if not path.is_file():
            raise FileNotFoundError(f"asset file does not exist: {path}")
        checksum = _sha256(path)
        key = f"visionflow/{workflow_run_id}/assets/scene-{scene_id:02d}{path.suffix.lower() or '.mp4'}"
        self._client.upload_file(
            str(path), self._settings.bucket, key,
            ExtraArgs={"ContentType": "video/mp4", "Metadata": {"sha256": checksum, "workflow-run-id": workflow_run_id}},
        )
        return {"object_key": key, "content_type": "video/mp4", "byte_size": path.stat().st_size, "checksum_sha256": checksum}

    def download_to(self, object_key: str, destination_path: str) -> str:
        destination = Path(destination_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._client.download_file(self._settings.bucket, object_key, str(destination))
        return str(destination)

    def upload_export(self, workflow_run_id: str, source_path: str) -> dict[str, object]:
        path = Path(source_path)
        checksum = _sha256(path)
        key = f"visionflow/{workflow_run_id}/exports/final.mp4"
        self._client.upload_file(str(path), self._settings.bucket, key, ExtraArgs={"ContentType": "video/mp4", "Metadata": {"sha256": checksum}})
        return {"object_key": key, "content_type": "video/mp4", "byte_size": path.stat().st_size, "checksum_sha256": checksum}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
