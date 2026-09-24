"""Wait until PostgreSQL is reachable through the configured startup tunnel."""
from __future__ import annotations

import argparse
import os
import time
from collections.abc import Callable

import psycopg


def normalize_psycopg_url(value: str) -> str:
    normalized = value.strip()
    for scheme in ("postgresql+psycopg://", "postgresql+psycopg2://"):
        if normalized.startswith(scheme):
            return "postgresql://" + normalized[len(scheme):]
    return normalized


def connect_once(database_url: str) -> None:
    with psycopg.connect(normalize_psycopg_url(database_url), connect_timeout=5) as connection:
        connection.execute("SELECT 1")


def wait_for_database(
    database_url: str,
    *,
    timeout_seconds: float,
    connector: Callable[[str], None] = connect_once,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> int:
    if not database_url.strip():
        raise ValueError("Database URL is empty")
    if timeout_seconds <= 0:
        raise ValueError("Database startup timeout must be positive")

    deadline = monotonic() + timeout_seconds
    attempt = 0
    while True:
        attempt += 1
        try:
            connector(database_url)
            return attempt
        except (OSError, psycopg.Error):
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"PostgreSQL did not become ready within {timeout_seconds:g} seconds"
                ) from None
            delay = min(10.0, float(2 ** min(attempt - 1, 3)), remaining)
            print(
                f"PostgreSQL is not ready (attempt {attempt}); retrying in {delay:g}s...",
                flush=True,
            )
            sleeper(delay)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url-env", default="MIGRATION_DATABASE_URL")
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()
    database_url = os.getenv(args.url_env, "")
    attempts = wait_for_database(database_url, timeout_seconds=args.timeout)
    print(f"PostgreSQL readiness verified after {attempts} attempt(s).", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
