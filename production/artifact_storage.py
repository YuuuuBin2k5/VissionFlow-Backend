"""Auto Production bridge to the existing S3/R2 adapter (no fallback hosts)."""
from pathlib import Path
from production.remote_manifest import sha256_file, validate_storage_ref
from worker.services.visionflow_object_storage import S3CompatibleObjectStorage, VisionFlowObjectStorageSettings


class ArtifactStorage:
    def __init__(self, adapter=None):
        self.adapter = adapter or S3CompatibleObjectStorage(VisionFlowObjectStorageSettings.from_env())

    def put_file(self, storage_ref: str, path: Path, mime_type: str) -> dict:
        return self.adapter.put_file(validate_storage_ref(storage_ref), str(path), content_type=mime_type)

    def metadata(self, storage_ref: str) -> dict:
        return self.adapter.head_object(validate_storage_ref(storage_ref))

    def object_exists(self, storage_ref: str) -> bool:
        try:
            self.metadata(storage_ref)
            return True
        except Exception as exc:
            if getattr(exc, "response", {}).get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return False
            raise

    def presigned_download(self, storage_ref: str) -> str:
        return self.adapter.generate_presigned_download_url(validate_storage_ref(storage_ref), expires_in_seconds=900)

    def presigned_upload(self, storage_ref: str, checksum: str) -> dict:
        url = self.adapter.issue_upload_url(validate_storage_ref(storage_ref), content_type="video/mp4", checksum_sha256=checksum, expires_in_seconds=900)
        return {"storage_ref": storage_ref, "upload_url": url,
                "headers": {"Content-Type": "video/mp4", "x-amz-meta-sha256": checksum}}

    def download_to(self, storage_ref: str, path: Path):
        self.adapter.download_to(validate_storage_ref(storage_ref), str(path))


def get_artifact_storage() -> ArtifactStorage:
    return ArtifactStorage()
