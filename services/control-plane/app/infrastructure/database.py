from __future__ import annotations

from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.config import Settings


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
    with Session(get_engine()) as session:
        yield session
