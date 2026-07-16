"""One trusted VisionFlow YouTube publish execution; designed for a worker/cron invocation."""
from __future__ import annotations

import argparse
import hashlib
import os
import tempfile
from pathlib import Path

import requests

from visionflow_publisher.youtube_resumable import YouTubeResumableUploader, YouTubeUploadMetadata


def _required(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _service_token(session: requests.Session, base_url: str) -> str:
    response = session.post(f"{base_url}/auth/token", data={"grant_type": "client_credentials", "client_id": _required("VISIONFLOW_PUBLISHER_CLIENT_ID"), "client_secret": _required("VISIONFLOW_PUBLISHER_CLIENT_SECRET"), "audience": _required("VISIONFLOW_AUTH_AUDIENCE"), "scope": "publish:execute"}, timeout=(5, 20))
    data = response.json() if response.status_code == 200 else {}
    token = data.get("access_token") if isinstance(data, dict) else None
    if not isinstance(token, str):
        raise RuntimeError("Control Plane did not issue publisher service token")
    return token


def _upload_manifest(session: requests.Session, manifest: dict[str, object]) -> tuple[str, str]:
    with tempfile.TemporaryDirectory(prefix="visionflow-publish-") as directory:
        artifact_path = Path(directory) / "final.mp4"
        _download_verified_artifact(session, manifest, artifact_path)
        uploaded = YouTubeResumableUploader(session).upload(access_token=str(manifest["access_token"]), video_path=artifact_path, metadata=YouTubeUploadMetadata(str(manifest["title"]), str(manifest["description"]), ("Shorts",)))
    return uploaded.video_id, uploaded.url


def _download_verified_artifact(session: requests.Session, manifest: dict[str, object], destination_path: Path) -> None:
    """Download only the immutable export identified by the Control Plane manifest."""
    expected_size = manifest.get("artifact_byte_size")
    expected_checksum = manifest.get("artifact_checksum_sha256")
    if not isinstance(expected_size, int) or isinstance(expected_size, bool) or expected_size < 1:
        raise RuntimeError("Publish manifest has an invalid artifact size")
    if not isinstance(expected_checksum, str) or len(expected_checksum) != 64:
        raise RuntimeError("Publish manifest has an invalid artifact checksum")
    digest = hashlib.sha256()
    received_size = 0
    with session.get(str(manifest["artifact_download_url"]), stream=True, timeout=(10, 600)) as artifact_response:
        artifact_response.raise_for_status()
        with destination_path.open("wb") as destination:
            for chunk in artifact_response.iter_content(1024 * 1024):
                if chunk:
                    destination.write(chunk)
                    digest.update(chunk)
                    received_size += len(chunk)
    if received_size != expected_size:
        raise RuntimeError("Downloaded export size does not match the approved artifact")
    if digest.hexdigest() != expected_checksum.lower():
        raise RuntimeError("Downloaded export checksum does not match the approved artifact")


def execute(workflow_run_id: str, organization_id: str) -> str:
    base_url = _required("VISIONFLOW_CONTROL_PLANE_URL").rstrip("/")
    session = requests.Session()
    token = _service_token(session, base_url)
    headers = {"Authorization": f"Bearer {token}"}
    manifest_response = session.get(f"{base_url}/integrations/youtube/publish-manifests/{workflow_run_id}", params={"organization_id": organization_id}, headers=headers, timeout=(5, 30))
    manifest = manifest_response.json() if manifest_response.status_code == 200 else {}
    if not isinstance(manifest, dict):
        raise RuntimeError("Control Plane did not issue publish manifest")
    video_id, video_url = _upload_manifest(session, manifest)
    completed = session.post(f"{base_url}/integrations/youtube/publish-manifests/{workflow_run_id}/complete", headers=headers, json={"organization_id": organization_id, "publisher_connection_id": manifest["publisher_connection_id"], "video_id": video_id, "video_url": video_url}, timeout=(5, 30))
    completed.raise_for_status()
    return video_url


def execute_publication_attempt(publication_attempt_id: str, organization_id: str) -> str | None:
    """Publish one durable retry; a finalized attempt is an idempotent no-op."""
    base_url = _required("VISIONFLOW_CONTROL_PLANE_URL").rstrip("/")
    session = requests.Session()
    token = _service_token(session, base_url)
    headers = {"Authorization": f"Bearer {token}"}
    claim = session.post(
        f"{base_url}/integrations/youtube/publication-attempts/{publication_attempt_id}/claim",
        headers=headers,
        json={"organization_id": organization_id},
        timeout=(5, 30),
    )
    if claim.status_code == 409:
        detail = claim.json().get("detail") if claim.headers.get("content-type", "").startswith("application/json") else None
        code = detail.get("code") if isinstance(detail, dict) else None
        if code == "PUBLICATION_ATTEMPT_ALREADY_FINALIZED":
            return None
        raise RuntimeError("Publication attempt is currently leased")
    claim.raise_for_status()
    manifest = claim.json()
    if not isinstance(manifest, dict):
        raise RuntimeError("Control Plane did not issue publication attempt manifest")
    video_id, video_url = _upload_manifest(session, manifest)
    completed = session.post(
        f"{base_url}/integrations/youtube/publication-attempts/{publication_attempt_id}/complete",
        headers=headers,
        json={
            "organization_id": organization_id,
            "publisher_connection_id": manifest["publisher_connection_id"],
            "lease_token": manifest["lease_token"],
            "video_id": video_id,
            "video_url": video_url,
        },
        timeout=(5, 30),
    )
    # A network retry after a successful completion sees the terminal state.
    if completed.status_code != 409:
        completed.raise_for_status()
    return video_url


def record_failure(workflow_run_id: str, organization_id: str, publisher_connection_id: str, failure_code: str) -> None:
    base_url = _required("VISIONFLOW_CONTROL_PLANE_URL").rstrip("/")
    session = requests.Session()
    token = _service_token(session, base_url)
    response = session.post(f"{base_url}/integrations/youtube/publish-manifests/{workflow_run_id}/fail", headers={"Authorization": f"Bearer {token}"}, json={"organization_id": organization_id, "publisher_connection_id": publisher_connection_id, "failure_code": failure_code}, timeout=(5, 30))
    response.raise_for_status()


def record_publication_attempt_failure(publication_attempt_id: str, organization_id: str, failure_code: str) -> None:
    base_url = _required("VISIONFLOW_CONTROL_PLANE_URL").rstrip("/")
    session = requests.Session()
    token = _service_token(session, base_url)
    response = session.post(
        f"{base_url}/integrations/youtube/publication-attempts/{publication_attempt_id}/fail-terminal",
        headers={"Authorization": f"Bearer {token}"},
        json={"organization_id": organization_id, "failure_code": failure_code},
        timeout=(5, 30),
    )
    if response.status_code != 409:
        response.raise_for_status()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Publish one approved VisionFlow video to YouTube")
    parser.add_argument("--workflow-run-id", required=True)
    parser.add_argument("--organization-id", required=True)
    arguments = parser.parse_args()
    print(execute(arguments.workflow_run_id, arguments.organization_id))
