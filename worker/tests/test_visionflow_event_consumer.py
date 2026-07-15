import json
import unittest

from worker.services.visionflow_event_consumer import VisionFlowEventConsumer, VisionFlowEventConsumerSettings


class FakeRedis:
    def __init__(self, messages):
        self.messages = messages
        self.acks = []

    def xreadgroup(self, *args, **kwargs):
        return self.messages

    def xack(self, *args):
        self.acks.append(args)


class RecordingControlPlane:
    def __init__(self):
        self.calls = []

    def advance_workflow(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return {"changed": True}

    def get_creative_document(self, *args, **kwargs):
        return {"state": "locked", "version_id": "creative-v1"}


class RecordingIntelligence:
    def __init__(self):
        self.calls = []

    def execute(self, *args, **kwargs):
        self.calls.append((args, kwargs))


class RecordingRenderDispatcher:
    def __init__(self):
        self.calls = []

    def dispatch(self, *args, **kwargs):
        self.calls.append((args, kwargs))


class VisionFlowEventConsumerTests(unittest.TestCase):
    def test_claims_queued_workflow_then_acknowledges_message(self):
        fields = {
            "event_id": "event-1",
            "event_type": "visionflow.workflow_run.state_changed.v1",
            "trace_id": "a" * 32,
            "payload": json.dumps({
                "workflow_run_id": "run-1",
                "to_state": "QUEUED",
                "intake": {"brief": "A concise creator brief."},
            }),
        }
        redis = FakeRedis([("visionflow.workflow-events.v1", [("1-0", fields)])])
        control_plane = RecordingControlPlane()
        intelligence = RecordingIntelligence()
        consumer = VisionFlowEventConsumer(
            redis,
            VisionFlowEventConsumerSettings("rediss://example", "visionflow.workflow-events.v1", "group", "consumer"),
            control_plane,
            intelligence,
        )

        self.assertEqual(1, consumer.consume_once(block_ms=1))
        self.assertEqual(
            ("run-1", {"brief": "A concise creator brief.", "creative_document": {"state": "locked", "version_id": "creative-v1"}}),
            intelligence.calls[0][0],
        )
        self.assertEqual("event-1", intelligence.calls[0][1]["event_id"])
        self.assertEqual([("visionflow.workflow-events.v1", "group", "1-0")], redis.acks)

    def test_acknowledges_unrelated_events_without_starting_work(self):
        redis = FakeRedis([("visionflow.workflow-events.v1", [("1-0", {"event_type": "other", "payload": "{}"})])])
        control_plane = RecordingControlPlane()
        intelligence = RecordingIntelligence()
        consumer = VisionFlowEventConsumer(
            redis,
            VisionFlowEventConsumerSettings("rediss://example", "visionflow.workflow-events.v1", "group", "consumer"),
            control_plane,
            intelligence,
        )

        consumer.consume_once(block_ms=1)
        self.assertEqual([], intelligence.calls)
        self.assertEqual(1, len(redis.acks))

    def test_dispatches_storyboarded_workflow_to_injected_renderer_then_acknowledges(self):
        fields = {
            "event_id": "event-2",
            "event_type": "visionflow.workflow_run.state_changed.v1",
            "trace_id": "b" * 32,
            "payload": json.dumps({"workflow_run_id": "run-2", "to_state": "STORYBOARDED"}),
        }
        redis = FakeRedis([("visionflow.workflow-events.v1", [("2-0", fields)])])
        dispatcher = RecordingRenderDispatcher()
        consumer = VisionFlowEventConsumer(
            redis,
            VisionFlowEventConsumerSettings("rediss://example", "visionflow.workflow-events.v1", "group", "consumer"),
            RecordingControlPlane(),
            RecordingIntelligence(),
            dispatcher,
        )

        self.assertEqual(1, consumer.consume_once(block_ms=1))
        self.assertEqual([(("run-2",), {"trace_id": "b" * 32})], dispatcher.calls)
        self.assertEqual([("visionflow.workflow-events.v1", "group", "2-0")], redis.acks)
