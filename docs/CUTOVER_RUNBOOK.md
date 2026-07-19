# VisionFlow PostgreSQL Cutover Runbook

Status: Operational runbook (companion to `POSTGRES_CUTOVER_PLAN.md`). This is an actionable checklist for operators, DBAs and on-call engineers executing the cutover.

Preconditions
- Confirm approved maintenance window.
- Notify stakeholders (Slack/Email) and ensure on-call DBA and runbook owner are present.
- Ensure recent logical backups exist for MySQL and Neon.
- Ensure `MIGRATION_SAFETY_TOKEN` is provisioned in CI and operator's environment.

Checklist (Step-by-step)

1) Discovery & Snapshot
   - Run on MySQL (read-only):
     ```sql
     SELECT COUNT(*) FROM video_pipeline_jobs;
     SELECT COUNT(*) FROM process_realtime_logs;
     ```
   - Save outputs to `migration-reports/` with timestamp.
   - Take MySQL dump:
     ```bash
     mysqldump -h $MYSQL_HOST -u $MYSQL_USER -p $MYSQL_DATABASE > /tmp/mysql-dump-$STAMP.sql
     ```
   - Take Postgres snapshot (Neon): use provider snapshot or pg_dump.

2) Adapter Toggle (Feature Flag Preparation)
   - Ensure worker/orchestrator has feature flag `CONTROL_PLANE_WRITE` default `false`.
   - Prepare environment variables for test toggles.

3) Dry-run migration (staging)
   - Run mapping dry-run for sample data:
     ```bash
     cd VisionFlow_Bakend
     python scripts/migrate_mysql_to_postgres.py --dry-run --limit 200
     ```
   - Inspect `migration-reports/*` for errors.

4) Dual-read verification
   - Deploy a staging instance where reads come from Postgres but writes still go to MySQL.
   - Execute an end-to-end smoke scenario and compare outputs.

5) Final Cutover (Maintenance Window)
   - Pause intake channels: stop Telegram bots & schedulers.
   - Wait for worker queues to drain (monitor `video_pipeline_jobs` state and `queue depth`).
   - Run final delta migration with safety token (operator runs):
     ```bash
     export MIGRATION_SAFETY_TOKEN="${SECRET_TOKEN_FROM_VAULT}"
     python scripts/migrate_mysql_to_postgres.py --apply --safety-token "$MIGRATION_SAFETY_TOKEN"
     ```
   - Verify row counts and sample payloads.
   - Toggle feature flag `CONTROL_PLANE_WRITE=true` (or update config) to point writers to Control Plane API.
   - Unpause intake channels.

6) Post-cutover verification
   - Run end-to-end smoke tests (create→render→qa→approve→publish on staging). Ensure no failures.
   - Audit outbox events and ensure expected events were emitted.

Rollback steps (if verification fails)
- Flip feature flag back to `false`.
- Re-enable legacy writers.
- Investigate `migration-reports` for failing rows; re-run mapping after fixes.

Contacts & Escalation
- Runbook owner: @owner
- DBA: @dba
- SRE: @sre-oncall

Notes
- Never run `--apply` without an approved safety token and a maintenance window.
- All steps must be executed with trace ids logged for operator replay and audit.
