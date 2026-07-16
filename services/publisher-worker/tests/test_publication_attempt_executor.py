import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


WORKER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKER_ROOT))

import main  # noqa: E402


class Response:
    def __init__(self, status_code: int, payload: object = None, headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.headers = headers or {"content-type": "application/json"}

    def json(self) -> object:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class PublicationAttemptExecutorTests(unittest.TestCase):
    environment = {
        "VISIONFLOW_CONTROL_PLANE_URL": "https://control.example/api/v1",
        "VISIONFLOW_PUBLISHER_CLIENT_ID": "visionflow-publisher",
        "VISIONFLOW_PUBLISHER_CLIENT_SECRET": "test-secret",
        "VISIONFLOW_AUTH_AUDIENCE": "visionflow-control-plane",
    }

    def test_claims_uploads_and_completes_with_the_lease_token(self) -> None:
        session = Mock()
        manifest = {
            "publisher_connection_id": "connection-1",
            "lease_token": "lease-token-1",
            "artifact_download_url": "https://object.example/final.mp4",
            "access_token": "short-lived",
            "title": "Recovered short",
            "description": "Description",
        }
        session.post.side_effect = [Response(200, manifest), Response(200, {"state": "uploading"}), Response(200, {"state": "succeeded"})]
        with patch.dict(os.environ, self.environment, clear=True), patch("main.requests.Session", return_value=session), patch("main._service_token", return_value="service-token"), patch("main._upload_manifest", return_value=("video-1", "https://www.youtube.com/watch?v=video-1")) as upload:
            result = main.execute_publication_attempt("attempt-1", "org-1")

        self.assertEqual("https://www.youtube.com/watch?v=video-1", result)
        upload.assert_called_once_with(session, manifest)
        mark_call = session.post.call_args_list[1]
        self.assertTrue(mark_call.args[0].endswith("/publication-attempts/attempt-1/mark-uploading"))
        self.assertEqual("lease-token-1", mark_call.kwargs["json"]["lease_token"])
        complete_call = session.post.call_args_list[2]
        self.assertTrue(complete_call.args[0].endswith("/publication-attempts/attempt-1/complete"))
        self.assertEqual("lease-token-1", complete_call.kwargs["json"]["lease_token"])
        self.assertEqual("org-1", complete_call.kwargs["json"]["organization_id"])

    def test_finalized_attempt_is_an_idempotent_noop(self) -> None:
        session = Mock()
        session.post.return_value = Response(409, {"detail": {"code": "PUBLICATION_ATTEMPT_ALREADY_FINALIZED"}})
        with patch.dict(os.environ, self.environment, clear=True), patch("main.requests.Session", return_value=session), patch("main._service_token", return_value="service-token"), patch("main._upload_manifest") as upload:
            result = main.execute_publication_attempt("attempt-1", "org-1")

        self.assertIsNone(result)
        upload.assert_not_called()

    def test_active_lease_remains_retryable(self) -> None:
        session = Mock()
        session.post.return_value = Response(409, {"detail": {"code": "PUBLICATION_ATTEMPT_LEASE_ACTIVE"}})
        with patch.dict(os.environ, self.environment, clear=True), patch("main.requests.Session", return_value=session), patch("main._service_token", return_value="service-token"):
            with self.assertRaisesRegex(RuntimeError, "currently leased"):
                main.execute_publication_attempt("attempt-1", "org-1")


if __name__ == "__main__":
    unittest.main()
