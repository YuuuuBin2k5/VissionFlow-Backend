"""VF-03.01b — Postgres Disposable Integration and Migration Chain Testing Script.

This script runs database integration tests and verifies the Alembic migration chain
(specifically the 0004 -> 0005 -> 0006 progression) in both upgrade and downgrade directions.
"""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

# Setup environment variables before imports
DB_URL = "postgresql+psycopg://postgres:postgres@localhost:5433/visionflow_test"
os.environ["DATABASE_URL"] = DB_URL
os.environ["MIGRATION_DATABASE_URL"] = DB_URL
os.environ["VISIONFLOW_ALLOW_INSECURE_DB"] = "true"

from alembic.config import Config
from alembic import command as alembic_command
from sqlalchemy import create_engine, text


def ensure_disposable_postgres() -> None:
    """Verifies that the disposable postgres docker container is running on 5433."""
    print("Checking docker container status...")
    try:
        res = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", "visionflow-disposable-postgres"],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip() == "true":
            print("Disposable PostgreSQL container is running.")
            return

        # If it exists but is stopped, start it
        print("Starting stopped disposable PostgreSQL container...")
        subprocess.run(["docker", "start", "visionflow-disposable-postgres"], check=True)
    except subprocess.SubprocessError:
        print("Warning: Failed to query docker. Trying to spin up container...")
        try:
            subprocess.run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    "visionflow-disposable-postgres",
                    "-p",
                    "5433:5432",
                    "-e",
                    "POSTGRES_PASSWORD=postgres",
                    "-e",
                    "POSTGRES_USER=postgres",
                    "-e",
                    "POSTGRES_DB=visionflow_test",
                    "postgres:15-alpine",
                ],
                check=True,
            )
            print("Successfully started disposable PostgreSQL container on port 5433.")
        except Exception as exc:
            print(f"Error: Docker is not available or failed to start container: {exc}")
            sys.exit(1)


def main() -> int:
    ensure_disposable_postgres()

    print("\n--- Phase 1: Database Setup and Initial Alembic Head Migration ---")
    engine = create_engine(DB_URL)
    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE;"))
        conn.execute(text("CREATE SCHEMA public;"))
        conn.commit()

    alembic_cfg = Config(str(SERVICE_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", DB_URL)

    print("Running migrations upgrade -> HEAD...")
    alembic_command.upgrade(alembic_cfg, "head")
    print("Migrations complete.")

    print("\n--- Phase 2: Running Database Integration Tests ---")
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Load integration/api tests
    suite.addTests(loader.loadTestsFromName("tests.test_narration_result_repository"))
    suite.addTests(loader.loadTestsFromName("tests.test_narration_result_api"))
    suite.addTests(loader.loadTestsFromName("tests.test_narration_auth_capability"))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if not result.wasSuccessful():
        print("Integration tests failed!")
        return 1

    print("\n--- Phase 3: Verifying Migration Downgrade & Re-Upgrade Chain (Base -> Head) ---")
    try:
        print("Downgrading all migrations to BASE...")
        alembic_command.downgrade(alembic_cfg, "base")
        print("Downgrade successful.")

        print("Upgrading all migrations back to HEAD...")
        alembic_command.upgrade(alembic_cfg, "head")
        print("Upgrade successful.")
    except Exception as exc:
        print(f"Migration rollback chain test failed: {exc}")
        return 1

    print("\nAll integration tests and migration rollback tests passed successfully! [OK]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
