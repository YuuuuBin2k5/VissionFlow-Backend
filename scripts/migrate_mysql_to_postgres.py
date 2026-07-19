"""
Safe migration tool skeleton: migrate_mysql_to_postgres.py

Usage (dry-run):
  python scripts/migrate_mysql_to_postgres.py --dry-run --limit 100

This script is a carefully constrained migration helper. It implements dry-run mapping
from the legacy MySQL aggregates into PostgreSQL Control Plane aggregates.

IMPORTANT: This script is a template and must be reviewed by a DBA and runbook owner
before executing in production. By default it operates in dry-run mode and never
writes to the destination unless `--apply` is provided and a safety token matches.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import logging
from typing import Any, Dict

try:
    import pymysql
except Exception:
    pymysql = None

try:
    import psycopg
except Exception:
    psycopg = None

LOGGER = logging.getLogger("migrate_mysql_to_postgres")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def get_mysql_conn():
    if pymysql is None:
        LOGGER.error("pymysql not installed. Install with pip install pymysql")
        sys.exit(1)
    url = os.getenv("LEGACY_MYSQL_URL") or os.getenv("DATABASE_URL")
    if not url:
        LOGGER.error("No LEGACY_MYSQL_URL or DATABASE_URL environment variable set")
        sys.exit(1)
    # Simple parser: expect mysql://user:pass@host:port/db
    return pymysql.connect(host=os.getenv("MYSQL_HOST", "127.0.0.1"),
                           user=os.getenv("MYSQL_USER", "root"),
                           password=os.getenv("MYSQL_PASSWORD", ""),
                           database=os.getenv("MYSQL_DATABASE", "tiktok_agent_automation_db"),
                           cursorclass=pymysql.cursors.DictCursor)


def get_postgres_conn():
    if psycopg is None:
        LOGGER.error("psycopg not installed. Install with pip install psycopg[binary]")
        sys.exit(1)
    pg_url = os.getenv("NEON_DATABASE_URL") or os.getenv("MIGRATION_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not pg_url:
        LOGGER.error("No NEON_DATABASE_URL/MIGRATION_DATABASE_URL/DATABASE_URL set for Postgres destination")
        sys.exit(1)
    return psycopg.connect(pg_url)


def map_video_pipeline_job_to_workflow_run(row: Dict[str, Any]) -> Dict[str, Any]:
    """Map legacy `video_pipeline_jobs` row to `workflow_runs` + initial step payload.
    This mapping must be reviewed and extended per aggregate. For now we produce a
    minimal mapping used for verification reports.
    """
    mapped = {
        "legacy_id": row.get("id"),
        "organization_id": row.get("organization_id") or None,
        "state": row.get("pipeline_state") or "unknown",
        "metadata": {
            "legacy_payload": row,
        },
    }
    return mapped


def run_dry_run(limit: int = 100):
    LOGGER.info("Starting dry-run migration (limit=%s)", limit)
    conn = get_mysql_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM video_pipeline_jobs ORDER BY updated_at DESC LIMIT %s", (limit,))
        rows = cur.fetchall()

    report = {"aggregate": "video_pipeline_jobs", "source_row_count": len(rows), "mapped_row_count": 0, "errors": []}
    mapped = []
    for r in rows:
        try:
            m = map_video_pipeline_job_to_workflow_run(r)
            mapped.append(m)
        except Exception as e:
            report["errors"].append({"id": r.get("id"), "error": str(e)})

    report["mapped_row_count"] = len(mapped)
    ts = __import__("datetime").datetime.utcnow().isoformat() + "Z"
    report["timestamp"] = ts
    print(json.dumps(report, indent=2))
    # write per-run report
    os.makedirs("migration-reports", exist_ok=True)
    fname = f"migration-reports/{ts.replace(':', '-')}-{report['aggregate']}.json"
    with open(fname, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    LOGGER.info("Dry-run report written to %s", fname)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Safe migration helper: MySQL -> Postgres (dry-run first)")
    parser.add_argument("--dry-run", action="store_true", default=False, help="Do not write to destination; only produce mapping reports")
    parser.add_argument("--limit", type=int, default=100, help="Limit rows to sample for dry-run")
    parser.add_argument("--apply", action="store_true", help="Apply mapped rows to destination (REQUIRES SAFETY_TOKEN) ")
    parser.add_argument("--safety-token", type=str, default=None, help="Safety token required to apply changes")
    args = parser.parse_args(argv)

    if args.dry_run:
        run_dry_run(limit=args.limit)
        return

    # apply mode (dangerous): additional safety checks
    safety_env = os.getenv("MIGRATION_SAFETY_TOKEN")
    if not args.apply or not args.safety_token or args.safety_token != safety_env:
        LOGGER.error("Apply mode requires --apply and --safety-token that matches MIGRATION_SAFETY_TOKEN")
        parser.print_help()
        sys.exit(2)

    LOGGER.info("Apply mode requested. Connecting to source and destination.")
    # Implementation placeholder: select rows, transform, insert into Postgres within controlled transaction
    # DO NOT RUN until DBA and runbook owner approve the mapping and testing reports.


if __name__ == "__main__":
    main()
