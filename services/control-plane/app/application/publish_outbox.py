"""Transactional-outbox relay application boundary.

The relay provides at-least-once delivery.  Consumers must deduplicate on the
stable event id included in every published message.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PendingOutboxEvent:
    id: uuid.UUID
    aggregate_type: str
    aggregate_id: uuid.UUID
    event_type: str
    payload: dict[str, object]
    trace_id: str


class OutboxRepository(Protocol):
    def claim_pending(self, limit: int) -> list[PendingOutboxEvent]: ...

    def mark_published(self, event_id: uuid.UUID) -> None: ...


class EventPublisher(Protocol):
    def publish(self, event: PendingOutboxEvent) -> None: ...


class PublishOutbox:
    def __init__(self, repository: OutboxRepository, publisher: EventPublisher) -> None:
        self._repository = repository
        self._publisher = publisher

    def execute(self, *, limit: int = 50) -> int:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        published = 0
        for event in self._repository.claim_pending(limit):
            self._publisher.publish(event)
            self._repository.mark_published(event.id)
            published += 1
        return published
