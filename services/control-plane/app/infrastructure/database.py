from __future__ import annotations

from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.config import Settings


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    settings = Settings.from_env()
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=3,
        max_overflow=3,
        pool_timeout=20,
        pool_recycle=300,
    )


def get_session():
    with Session(get_engine()) as session:
        yield session
