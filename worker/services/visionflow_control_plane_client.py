"""Client-credentials adapter for the VisionFlow Control Plane.

This module is deliberately independent from the legacy MySQL repositories. New
workers submit state transitions through the API and never write PostgreSQL
workflow state directly.
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


class VisionFlowControlPlaneClient:
    def __init__(self, settings: VisionFlowWorkerSettings, *, http: requests.Session | None = None) -> None:
        self._settings = settings
        self._http = http or requests.Session()
        self._access_token: str | None = None
        self._access_token_expires_at = 0.0

    def advance_workflow(
        self,
        workflow_run_id: str,
        expected_state: str,
        target_state: str,
        output_payload: dict[str, Any],
        *,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        response = self._http.post(
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
            timeout=(3, 20),
        )
        if response.status_code not in (200, 201):
            detail = _response_detail(response)
            raise VisionFlowControlPlaneError(
                f"Control Plane transition failed with HTTP {response.status_code}: {detail}"
            )
        return response.json()

    def get_execution_context(
        self,
        workflow_run_id: str,
        *,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """Read the organization-scoped execution context for a workflow.

        The worker must use this service API instead of reading the Control
        Plane database.  ``organization_id`` is sent explicitly because the
        server treats it as a tenancy boundary rather than trusting an ID in a
        queue message alone.
        """
        response = self._http.get(
            f"{self._settings.api_url}/workflows/{workflow_run_id}/execution-context",
            params={"organization_id": self._settings.organization_id},
            headers={
                "Authorization": f"Bearer {self._get_access_token()}",
                "X-Request-ID": trace_id or uuid.uuid4().hex,
            },
            timeout=(3, 20),
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
        """Fetch the immutable operator-approved document through the API."""
        response = self._http.get(
            f"{self._settings.api_url}/workflows/{workflow_run_id}/creative-document",
            params={"organization_id": self._settings.organization_id},
            headers={"Authorization": f"Bearer {self._get_access_token()}", "X-Request-ID": trace_id or uuid.uuid4().hex},
            timeout=(3, 20),
        )
        if response.status_code != 200:
            raise VisionFlowControlPlaneError(f"Control Plane creative document failed with HTTP {response.status_code}: {_response_detail(response)}")
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("state") != "locked":
            raise VisionFlowControlPlaneError("Control Plane did not return a locked creative document")
        return payload

    def _get_access_token(self) -> str:
        if self._access_token and time.monotonic() < self._access_token_expires_at:
            return self._access_token
        response = self._http.post(
            self._settings.token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self._settings.client_id,
                "client_secret": self._settings.client_secret,
                "audience": self._settings.audience,
            },
            headers={"Accept": "application/json"},
            timeout=(3, 15),
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
        # Refresh before expiry.  Very short-lived tokens must never be cached
        # beyond their actual validity window.
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
