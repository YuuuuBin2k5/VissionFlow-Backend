import logging
import os
import urllib.parse
import httpx
from worker import config

logger = logging.getLogger(__name__)


class ControlPlaneClient:
    """Client for the Control Plane API to handle workflow step submissions."""

    def __init__(self, base_url: str = config.VISIONFLOW_CONTROL_PLANE_URL) -> None:
        self.base_url = base_url
        self.token_url = os.environ.get("VISIONFLOW_TOKEN_URL", "")
        self.client_id = os.environ.get("VISIONFLOW_WORKER_CLIENT_ID", "")
        self.client_secret = os.environ.get("VISIONFLOW_WORKER_CLIENT_SECRET", "")
        self.audience = os.environ.get("VISIONFLOW_AUTH_AUDIENCE", "")
        self._cached_token = None

    def _get_access_token(self) -> str:
        if self._cached_token:
            return self._cached_token
        if not self.token_url or not self.client_id or not self.client_secret:
            raise ValueError("Control plane token credentials are not fully configured")

        payload = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "audience": self.audience,
        }
        encoded = urllib.parse.urlencode(payload)
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        logger.info("Requesting service token from Control Plane")
        response = httpx.post(self.token_url, content=encoded, headers=headers)
        if response.status_code != 200:
            raise RuntimeError(f"Failed to authenticate with control plane: {response.text}")

        data = response.json()
        self._cached_token = data["access_token"]
        return self._cached_token

    def complete_narration(
        self,
        *,
        workflow_run_id: str,
        organization_id: str,
        idempotency_key: str,
        script: str,
        scenes: list[dict],
        source_metadata: dict,
        legacy_job_id: int | None = None,
        trace_id: str | None = None,
    ) -> dict:
        """Call complete-narration endpoint on the Control Plane."""
        url = f"{self.base_url}/workflows/{workflow_run_id}/complete-narration"
        token = self._get_access_token()

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        if trace_id:
            headers["X-Request-ID"] = trace_id

        payload = {
            "organization_id": organization_id,
            "idempotency_key": idempotency_key,
            "script": script,
            "scenes": scenes,
            "source_metadata": source_metadata,
            "legacy_job_id": legacy_job_id,
        }

        logger.info(f"Submitting narration result to Control Plane for run {workflow_run_id}")
        response = httpx.post(url, json=payload, headers=headers)
        if response.status_code not in (200, 201):
            raise RuntimeError(f"Control plane complete-narration failed ({response.status_code}): {response.text}")

        return response.json()
