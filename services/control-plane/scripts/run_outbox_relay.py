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
    while True:
        with Session(get_engine()) as session:
            count = PublishOutbox(SqlAlchemyOutboxRepository(session), RedisStreamEventPublisher(client, settings.stream)).execute(limit=50)
            session.commit()
        if count == 0:
            time.sleep(1)


if __name__ == "__main__":
    main()
