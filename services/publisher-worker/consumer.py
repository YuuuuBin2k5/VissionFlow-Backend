"""Redis Streams consumer for committed VisionFlow PUBLISHING transitions."""
from __future__ import annotations

import json
import os
import socket
import time
import argparse

from redis import Redis

from main import execute


STREAM = os.getenv("VISIONFLOW_EVENTS_STREAM", "visionflow.workflow-events.v1")
GROUP = os.getenv("VISIONFLOW_PUBLISHER_CONSUMER_GROUP", "visionflow-publisher-v1")
CONSUMER = os.getenv("VISIONFLOW_PUBLISHER_CONSUMER_NAME", socket.gethostname())
DLQ = os.getenv("VISIONFLOW_PUBLISHER_DLQ_STREAM", "visionflow.publisher-dlq.v1")
MAX_ATTEMPTS = int(os.getenv("VISIONFLOW_PUBLISHER_MAX_ATTEMPTS", "5"))
CLAIM_IDLE_MS = int(os.getenv("VISIONFLOW_PUBLISHER_CLAIM_IDLE_MS", "60000"))


def _redis() -> Redis:
    url = (os.getenv("REDIS_URL") or "").strip()
    if not url:
        raise ValueError("REDIS_URL is required")
    return Redis.from_url(url, decode_responses=True)


def main(*, once: bool = False) -> None:
    client = _redis()
    try:
        client.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
    except Exception as exc:
        if "BUSYGROUP" not in str(exc):
            raise
    while True:
        reclaimed = client.xautoclaim(STREAM, GROUP, CONSUMER, CLAIM_IDLE_MS, "0-0", count=10)
        reclaimed_events = reclaimed[1] if len(reclaimed) > 1 else []
        messages = client.xreadgroup(GROUP, CONSUMER, {STREAM: ">"}, count=10, block=5000)
        new_events = [event for _, events in messages for event in events]
        for event_id, fields in [*reclaimed_events, *new_events]:
            _process(client, event_id, fields)
        if once:
            return


def _handle(fields: dict[str, str]) -> None:
    if fields.get("event_type") != "visionflow.workflow_run.state_changed.v1":
        return
    payload = json.loads(fields.get("payload", "{}"))
    if not isinstance(payload, dict) or payload.get("to_state") != "PUBLISHING":
        return
    workflow_run_id, organization_id = payload.get("workflow_run_id"), payload.get("organization_id")
    if not isinstance(workflow_run_id, str) or not isinstance(organization_id, str):
        raise ValueError("PUBLISHING event has no tenant-scoped workflow identifiers")
    execute(workflow_run_id, organization_id)


def _process(client: Redis, event_id: str, fields: dict[str, str]) -> None:
    attempts_key = f"visionflow:publisher:attempts:{event_id}"
    try:
        _handle(fields)
    except Exception as exc:
        attempts = int(client.incr(attempts_key))
        client.expire(attempts_key, 86_400)
        if attempts >= MAX_ATTEMPTS:
            client.xadd(DLQ, {"source_stream": STREAM, "source_event_id": event_id, "attempts": str(attempts), "error_type": type(exc).__name__, "event": json.dumps(fields, sort_keys=True)})
            client.xack(STREAM, GROUP, event_id)
            client.delete(attempts_key)
        else:
            time.sleep(min(attempts, 5))
        return
    client.xack(STREAM, GROUP, event_id)
    client.delete(attempts_key)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Consume VisionFlow publishing events")
    parser.add_argument("--once", action="store_true", help="Run one bounded pass for GitHub Actions")
    arguments = parser.parse_args()
    main(once=arguments.once)
