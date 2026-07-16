"""One trusted VisionFlow YouTube publish execution; designed for a worker/cron invocation."""
from __future__ import annotations

import argparse
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


def execute(workflow_run_id: str, organization_id: str) -> str:
    base_url = _required("VISIONFLOW_CONTROL_PLANE_URL").rstrip("/")
    session = requests.Session()
    token = _service_token(session, base_url)
    headers = {"Authorization": f"Bearer {token}"}
    manifest_response = session.get(f"{base_url}/integrations/youtube/publish-manifests/{workflow_run_id}", params={"organization_id": organization_id}, headers=headers, timeout=(5, 30))
    manifest = manifest_response.json() if manifest_response.status_code == 200 else {}
    if not isinstance(manifest, dict):
        raise RuntimeError("Control Plane did not issue publish manifest")
    with tempfile.TemporaryDirectory(prefix="visionflow-publish-") as directory:
        artifact_path = Path(directory) / "final.mp4"
        with session.get(str(manifest["artifact_download_url"]), stream=True, timeout=(10, 600)) as artifact_response:
            artifact_response.raise_for_status()
            with artifact_path.open("wb") as destination:
                for chunk in artifact_response.iter_content(1024 * 1024):
                    if chunk:
                        destination.write(chunk)
        uploaded = YouTubeResumableUploader(session).upload(access_token=str(manifest["access_token"]), video_path=artifact_path, metadata=YouTubeUploadMetadata(str(manifest["title"]), str(manifest["description"]), ("Shorts",)))
    completed = session.post(f"{base_url}/integrations/youtube/publish-manifests/{workflow_run_id}/complete", headers=headers, json={"organization_id": organization_id, "publisher_connection_id": manifest["publisher_connection_id"], "video_id": uploaded.video_id, "video_url": uploaded.url}, timeout=(5, 30))
    completed.raise_for_status()
    return uploaded.url


def record_failure(workflow_run_id: str, organization_id: str, publisher_connection_id: str, failure_code: str) -> None:
    base_url = _required("VISIONFLOW_CONTROL_PLANE_URL").rstrip("/")
    session = requests.Session()
    token = _service_token(session, base_url)
    response = session.post(f"{base_url}/integrations/youtube/publish-manifests/{workflow_run_id}/fail", headers={"Authorization": f"Bearer {token}"}, json={"organization_id": organization_id, "publisher_connection_id": publisher_connection_id, "failure_code": failure_code}, timeout=(5, 30))
    response.raise_for_status()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Publish one approved VisionFlow video to YouTube")
    parser.add_argument("--workflow-run-id", required=True)
    parser.add_argument("--organization-id", required=True)
    arguments = parser.parse_args()
    print(execute(arguments.workflow_run_id, arguments.organization_id))
