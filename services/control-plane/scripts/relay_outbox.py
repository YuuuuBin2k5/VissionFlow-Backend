"""Run one bounded VisionFlow PostgreSQL-to-Redis outbox relay pass."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from redis import Redis

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.application.publish_outbox import PublishOutbox  # noqa: E402
from app.infrastructure.database import get_engine  # noqa: E402
from app.infrastructure.outbox_repository import SqlAlchemyOutboxRepository  # noqa: E402
from app.infrastructure.redis_stream_publisher import (  # noqa: E402
    RedisStreamEventPublisher,
    RedisStreamSettings,
)
from sqlalchemy.orm import Session  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Relay committed VisionFlow outbox events to Redis Streams")
    parser.add_argument("--limit", type=int, default=50)
    arguments = parser.parse_args()
    redis_settings = RedisStreamSettings.from_env()
    with Session(get_engine()) as session:
        count = PublishOutbox(
            SqlAlchemyOutboxRepository(session),
            RedisStreamEventPublisher(Redis.from_url(redis_settings.url, decode_responses=True), redis_settings.stream),
        ).execute(limit=arguments.limit)
        session.commit()
    print(f"Published {count} VisionFlow outbox event(s) to {redis_settings.stream}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
