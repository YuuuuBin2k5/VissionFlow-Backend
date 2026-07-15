import sys
import unittest
import uuid
from pathlib import Path


SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.application.publish_outbox import PendingOutboxEvent, PublishOutbox  # noqa: E402


class FakeRepository:
    def __init__(self, events: list[PendingOutboxEvent]) -> None:
        self.events = events
        self.marked: list[uuid.UUID] = []

    def claim_pending(self, limit: int) -> list[PendingOutboxEvent]:
        return self.events[:limit]

    def mark_published(self, event_id: uuid.UUID) -> None:
        self.marked.append(event_id)


class RecordingPublisher:
    def __init__(self) -> None:
        self.events: list[PendingOutboxEvent] = []

    def publish(self, event: PendingOutboxEvent) -> None:
        self.events.append(event)


class PublishOutboxTests(unittest.TestCase):
    def test_publishes_stable_event_before_marking_it_delivered(self) -> None:
        event = PendingOutboxEvent(
            id=uuid.uuid4(),
            aggregate_type="workflow_run",
            aggregate_id=uuid.uuid4(),
            event_type="visionflow.workflow_run.opened.v1",
            payload={"workflow_run_id": "example"},
            trace_id="a" * 32,
        )
        repository = FakeRepository([event])
        publisher = RecordingPublisher()

        count = PublishOutbox(repository, publisher).execute()

        self.assertEqual(1, count)
        self.assertEqual([event], publisher.events)
        self.assertEqual([event.id], repository.marked)

    def test_rejects_unbounded_batch_size(self) -> None:
        with self.assertRaisesRegex(ValueError, "between"):
            PublishOutbox(FakeRepository([]), RecordingPublisher()).execute(limit=0)
