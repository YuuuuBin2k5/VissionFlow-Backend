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

    def test_executes_only_tenant_scoped_publishing_event(self) -> None:
        with patch("consumer.execute") as execute:
            consumer._handle({"event_type": "visionflow.workflow_run.state_changed.v1", "payload": '{"to_state":"PUBLISHING","workflow_run_id":"run-1","organization_id":"org-1"}'})
        execute.assert_called_once_with("run-1", "org-1")

    def test_rejects_publishing_event_without_organization(self) -> None:
        with self.assertRaisesRegex(ValueError, "tenant-scoped"):
            consumer._handle({"event_type": "visionflow.workflow_run.state_changed.v1", "payload": '{"to_state":"PUBLISHING","workflow_run_id":"run-1"}'})


if __name__ == "__main__":
    unittest.main()
