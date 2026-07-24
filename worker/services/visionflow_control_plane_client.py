"""Client-credentials adapter for the VisionFlow Control Plane.

This module is deliberately independent from the legacy MySQL repositories. New
workers submit state transitions through the API and never write PostgreSQL
workflow state directly.

VF-03.02a.2: Added get_execution_context_by_job_id() for per-job authoritative
context retrieval. Workers MUST use this method to obtain workflow_run_id,
organization_id, narration_attempt_id, and trace_id for each job rather than
deriving them from environment variables or queue message fields.
"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass
from typing import Any

import requests


class VisionFlowConfigurationError(ValueError):
    pass


class VisionFlowControlPlaneError(RuntimeError):
    pass


@dataclass(frozen=True)
class VisionFlowWorkerSettings:
    api_url: str
    organization_id: str
    token_url: str
    client_id: str
    client_secret: str
    audience: str

    @classmethod
    def from_env(cls) -> "VisionFlowWorkerSettings":
        api_url = _required("VISIONFLOW_CONTROL_PLANE_URL").rstrip("/")
        token_url = _required("VISIONFLOW_TOKEN_URL")
        if not api_url.startswith(("https://", "http://localhost")):
            raise VisionFlowConfigurationError("VISIONFLOW_CONTROL_PLANE_URL must use HTTPS outside local development")
        if not token_url.startswith("https://"):
            raise VisionFlowConfigurationError("VISIONFLOW_OIDC_TOKEN_URL must use HTTPS")
        return cls(
            api_url=api_url,
            organization_id=_required("VISIONFLOW_ORGANIZATION_ID"),
            token_url=token_url,
            client_id=_required("VISIONFLOW_WORKER_CLIENT_ID"),
            client_secret=_required("VISIONFLOW_WORKER_CLIENT_SECRET"),
            audience=_required("VISIONFLOW_AUTH_AUDIENCE"),
        )


from urllib3.util import Retry
from requests.adapters import HTTPAdapter


def _create_http_session() -> requests.Session:
    session = requests.Session()
    retries = Retry(
        total=3,
        backoff_factor=1.5,
        status_forcelist=[500, 502, 503, 504],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


class VisionFlowControlPlaneClient:
    def __init__(self, settings: VisionFlowWorkerSettings, *, http: requests.Session | None = None) -> None:
        self._settings = settings
        self._http = http or _create_http_session()
        self._access_token: str | None = None
        self._access_token_expires_at = 0.0

    def get_execution_context_by_job_id(
        self,
        job_id: int | str,
        *,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """Fetch the authoritative per-job execution context from the Control Plane.

        This is the canonical way for the worker to obtain workflow_run_id,
        organization_id, narration_attempt_id, and trace_id for a given job.
        The lookup uses the immutable legacy_job_id reference stored in the
        workflow_runs table (added in migration 0007).

        Args:
            job_id: The legacy MySQL job ID as provided by the queue envelope.
            trace_id: Optional X-Request-ID for correlation. A UUID is used
                if not provided.

        Returns:
            A dict containing workflow_run_id, organization_id,
            narration_attempt_id, trace_id, issued_at, and event_version.

        Raises:
            VisionFlowControlPlaneError: On any non-200 HTTP response or if the
                response body is not a valid JSON object.
        """
        response = self._http.get(
            f"{self._settings.api_url}/workflows/execution-context-by-job/{job_id}",
            params={"organization_id": self._settings.organization_id},
            headers={
                "Authorization": f"Bearer {self._get_access_token()}",
                "X-Request-ID": trace_id or uuid.uuid4().hex,
            },
            timeout=(15, 90),
        )
        if response.status_code != 200:
            detail = _response_detail(response)
            raise VisionFlowControlPlaneError(
                f"Control Plane execution-context-by-job failed with HTTP {response.status_code}: {detail}"
            )
        payload = response.json()
        if not isinstance(payload, dict):
            raise VisionFlowControlPlaneError(
                "Control Plane execution-context-by-job response must be a JSON object"
            )
        return payload

    def _request_with_retry(
        self,
        method: str,
        url: str,
        *,
        max_attempts: int = 4,
        timeout: tuple[int, int] = (15, 90),
        **kwargs: Any,
    ) -> requests.Response:
        last_err: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                response = self._http.request(method, url, timeout=timeout, **kwargs)
                if response.status_code in (502, 503, 504) and attempt < max_attempts:
                    time.sleep(3.0 * attempt)
                    continue
                return response
            except requests.exceptions.RequestException as err:
                last_err = err
                if attempt < max_attempts:
                    time.sleep(3.0 * attempt)
                else:
                    raise
        if last_err:
            raise last_err
        raise VisionFlowControlPlaneError(f"HTTP request to {url} failed after {max_attempts} attempts")

    def get_execution_context_by_job_id(
        self,
        job_id: int | str,
        *,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        response = self._request_with_retry(
            "GET",
            f"{self._settings.api_url}/workflows/execution-context-by-job/{job_id}",
            params={"organization_id": self._settings.organization_id},
            headers={
                "Authorization": f"Bearer {self._get_access_token()}",
                "X-Request-ID": trace_id or uuid.uuid4().hex,
            },
            timeout=(15, 90),
        )
        if response.status_code != 200:
            detail = _response_detail(response)
            raise VisionFlowControlPlaneError(
                f"Control Plane execution-context-by-job failed with HTTP {response.status_code}: {detail}"
            )
        payload = response.json()
        if not isinstance(payload, dict):
            raise VisionFlowControlPlaneError(
                "Control Plane execution-context-by-job response must be a JSON object"
            )
        return payload

    def advance_workflow(
        self,
        workflow_run_id: str,
        expected_state: str,
        target_state: str,
        output_payload: dict[str, Any],
        *,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        response = self._request_with_retry(
            "POST",
            f"{self._settings.api_url}/workflows/{workflow_run_id}/transitions",
            json={
                "organization_id": self._settings.organization_id,
                "expected_state": expected_state,
                "target_state": target_state,
                "output_payload": output_payload,
            },
            headers={
                "Authorization": f"Bearer {self._get_access_token()}",
                "X-Request-ID": trace_id or uuid.uuid4().hex,
            },
            timeout=(15, 90),
        )
        if response.status_code not in (200, 201):
            detail = _response_detail(response)
            raise VisionFlowControlPlaneError(
                f"Control Plane transition failed with HTTP {response.status_code}: {detail}"
            )
        return response.json()

    def open_manual_approval(
        self,
        workflow_run_id: str,
        *,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        response = self._request_with_retry(
            "POST",
            f"{self._settings.api_url}/workflows/{workflow_run_id}/approval/open",
            json={"organization_id": self._settings.organization_id},
            headers={
                "Authorization": f"Bearer {self._get_access_token()}",
                "X-Request-ID": trace_id or uuid.uuid4().hex,
            },
            timeout=(15, 90),
        )
        if response.status_code not in (200, 201):
            detail = _response_detail(response)
            raise VisionFlowControlPlaneError(
                f"Control Plane approval handoff failed with HTTP {response.status_code}: {detail}"
            )
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("state") != "APPROVAL_PENDING":
            raise VisionFlowControlPlaneError("Control Plane approval handoff returned an invalid state")
        return payload

    def get_execution_context(
        self,
        workflow_run_id: str,
        *,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        response = self._request_with_retry(
            "GET",
            f"{self._settings.api_url}/workflows/{workflow_run_id}/execution-context",
            params={"organization_id": self._settings.organization_id},
            headers={
                "Authorization": f"Bearer {self._get_access_token()}",
                "X-Request-ID": trace_id or uuid.uuid4().hex,
            },
            timeout=(15, 90),
        )
        if response.status_code != 200:
            detail = _response_detail(response)
            raise VisionFlowControlPlaneError(
                f"Control Plane execution context failed with HTTP {response.status_code}: {detail}"
            )
        payload = response.json()
        if not isinstance(payload, dict):
            raise VisionFlowControlPlaneError("Control Plane execution context response must be an object")
        return payload

    def get_creative_document(self, workflow_run_id: str, *, trace_id: str | None = None) -> dict[str, Any]:
        response = self._request_with_retry(
            "GET",
            f"{self._settings.api_url}/workflows/{workflow_run_id}/creative-document",
            params={"organization_id": self._settings.organization_id},
            headers={"Authorization": f"Bearer {self._get_access_token()}", "X-Request-ID": trace_id or uuid.uuid4().hex},
            timeout=(15, 90),
        )
        if response.status_code != 200:
            raise VisionFlowControlPlaneError(f"Control Plane creative document failed with HTTP {response.status_code}: {_response_detail(response)}")
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("state") != "locked":
            raise VisionFlowControlPlaneError("Control Plane did not return a locked creative document")
        return payload

    def get_composition(self, workflow_run_id: str, *, trace_id: str | None = None) -> dict[str, Any]:
        response = self._request_with_retry(
            "GET",
            f"{self._settings.api_url}/workflows/{workflow_run_id}/composition",
            params={"organization_id": self._settings.organization_id},
            headers={"Authorization": f"Bearer {self._get_access_token()}", "X-Request-ID": trace_id or uuid.uuid4().hex},
            timeout=(15, 90),
        )
        if response.status_code != 200:
            raise VisionFlowControlPlaneError(f"Control Plane composition failed with HTTP {response.status_code}: {_response_detail(response)}")
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("state") != "locked":
            raise VisionFlowControlPlaneError("Control Plane did not return a locked composition")
        return payload

    def resolve_provider_credentials(self, provider: str, *, trace_id: str | None = None) -> list[dict[str, Any]]:
        response = self._request_with_retry(
            "GET",
            f"{self._settings.api_url}/organizations/{self._settings.organization_id}/provider-credentials/{provider}/resolve",
            headers={"Authorization": f"Bearer {self._get_access_token()}", "X-Request-ID": trace_id or uuid.uuid4().hex},
            timeout=(15, 90),
        )
        if response.status_code != 200:
            raise VisionFlowControlPlaneError(f"Control Plane provider credential resolution failed with HTTP {response.status_code}")
        payload = response.json()
        if not isinstance(payload, list) or not all(isinstance(item, dict) and isinstance(item.get("secret"), str) for item in payload):
            raise VisionFlowControlPlaneError("Control Plane returned invalid provider credential data")
        return payload

    def get_composition_render_plan(self, workflow_run_id: str, *, trace_id: str | None = None) -> dict[str, Any]:
        response = self._request_with_retry(
            "GET",
            f"{self._settings.api_url}/workflows/{workflow_run_id}/composition/render-plan",
            params={"organization_id": self._settings.organization_id},
            headers={"Authorization": f"Bearer {self._get_access_token()}", "X-Request-ID": trace_id or uuid.uuid4().hex},
            timeout=(15, 90),
        )
        if response.status_code != 200:
            raise VisionFlowControlPlaneError(
                f"Control Plane render plan failed with HTTP {response.status_code}: {_response_detail(response)}"
            )
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("fingerprint"), str) or len(payload["fingerprint"]) != 64:
            raise VisionFlowControlPlaneError("Control Plane did not return a valid render plan fingerprint")
        return payload

    def complete_narration(
        self,
        *,
        workflow_run_id: str,
        organization_id: str,
        idempotency_key: str,
        script: str,
        scenes: list[dict[str, Any]],
        source_metadata: dict[str, Any],
        legacy_job_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        if organization_id != self._settings.organization_id:
            raise ValueError("organization_id mismatch with configured client settings")
        url = f"{self._settings.api_url}/workflows/{workflow_run_id}/complete-narration"
        response = self._request_with_retry(
            "POST",
            url,
            json={
                "organization_id": organization_id,
                "idempotency_key": idempotency_key,
                "script": script,
                "scenes": scenes,
                "source_metadata": source_metadata,
                "legacy_job_id": legacy_job_id,
            },
            headers={
                "Authorization": f"Bearer {self._get_access_token()}",
                "X-Request-ID": trace_id or uuid.uuid4().hex,
            },
            timeout=(15, 90),
        )
        if response.status_code not in (200, 201):
            detail = _response_detail(response)
            raise VisionFlowControlPlaneError(
                f"Control Plane complete-narration failed with HTTP {response.status_code}: {detail}"
            )
        return response.json()

    def _get_access_token(self) -> str:
        if self._access_token and time.monotonic() < self._access_token_expires_at:
            return self._access_token
        response = self._request_with_retry(
            "POST",
            self._settings.token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self._settings.client_id,
                "client_secret": self._settings.client_secret,
                "audience": self._settings.audience,
            },
            headers={"Accept": "application/json"},
            timeout=(15, 60),
            max_attempts=4,
        )
        if response.status_code != 200:
            raise VisionFlowControlPlaneError(
                f"Control Plane client-credentials exchange failed with HTTP {response.status_code}"
            )
        payload = response.json()
        access_token = payload.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise VisionFlowControlPlaneError("OIDC token response did not include access_token")
        expires_in = payload.get("expires_in", 300)
        self._access_token = access_token
        self._access_token_expires_at = time.monotonic() + max(1, int(expires_in) - 60)
        return access_token


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise VisionFlowConfigurationError(f"{name} must be configured")
    return value


def _response_detail(response: requests.Response) -> str:
    try:
        payload = response.json()
        detail = payload.get("detail")
        if isinstance(detail, str):
            return detail
    except ValueError:
        pass
    return "no safe detail returned"
