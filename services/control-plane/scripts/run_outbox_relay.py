"""Continuously relay committed outbox events; intended for a Render worker."""
from __future__ import annotations

import time

from redis import Redis
from sqlalchemy.orm import Session

from app.application.publish_outbox import PublishOutbox
from app.infrastructure.database import get_engine
from app.infrastructure.outbox_repository import SqlAlchemyOutboxRepository
from app.infrastructure.redis_stream_publisher import RedisStreamEventPublisher, RedisStreamSettings


def main() -> None:
    settings = RedisStreamSettings.from_env()
    client = Redis.from_url(settings.url, decode_responses=True)
    engine = get_engine()
    backoff_secs = 2.0

    while True:
        try:
            with Session(engine) as session:
                count = PublishOutbox(
                    SqlAlchemyOutboxRepository(session),
                    RedisStreamEventPublisher(client, settings.stream),
                ).execute(limit=50)
                session.commit()

            if count == 0:
                time.sleep(backoff_secs)
                # Exponential backoff when idle up to max 12 seconds
                backoff_secs = min(backoff_secs * 1.5, 12.0)
            else:
                # Instant reset for real-time processing of consecutive events
                backoff_secs = 1.0
                time.sleep(0.1)
        except Exception as exc:
            time.sleep(5.0)
            backoff_secs = 3.0


if __name__ == "__main__":
    main()
