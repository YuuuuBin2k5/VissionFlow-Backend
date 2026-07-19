# VisionFlow PostgreSQL Cutover Plan

Status: Draft

Author: Automated assistant (please add reviewer names before merge)

Overview
--------
This document describes a safe, auditable, reversible plan to cut over VisionFlow from the legacy MySQL runtime stores to the canonical PostgreSQL Control Plane (Neon). The approach follows the existing ADR and assessment: preserve MySQL for the migration window, migrate aggregates in slices, and ensure all writes become mediated by the Control Plane API.

Goals
-----
- Move authoritative workflow & business state to Neon PostgreSQL.
- Avoid data loss, race conditions, and breaking the outbox/transactional guarantees.
- Provide verification and rollback paths.

Prerequisites
-------------
- Operational Neon PostgreSQL instance and migration access (Alembic). Ensure `MIGRATION_DATABASE_URL` and `DATABASE_URL` are available.
- Read-only access to legacy MySQL instance used by `orchestrator`/`worker`.
- CI runners and a staging environment that mirrors production configuration (Control Plane + worker adapters).
- Backups: take logical dumps/snapshots of MySQL and Postgres before each major step.
- Runbook owner and an agreed maintenance window for the final cutover.

High-level Phases
-----------------
1. Discovery & Inventory
   - Verify all MySQL tables and identify aggregate boundaries to migrate (video_pipeline_jobs, process_realtime_logs, publish_targets, agent_prompt_templates, etc.).
   - Produce row counts and sample payloads for each aggregate.
   - Ensure Control Plane schemas exist and migrations are up-to-date (`alembic upgrade head`).

2. Adapter Implementation (Worker → Control Plane API)
   - Stop direct MySQL writes in worker/orchestrator code paths where possible. Replace with an adapter that issues typed HTTP commands to the Control Plane API.
   - Implement eventual-consistency adapters: when the worker would previously call `video_job_repository.update_state()`, it should instead call `ControlPlaneClient.submit_command('workflow_step.update', payload)` and wait for acknowledgement.
   - Add feature flags to toggle adapter behavior (legacy-write vs control-plane-api).
   - Unit + contract tests: add tests for the adapter, including idempotency keys and error handling.

3. Migration Tooling & Dry Runs
   - Create a migration script (`scripts/migrate_mysql_to_postgres.py`) with a dry-run mode that maps MySQL rows to PostgreSQL aggregates.
   - For each aggregate slice, run dry-run with `--limit` and produce a reconciliation report (rows mapped, fields defaulted, errors).
   - Store reconciliation reports in the repo under `migration-reports/` for audit.

4. Dual-Read Verification
   - Deploy read adapters that read the new PostgreSQL state but keep MySQL as the write target.
   - Run smoke tests and integration tests that read from PostgreSQL and compare expected results with MySQL-derived expectations.

5. Final Cutover (Maintenance Window)
   - Pause intake channels and schedulers.
   - Drain inflight work: let workers finish current tasks.
   - Run final delta migration using the migration script.
   - Enable Control Plane API as the write target; flip feature flags.
   - Unpause intake.
   - Run post-cutover verification (row counts, sample checks, end-to-end smoke tests).

6. Retirement
   - After a stabilization window and reconciliation checks, deprecate the MySQL writer and schedule the MySQL instance for archival.

Verification & Assertions
-------------------------
- Row counts per aggregate must match expected counts (allowable delta must be documented per-aggregate).
- Random sample payloads (N=100) must map to valid PostgreSQL aggregates (no nulls in required fields).
- Transactional outbox events emitted by Control Plane must match expected event types.
- End-to-end workflow: create → render → QA → approval → publish (manual/smoke) must pass on staging before production switch.

Rollback Plan
-------------
- If verification fails, revert feature flag to legacy writer, pause new writes, and restore MySQL writes.
- Use the migration reports to identify rows causing mapping errors; fix mapping scripts and re-run delta.
- All irreversible production changes must be logged with trace ids to enable operator replay.

Operational Commands
--------------------
-- Verify Postgres migrations (run from `services/control-plane`):
```bash
export MIGRATION_DATABASE_URL="${NEON_MIGRATION_URL}"
cd VisionFlow_Bakend/services/control-plane
alembic upgrade head
```

-- Example read verification on MySQL (worker DB):
```sql
SELECT COUNT(*) FROM video_pipeline_jobs;
SELECT id, pipeline_state, error_log_trace FROM video_pipeline_jobs ORDER BY updated_at DESC LIMIT 20;
```

-- Example Postgres verification (Control Plane):
```sql
SELECT COUNT(*) FROM workflow_runs;
SELECT id, state, organization_id FROM workflow_runs ORDER BY created_at DESC LIMIT 20;
```

Migration Reporting
-------------------
- Each migration run must produce a JSON report with: `aggregate`, `source_row_count`, `mapped_row_count`, `errors` (array), `timestamp`, `commit_tag`.
- Store reports in `migration-reports/YYYYMMDD-HHMMSS-aggregate.json`.

Testing Requirements
--------------------
- Unit tests for adapter rewrites, with fakes for Control Plane API. CI must assert adapter coverage.
- Integration tests: disposable MySQL + Postgres containers covering key flows (create run, mark step complete, generate outbox event).
- Non-functional tests: run smoke rendering in staging with sample briefs.

PR & Commit Standards
---------------------
- Branch naming: `cutover/<aggregate>-to-postgres` or `docs/cutover-postgres` for documentation-only changes.
- Commit message pattern:
  - Short summary (50 chars max)
  - Blank line
  - Detailed description of changes, test instructions, and rollbacks.

Example commit message:
```
docs(cutover): add PostgreSQL cutover plan and migration script

Add a comprehensive cutover plan describing phased migration from MySQL to Neon Postgres.
- Include discovery, adapter implementation, migration dry-run, final cutover, verification and rollback.
- Add a safe migration script template in `scripts/` to perform dry-runs and reconciliation.

Testing: run unit tests for adapters, run `scripts/migrate_mysql_to_postgres.py --dry-run --limit 100`.
```

Appendix: roles & contacts
--------------------------
- Runbook owner: @owner (replace with actual GitHub handle)
- DBA / Neon admin: @dba
- On-call: ops rotation contact
