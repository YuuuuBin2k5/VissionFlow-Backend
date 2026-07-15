import os
import unittest
from unittest.mock import patch

from worker.services.visionflow_control_plane_client import (
    VisionFlowConfigurationError,
    VisionFlowControlPlaneClient,
    VisionFlowWorkerSettings,
)


class FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class RecordingHttp:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def post(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        if url.endswith("/auth/token"):
            return FakeResponse(200, {"access_token": "service-access-token", "expires_in": 300})
        return FakeResponse(200, {"workflow_run_id": "run-1", "state": "PLANNING", "changed": True})

    def get(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        return FakeResponse(
            200,
            {
                "workflow_run_id": "run-1",
                "state": "STORYBOARDED",
                "intake": {"brief": "A production-ready brief"},
                "steps": [{"step_type": "SCRIPT", "output_payload": {"script": "..."}}],
            },
        )


class VisionFlowWorkerSettingsTests(unittest.TestCase):
    def test_requires_https_for_non_local_control_plane(self) -> None:
        values = {
            "VISIONFLOW_CONTROL_PLANE_URL": "http://visionflow.internal/api/v1",
            "VISIONFLOW_ORGANIZATION_ID": "00000000-0000-0000-0000-000000000001",
            "VISIONFLOW_TOKEN_URL": "https://visionflow.example.com/api/v1/auth/token",
            "VISIONFLOW_WORKER_CLIENT_ID": "intelligence-worker",
            "VISIONFLOW_WORKER_CLIENT_SECRET": "not-a-real-secret",
            "VISIONFLOW_AUTH_AUDIENCE": "visionflow-control-plane",
        }
        with patch.dict(os.environ, values, clear=True):
            with self.assertRaisesRegex(VisionFlowConfigurationError, "HTTPS"):
                VisionFlowWorkerSettings.from_env()

    def test_accepts_complete_secure_worker_configuration(self) -> None:
        values = {
            "VISIONFLOW_CONTROL_PLANE_URL": "https://visionflow.example.com/api/v1",
            "VISIONFLOW_ORGANIZATION_ID": "00000000-0000-0000-0000-000000000001",
            "VISIONFLOW_TOKEN_URL": "https://visionflow.example.com/api/v1/auth/token",
            "VISIONFLOW_WORKER_CLIENT_ID": "intelligence-worker",
            "VISIONFLOW_WORKER_CLIENT_SECRET": "not-a-real-secret",
            "VISIONFLOW_AUTH_AUDIENCE": "visionflow-control-plane",
        }
        with patch.dict(os.environ, values, clear=True):
            settings = VisionFlowWorkerSettings.from_env()
        self.assertEqual("intelligence-worker", settings.client_id)

    def test_uses_client_credentials_and_organization_scoped_transition(self) -> None:
        settings = VisionFlowWorkerSettings(
            api_url="https://visionflow.example.com/api/v1",
            organization_id="00000000-0000-0000-0000-000000000001",
            token_url="https://visionflow.example.com/api/v1/auth/token",
            client_id="intelligence-worker",
            client_secret="not-a-real-secret",
            audience="visionflow-control-plane",
        )
        http = RecordingHttp()
        client = VisionFlowControlPlaneClient(settings, http=http)

        result = client.advance_workflow(
            "00000000-0000-0000-0000-000000000002",
            "QUEUED",
            "PLANNING",
            {"worker": "intelligence"},
            trace_id="a" * 32,
        )

        self.assertTrue(result["changed"])
        self.assertEqual(2, len(http.calls))
        self.assertEqual("client_credentials", http.calls[0]["data"]["grant_type"])
        self.assertEqual(
            "Bearer service-access-token",
            http.calls[1]["headers"]["Authorization"],
        )
        self.assertEqual(
            settings.organization_id,
            http.calls[1]["json"]["organization_id"],
        )

    def test_gets_organization_scoped_execution_context_with_service_token(self) -> None:
        settings = VisionFlowWorkerSettings(
            api_url="https://visionflow.example.com/api/v1",
            organization_id="00000000-0000-0000-0000-000000000001",
            token_url="https://visionflow.example.com/api/v1/auth/token",
            client_id="render-worker",
            client_secret="not-a-real-secret",
            audience="visionflow-control-plane",
        )
        http = RecordingHttp()
        client = VisionFlowControlPlaneClient(settings, http=http)

        result = client.get_execution_context(
            "00000000-0000-0000-0000-000000000002",
            trace_id="b" * 32,
        )

        self.assertEqual("STORYBOARDED", result["state"])
        self.assertEqual(2, len(http.calls))
        self.assertEqual("client_credentials", http.calls[0]["data"]["grant_type"])
        self.assertTrue(http.calls[1]["url"].endswith("/execution-context"))
        self.assertEqual(settings.organization_id, http.calls[1]["params"]["organization_id"])
        self.assertEqual("Bearer service-access-token", http.calls[1]["headers"]["Authorization"])
        self.assertEqual("b" * 32, http.calls[1]["headers"]["X-Request-ID"])

    def test_complete_narration_calls_endpoint(self) -> None:
        settings = VisionFlowWorkerSettings(
            api_url="https://visionflow.example.com/api/v1",
            organization_id="00000000-0000-0000-0000-000000000001",
            token_url="https://visionflow.example.com/api/v1/auth/token",
            client_id="intelligence-worker",
            client_secret="not-a-real-secret",
            audience="visionflow-control-plane",
        )
        http = RecordingHttp()
        client = VisionFlowControlPlaneClient(settings, http=http)

        client.complete_narration(
            workflow_run_id="00000000-0000-0000-0000-000000000002",
            organization_id=settings.organization_id,
            idempotency_key="idempotency-key-narration-01",
            script="This is a valid narration script that is long enough.",
            scenes=[
                {"narration": "Scene 1", "visual_prompt": "Prompt 1", "duration_seconds": 5},
                {"narration": "Scene 2", "visual_prompt": "Prompt 2", "duration_seconds": 10},
                {"narration": "Scene 3", "visual_prompt": "Prompt 3", "duration_seconds": 15},
            ],
            source_metadata={
                "provider": "google",
                "model": "gemini-1.5-pro",
            },
            trace_id="c" * 32,
        )

        self.assertEqual(2, len(http.calls))
        self.assertTrue(http.calls[1]["url"].endswith("/complete-narration"))
        self.assertEqual(
            "Bearer service-access-token",
            http.calls[1]["headers"]["Authorization"],
        )
        self.assertEqual(
            settings.organization_id,
            http.calls[1]["json"]["organization_id"],
        )
        self.assertEqual(
            "idempotency-key-narration-01",
            http.calls[1]["json"]["idempotency_key"],
        )
        self.assertEqual(
            "google",
            http.calls[1]["json"]["source_metadata"]["provider"],
        )

