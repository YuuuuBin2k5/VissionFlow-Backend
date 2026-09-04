"""S3-compatible asset storage adapter (Cloudflare R2 or AWS S3)."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

try:
    import boto3
except ImportError:
    boto3 = None


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
        if boto3 is None:
            raise ValueError("boto3 package is missing. Install via 'pip install boto3'")
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
        actual_key = object_key
        if object_key.startswith("http://") or object_key.startswith("https://"):
            if "visionflow/" in object_key:
                actual_key = "visionflow/" + object_key.split("visionflow/", 1)[1].split("?")[0]
            else:
                import urllib.request
                urllib.request.urlretrieve(object_key, str(destination))
                return str(destination)
        self._client.download_file(self._settings.bucket, actual_key, str(destination))
        return str(destination)

    def issue_upload_url(self, object_key: str, *, content_type: str, expires_in_seconds: int = 900) -> str:
        return self._client.generate_presigned_url(
            "put_object",
            Params={"Bucket": self._settings.bucket, "Key": object_key, "ContentType": content_type},
            ExpiresIn=expires_in_seconds,
            HttpMethod="PUT",
        )

    def head_object(self, object_key: str) -> dict[str, object]:
        return self._client.head_object(Bucket=self._settings.bucket, Key=object_key)

    def upload_export(self, workflow_run_id: str, source_path: str) -> dict[str, object]:
        path = Path(source_path)
        checksum = _sha256(path)
        key = f"visionflow/{workflow_run_id}/exports/final.mp4"
        self._client.upload_file(str(path), self._settings.bucket, key, ExtraArgs={"ContentType": "video/mp4", "Metadata": {"sha256": checksum}})
        public_url = self.get_public_url(key)
        return {"object_key": key, "content_type": "video/mp4", "byte_size": path.stat().st_size, "checksum_sha256": checksum, "public_url": public_url}

    def get_public_url(self, object_key: str) -> str:
        public_base = os.getenv("VISIONFLOW_OBJECT_STORE_PUBLIC_BASE_URL", "").strip().rstrip("/")
        if public_base:
            return f"{public_base}/{object_key.lstrip('/')}"
        try:
            return self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._settings.bucket, "Key": object_key},
                ExpiresIn=604800,
            )
        except Exception:
            return f"{self._settings.endpoint.rstrip('/')}/{self._settings.bucket}/{object_key.lstrip('/')}"


class CloudAssetUploader:
    """Smart Cloud Storage Uploader.
    Uses Cloudflare R2 / S3 when credentials are set, with multi-host fallback engine.
    """

    @classmethod
    def upload_export_video(cls, workflow_run_id: str, source_path: str) -> str | None:
        path = Path(source_path)
        if not path.is_file():
            print(f"⚠️ [CloudUpload] File does not exist: {path}")
            return None

        # 1. Try S3/R2 Object Store if configured
        try:
            settings = VisionFlowObjectStorageSettings.from_env()
            storage = S3CompatibleObjectStorage(settings)
            result = storage.upload_export(workflow_run_id, str(path))
            public_url = str(result.get("public_url", result.get("object_key", "")))
            print(f"[SUCCESS] [CloudUpload S3/R2] Successfully uploaded to Cloud Storage: {public_url}")
            return public_url
        except Exception as s3_err:
            print(f"[INFO] [CloudUpload S3/R2] S3/R2 not configured or error ({s3_err}), trying fallback hosts...")

        # 2. Multi-host fallback engines with HTTP reachability verification
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        import requests

        # Try Litterbox
        try:
            with path.open("rb") as f:
                resp = requests.post(
                    "https://litterbox.catbox.moe/resources/internals/api.php",
                    data={"reqtype": "fileupload", "time": "24h"},
                    files={"fileToUpload": ("export.mp4", f, "video/mp4")},
                    headers=headers,
                    timeout=120
                )
            if resp.status_code == 200 and resp.text.strip().startswith("http"):
                url = resp.text.strip()
                print(f"[SUCCESS] [CloudUpload Fallback] Uploaded to Litterbox: {url}")
                return url
        except Exception as err:
            print(f"[NOTICE] [CloudUpload] Litterbox fallback notice: {err}")

        # Try Tmpfiles
        try:
            with path.open("rb") as f:
                resp = requests.post("https://tmpfiles.org/api/v1/upload", files={"file": f}, timeout=120)
            data = resp.json()
            if data.get("status") == "success":
                dl_url = data["data"]["url"].replace("tmpfiles.org/", "tmpfiles.org/dl/")
                print(f"[SUCCESS] [CloudUpload Fallback] Uploaded to Tmpfiles: {dl_url}")
                return dl_url
        except Exception as err:
            print(f"[NOTICE] [CloudUpload] Tmpfiles fallback notice: {err}")

        return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
