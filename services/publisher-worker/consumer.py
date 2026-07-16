"""Redis Streams consumer for committed VisionFlow PUBLISHING transitions."""
from __future__ import annotations

import json
import os
import socket
import time

from redis import Redis

from main import execute


STREAM = os.getenv("VISIONFLOW_EVENTS_STREAM", "visionflow.workflow-events.v1")
GROUP = os.getenv("VISIONFLOW_PUBLISHER_CONSUMER_GROUP", "visionflow-publisher-v1")
CONSUMER = os.getenv("VISIONFLOW_PUBLISHER_CONSUMER_NAME", socket.gethostname())


def _redis() -> Redis:
    url = (os.getenv("REDIS_URL") or "").strip()
    if not url:
        raise ValueError("REDIS_URL is required")
    return Redis.from_url(url, decode_responses=True)


def main() -> None:
    client = _redis()
    try:
        client.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
    except Exception as exc:
        if "BUSYGROUP" not in str(exc):
            raise
    while True:
        messages = client.xreadgroup(GROUP, CONSUMER, {STREAM: ">"}, count=1, block=5000)
        for _, events in messages:
            for event_id, fields in events:
                try:
                    _handle(fields)
                except Exception:
                    # Do not ACK transient failures; Redis PEL preserves the event for recovery.
                    time.sleep(2)
                    continue
                client.xack(STREAM, GROUP, event_id)


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


if __name__ == "__main__":
    main()
