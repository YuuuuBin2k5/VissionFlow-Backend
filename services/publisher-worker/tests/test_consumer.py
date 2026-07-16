import sys
import unittest
from pathlib import Path
from unittest.mock import patch


WORKER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKER_ROOT))

import consumer  # noqa: E402


class PublisherConsumerTests(unittest.TestCase):
    def test_ignores_unrelated_events(self) -> None:
        with patch("consumer.execute") as execute:
            consumer._handle({"event_type": "visionflow.workflow_run.state_changed.v1", "payload": '{"to_state":"APPROVED"}'})
        execute.assert_not_called()

    def test_ignores_publishing_state_event_because_attempt_owns_the_lease(self) -> None:
        with patch("consumer.execute") as execute:
            consumer._handle({"event_type": "visionflow.workflow_run.state_changed.v1", "payload": '{"to_state":"PUBLISHING","workflow_run_id":"run-1","organization_id":"org-1"}'})
        execute.assert_not_called()

    def test_ignores_publishing_audit_event_without_execution_payload(self) -> None:
        consumer._handle({"event_type": "visionflow.workflow_run.state_changed.v1", "payload": '{"to_state":"PUBLISHING","workflow_run_id":"run-1"}'})

    def test_executes_a_tenant_scoped_publication_attempt(self) -> None:
        with patch("consumer.execute_publication_attempt") as execute_attempt:
            consumer._handle({"event_type": "visionflow.publication_attempt.requested.v1", "payload": '{"publication_attempt_id":"attempt-1","organization_id":"org-1"}'})
        execute_attempt.assert_called_once_with("attempt-1", "org-1")

    def test_rejects_publication_attempt_without_organization(self) -> None:
        with self.assertRaisesRegex(ValueError, "tenant-scoped"):
            consumer._handle({"event_type": "visionflow.publication_attempt.requested.v1", "payload": '{"publication_attempt_id":"attempt-1"}'})


if __name__ == "__main__":
    unittest.main()
