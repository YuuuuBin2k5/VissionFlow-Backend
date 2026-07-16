from __future__ import annotations

import os
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch


SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.application.publish_outbox import PendingOutboxEvent  # noqa: E402
from app.core.intake_signing import IntakeSigningSettings, sign  # noqa: E402
from app.infrastructure.redis_stream_publisher import RedisStreamEventPublisher  # noqa: E402


class _RecordingRedis:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []

    def xadd(self, stream: str, fields: dict[str, str]) -> str:
        self.calls.append((stream, fields))
        return "1-0"


class RedisStreamIntakeSigningTests(unittest.TestCase):
    def test_signs_only_legacy_job_requested_with_canonical_envelope(self) -> None:
        event = PendingOutboxEvent(
            id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
            aggregate_type="workflow_run",
            aggregate_id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
            event_type="visionflow.legacy_job.requested.v1",
            payload={"event_version": 1, "workflow_run_id": "22222222-2222-2222-2222-222222222222"},
            trace_id="a" * 32,
        )
        redis = _RecordingRedis()
        with patch.dict(
            os.environ,
            {"VISIONFLOW_INTAKE_HMAC_KEY_ID": "2026-07", "VISIONFLOW_INTAKE_HMAC_KEY": "test-key"},
            clear=True,
        ):
            RedisStreamEventPublisher(redis, "visionflow.workflow-events.v1").publish(event)
            expected = sign(
                {
                    "event_id": str(event.id),
                    "event_type": event.event_type,
                    "aggregate_type": event.aggregate_type,
                    "aggregate_id": str(event.aggregate_id),
                    "trace_id": event.trace_id,
                    "payload": event.payload,
                },
                IntakeSigningSettings.from_env(),
            )

        self.assertEqual(1, len(redis.calls))
        _, fields = redis.calls[0]
        self.assertEqual("2026-07", fields["signature_key_id"])
        self.assertEqual(expected, fields["signature"])

    def test_other_events_do_not_require_intake_hmac_configuration(self) -> None:
        event = PendingOutboxEvent(
            id=uuid.uuid4(),
            aggregate_type="workflow_run",
            aggregate_id=uuid.uuid4(),
            event_type="visionflow.workflow_run.opened.v1",
            payload={"workflow_run_id": "example"},
            trace_id="b" * 32,
        )
        redis = _RecordingRedis()
        with patch.dict(os.environ, {}, clear=True):
            RedisStreamEventPublisher(redis, "visionflow.workflow-events.v1").publish(event)
        self.assertNotIn("signature", redis.calls[0][1])
