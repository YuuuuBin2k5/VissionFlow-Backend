from __future__ import annotations

from functools import lru_cache
import logging

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.config import Settings


logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    import os
    settings = Settings.from_env()
    pool_size = int(os.getenv("VISIONFLOW_DB_POOL_SIZE", "20"))
    max_overflow = int(os.getenv("VISIONFLOW_DB_MAX_OVERFLOW", "20"))
    pool_timeout = int(os.getenv("VISIONFLOW_DB_POOL_TIMEOUT", "30"))
    pool_recycle = int(os.getenv("VISIONFLOW_DB_POOL_RECYCLE", "300"))
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout,
        pool_recycle=pool_recycle,
    )


def get_session():
    session = Session(get_engine())
    try:
        yield session
    finally:
        try:
            session.close()
        except Exception:
            # Cleanup must never replace the actual HTTP response/error. This
            # can happen when PostgreSQL drops an in-flight connection and
            # SQLAlchemy attempts a final ROLLBACK while closing the session.
            logger.exception("Database session cleanup failed")
