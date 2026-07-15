from __future__ import annotations

import json
from dataclasses import dataclass

from redis import Redis

from app.application.publish_outbox import PendingOutboxEvent


@dataclass(frozen=True)
class RedisStreamSettings:
    url: str
    stream: str = "visionflow.workflow-events.v1"

    @classmethod
    def from_env(cls) -> "RedisStreamSettings":
        from os import getenv

        url = (getenv("REDIS_URL") or "").strip()
        if not url:
            raise ValueError("REDIS_URL must be configured for the outbox relay")
        if not url.startswith(("rediss://", "redis://localhost", "redis://127.0.0.1")):
            raise ValueError("REDIS_URL must use TLS outside local development")
        return cls(url=url, stream=(getenv("VISIONFLOW_EVENTS_STREAM") or cls.stream).strip())


class RedisStreamEventPublisher:
    def __init__(self, client: Redis, stream: str) -> None:
        self._client = client
        self._stream = stream

    def publish(self, event: PendingOutboxEvent) -> None:
        self._client.xadd(
            self._stream,
            {
                "event_id": str(event.id),
                "event_type": event.event_type,
                "aggregate_type": event.aggregate_type,
                "aggregate_id": str(event.aggregate_id),
                "trace_id": event.trace_id,
                "payload": json.dumps(event.payload, separators=(",", ":"), sort_keys=True),
            },
        )
