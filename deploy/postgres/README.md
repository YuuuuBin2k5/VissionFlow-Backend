# VisionFlow self-hosted PostgreSQL

This stack is the PostgreSQL system of record for a personal, always-on PC.
It does not replace the repository's legacy MySQL stack.

For the complete Windows PC + Tailscale + Render cutover procedure, follow
[`TAILSCALE_RENDER_RUNBOOK.md`](TAILSCALE_RENDER_RUNBOOK.md).

`schema.sql` is the consolidated, PostgreSQL-compatible schema generated from
the complete Alembic chain through revision `0022_channel_learning_metrics`.
Alembic remains the source of truth; regenerate this file after every migration
instead of editing it by hand.

## Required host setup

1. Keep the PC awake and enable BIOS power-on after AC loss.
2. Install Docker Desktop and Tailscale; enable Tailscale unattended mode.
3. Do not forward PostgreSQL port 5432 on the home router.
4. Restrict Windows Firewall and the Tailscale grant so only the tagged Render
   node can reach this host on TCP 5432.
5. Copy `.env.example` to `.env`, generate three distinct random passwords, and
   use absolute paths on an SSD for data and backups. Set
   `VISIONFLOW_POSTGRES_BIND_IP=127.0.0.1` and local port `55432`. On Windows,
   expose tailnet TCP 5432 with `tailscale serve --bg --tcp=5432
   tcp://127.0.0.1:55432`. Never use `0.0.0.0`.

## Start and inspect

```powershell
docker compose --env-file deploy/postgres/.env -f deploy/postgres/compose.yaml config
docker compose --env-file deploy/postgres/.env -f deploy/postgres/compose.yaml up -d
docker compose --env-file deploy/postgres/.env -f deploy/postgres/compose.yaml ps
docker exec visionflow-postgres pg_isready -U postgres -d visionflow
```

The init script creates `visionflow_app` for runtime DML and
`visionflow_migrator` for Alembic DDL. It runs only when the data directory is
empty. Changing `.env` later does not rotate existing PostgreSQL role passwords.

## Migrate

Run Alembic from a trusted operator shell. For a local migration connection,
set `VISIONFLOW_ALLOW_INSECURE_DB=true` only in that shell and point
`MIGRATION_DATABASE_URL` at `127.0.0.1`. Never set this compatibility flag on
Render.

## Back up and restore

```powershell
./deploy/postgres/backup.ps1
./deploy/postgres/restore.ps1 -BackupFile D:/VisionFlowServer/postgres/backups/visionflow-YYYY-MM-DD-HHmmss.dump
```

Copy backups to a second device or encrypted cloud storage. Test a restore at
least monthly; a dump that has never been restored is not a verified backup.
