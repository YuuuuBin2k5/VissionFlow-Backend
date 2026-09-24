from __future__ import annotations

import sys
import unittest
from pathlib import Path

import psycopg


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from wait_for_database import normalize_psycopg_url, wait_for_database  # noqa: E402


class DatabaseReadinessTests(unittest.TestCase):
    def test_normalizes_sqlalchemy_driver_scheme(self) -> None:
        self.assertEqual(
            "postgresql://app:secret@127.0.0.1:15432/visionflow",
            normalize_psycopg_url(
                "postgresql+psycopg://app:secret@127.0.0.1:15432/visionflow"
            ),
        )

    def test_retries_until_end_to_end_query_succeeds(self) -> None:
        attempts = []
        sleeps = []
        clock = [0.0]

        def connector(_url: str) -> None:
            attempts.append(1)
            if len(attempts) < 3:
                raise psycopg.OperationalError("tunnel warming up")

        def sleeper(seconds: float) -> None:
            sleeps.append(seconds)
            clock[0] += seconds

        result = wait_for_database(
            "postgresql://app:secret@localhost/db",
            timeout_seconds=30,
            connector=connector,
            monotonic=lambda: clock[0],
            sleeper=sleeper,
        )
        self.assertEqual(result, 3)
        self.assertEqual(sleeps, [1.0, 2.0])

    def test_times_out_instead_of_starting_migrations_early(self) -> None:
        clock = [0.0]

        def connector(_url: str) -> None:
            raise psycopg.OperationalError("database offline")

        def sleeper(seconds: float) -> None:
            clock[0] += seconds

        with self.assertRaisesRegex(TimeoutError, "did not become ready"):
            wait_for_database(
                "postgresql://app:secret@localhost/db",
                timeout_seconds=2,
                connector=connector,
                monotonic=lambda: clock[0],
                sleeper=sleeper,
            )


if __name__ == "__main__":
    unittest.main()
