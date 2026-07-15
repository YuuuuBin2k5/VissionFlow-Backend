# VisionFlow Control Plane

The Control Plane is the only production writer for VisionFlow PostgreSQL workflow state. It exposes the public API, authorization/policy boundary, PostgreSQL transaction boundary and transactional outbox.

## Local setup

1. Copy .env.example to .env.
2. Install dependencies with python -m pip install -r requirements.txt.
3. Run python -m alembic upgrade head.
4. Run python -m uvicorn app.main:app --reload --port 8000.

DATABASE_URL must be PostgreSQL. Runtime uses Neon's pooled URL. Alembic requires MIGRATION_DATABASE_URL, which points to Neon's direct endpoint. MySQL URLs are intentionally rejected.

## Current foundation

- PostgreSQL-only configuration guard.
- Initial Alembic schema for the V1 workflow, prompt, media, approval and outbox aggregates.
- Organization memberships and least-privilege authorization policy for the operator console.
- Pure workflow-state policy with unit tests.
- /health and database-backed /ready endpoints.
- Idempotent short-form creation use case and PostgreSQL repository.
- Transactional `visionflow.workflow_run.opened.v1` outbox event for every new run.
- Bounded PostgreSQL-to-Redis Streams relay with PostgreSQL `SKIP LOCKED` claims and stable event ids for consumer deduplication.
- Serialized worker/operator state progression with row-level locks, optimistic state checks and idempotent replay behavior.
- OIDC bearer-token boundary and organization membership authorization for browser API writes.
- Explicit one-time PostgreSQL bootstrap command for the initial administrator.

## Local verification

Run `..\\..\\scripts\\verify-control-plane.ps1` from the repository root. Add `-InstallDependencies` for a clean environment; it installs development quality tools and runs the same syntax, lint and unit checks as CI.

## First protected API contract

`POST /api/v1/workflows/short-form` requires an OIDC Bearer access token, a caller membership with `workflow:create`, and an `Idempotency-Key` header. The server does not auto-provision OIDC subjects: an administrator must be created in the PostgreSQL bootstrap process before browser access is enabled.

## Bootstrap the first administrator

After Alembic has completed and the OIDC provider is configured, run this one-time command from a secure operator environment with `MIGRATION_DATABASE_URL` set. It deliberately requires `--confirm`; it never runs in the web service.

```powershell
python scripts/bootstrap_admin.py `
  --organization-slug visionflow-studio `
  --organization-name "VisionFlow Studio" `
  --identity-subject "exact-oidc-sub-claim" `
  --email "admin@example.com" `
  --confirm
```

The command is idempotent for an existing membership. It refuses to silently change an existing role; use `--promote-existing` only after an explicit access review. For Telegram Intake or Intelligence Worker OIDC client subjects, use `--role service`; this role can create/view/advance workflows but cannot manage prompts or publish.

## Relay committed events to workers

Run the relay as a separate Render worker process, using the same `DATABASE_URL` and a TLS `REDIS_URL`:

```powershell
python scripts/relay_outbox.py --limit 50
```

The production image includes `scripts/relay_outbox.py`. Configure the Render
worker start command as `python scripts/relay_outbox.py --limit 50`; do not run
this command inside the web-service process.

The relay is at-least-once: a process crash after Redis accepts an event but before PostgreSQL records it may redeliver it. Worker consumers must persist and deduplicate the `event_id` field before starting a side effect.
