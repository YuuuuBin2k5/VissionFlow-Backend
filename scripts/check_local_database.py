"""Minimal authenticated database preflight for the local render launcher."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, text


def main() -> None:
    backend_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(backend_root / "services" / "control-plane"))
    from app.core.config import Settings

    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")
    settings = Settings.from_env()
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    finally:
        engine.dispose()
    print("PostgreSQL Docker connection verified")


if __name__ == "__main__":
    main()
