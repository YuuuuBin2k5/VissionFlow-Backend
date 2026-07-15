from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.publish_outbox import PendingOutboxEvent
from app.infrastructure.models import OutboxEvent


class SqlAlchemyOutboxRepository:
    """Claims events with PostgreSQL row locks; safe for multiple relay replicas."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def claim_pending(self, limit: int) -> list[PendingOutboxEvent]:
        rows = list(
            self._session.scalars(
                select(OutboxEvent)
                .where(OutboxEvent.published_at.is_(None))
                .order_by(OutboxEvent.created_at, OutboxEvent.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        return [
            PendingOutboxEvent(
                id=row.id,
                aggregate_type=row.aggregate_type,
                aggregate_id=row.aggregate_id,
                event_type=row.event_type,
                payload=row.payload,
                trace_id=row.trace_id,
            )
            for row in rows
        ]

    def mark_published(self, event_id: uuid.UUID) -> None:
        row = self._session.get(OutboxEvent, event_id)
        if row is None or row.published_at is not None:
            return
        row.published_at = datetime.now(timezone.utc)
        # The relay commits the complete claimed batch after all Redis writes.
        # This keeps its row locks until the batch finishes and avoids another
        # replica claiming a later event halfway through this pass.
        self._session.flush()
