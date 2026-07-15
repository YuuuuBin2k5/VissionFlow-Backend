# VisionFlow — Delivery Plan

**Goal:** release a production-grade, short-form AI Video Operating System through staging before production, without blocking the later long-form product.

All phases must comply with [VisionFlow Engineering Standards](VISIONFLOW_ENGINEERING_STANDARDS.md). A feature is not complete merely because its UI works.

> Execution detail is maintained in the [Master Execution Playbook](VISIONFLOW_MASTER_EXECUTION_PLAYBOOK.md), [Agent Skills Catalog](VISIONFLOW_AGENT_SKILLS_CATALOG.md) and [Acceptance/Operations Runbook](VISIONFLOW_ACCEPTANCE_AND_OPERATIONS_RUNBOOK.md). Use those documents when assigning or accepting work; this file remains the concise roadmap.

## Delivery rules

- The primary repository becomes **VisionFlow**. `AgentTiktok` is the current working name until the dirty worktree is reviewed and committed; do not rename the remote/repository folder during active development.
- V1 ships on-demand short-form only. Long-form compatibility is delivered as formats, timeline schema and worker contracts—not inactive UI mockups.
- V1 does not include campaign batches, 30-day generation, automatic calendars, auto-publish, multi-account bot fleet controls or advanced analytics. These are explicitly deferred, not partially implemented.
- Staging is mandatory. No direct local-to-production deployment.
- Render hosts Studio, Control Plane, Intake and non-GPU workers. Neon hosts PostgreSQL. Render Key Value hosts Redis. Cloudflare R2 stores all durable media. GPU rendering is selected through an adapter and can start with one managed runner.
- Human approval remains mandatory before any production publish operation.

## Phased implementation

| Phase | Outcome | Main work | Exit evidence |
| --- | --- | --- | --- |
| 0. Repository consolidation | One source tree and one ownership map | Bring Cockpit code into VisionFlow; mark legacy modules; add architecture decision records | Clean build from a fresh checkout, no duplicated source of truth |
| 1. Engineering foundation | Repeatable local and CI verification | Root workspace commands, GitHub Actions, dependency/security checks, protected environments | Local scripts and PR CI produce the same pass/fail result |
| 2. PostgreSQL foundation | Neon becomes the only write database | PostgreSQL-only local/staging/prod, SQLAlchemy/Alembic schema, repository ports, data export tools and staging reconciliation | Staging runs on Neon with verified V1 data; MySQL is no runtime dependency |
| 3. Workflow backbone | Durable cross-language jobs | State machine, outbox, Redis Streams, retry/DLQ, service identities and progress events | Worker restart/resume and idempotency integration tests pass |
| 4. Short-form vertical slice | End-to-end creation in Studio | One brief, prompt registry, assets, script, timeline, render request, QA, review and signed preview | One staging short video completes without Telegram or manual DB edits |
| 5. Manual publishing | Governed delivery loop | Platform adapter, approval ledger, token encryption and manual dispatch | A test-channel publication is fully auditable and reversible before dispatch |
| 6. Production readiness | Safe staging → production release | R2 lifecycle, OTel dashboards, alerts, backup/restore drills, load/security review and runbooks | Production checklist signed off and synthetic smoke workflow succeeds |
| 7. Long-form enablement | Long-form on the same system | New format profile, multi-act planner, chapter timeline and larger render profile | No control-plane/database redesign required |

## Phase detail

### Phase 0 — Consolidate without losing work

1. Audit all uncommitted AgentTiktok changes and make reviewable commits before moving directories.
2. Create the target layout:

   ```text
   visionflow/
     apps/studio/                 # React cockpit
     services/control-plane/      # FastAPI
     services/intake/             # Telegram adapter
     workers/intelligence/        # planning/research
     workers/media/               # CPU/GPU rendering
     packages/contracts/          # OpenAPI/event schemas
     infra/render/                # Render blueprint and runbooks
     scripts/                     # local verification and migration tools
     docs/
   ```

3. Preserve functional behavior during moves; each move is a separate commit and must be buildable.
4. Retire duplicated MySQL schema ownership after the PostgreSQL cutover, not before.

### Phase 1 — CI/CD and local developer experience

Deliver these local commands for Windows PowerShell and POSIX shells:

| Command | Purpose |
| --- | --- |
| `verify` | Typecheck, lint, unit tests, Python syntax/type tests and frontend build |
| `verify:contracts` | OpenAPI/event-schema compatibility tests |
| `verify:e2e` | Headless Studio login, create short project, approval-gate workflow using staging-safe providers |
| `db:migrate` | Run Alembic only through `MIGRATION_DATABASE_URL` |
| `db:check` | Verify schema head, connection and migration drift |
| `smoke:staging` | Readiness, R2 signed URL and synthetic workflow checks without publishing |

GitHub Actions pipelines:

- **Pull request:** secret scan, dependency review, TypeScript/Python verification, API contract diff, migration upgrade on an ephemeral database and browser E2E with mock media provider.
- **Main:** build immutable images, deploy staging, run migration job once, run staging smoke tests and publish deployment summary.
- **Release tag:** require production environment approval, verify backup, deploy forward-only migration, deploy services, execute synthetic run, annotate release.

### Phase 2 — Neon PostgreSQL migration

1. Define Alembic migrations from the canonical VisionFlow model; use `jsonb`, `uuid`, `timestamptz`, constraints and indexes based on workflow access paths.
2. Implement repository interfaces used by application services, then PostgreSQL adapters. No router, Telegram handler or worker may contain connection/SQL details.
3. Create repeatable migration commands: export MySQL, transform, load staging, compare row counts/state distributions, validate R2 object manifests, and report failures.
4. Run a staging rehearsal before the production maintenance window. The production migration is forward-only; application rollback must tolerate the latest schema.

### Phase 3 — Workflow and worker refactor

1. Add the state machine and transition policy in the control plane.
2. Write commands to PostgreSQL outbox in the same transaction as state changes.
3. Publish through Event Relay to Redis Streams; workers use consumer groups, emit a result command and do not directly mutate database tables.
4. Enforce idempotency at API, producer and worker levels. Add timeout, cancellation, bounded retry and dead-letter replay tooling.
5. Replace Node child-process rendering and direct worker SQL with service contracts. Telegram becomes a thin adapter to the Control Plane.

### Phase 4 — Short-form product completion

The Studio workflow has five product surfaces:

1. **Create:** brief, brand kit, target channel, format and content rights.
2. **Plan:** script/storyboard/timeline preview, pinned prompt versions and AI output review.
3. **Produce:** assets, voice, captions, render progress and retryable diagnostics.
4. **Review:** QA report, signed preview, reviewer decision and audit timeline.
5. **Publish:** explicit reviewer dispatch, delivery status and provider error explanation. Scheduling and analytics feedback are post-V1.

No screen may invent state. Every status, metric, preview and action calls a production API contract.

### Phase 5 and 6 — delivery confidence

- Use a dedicated staging social account and an allow-listed non-production destination.
- Test failure paths: expired provider token, missing asset, worker crash, duplicate command, rejected QA, rejected approval and publish timeout.
- Run backup/restore and queue dead-letter replay exercises before production.
- Add runbooks for `render-stalled`, `publish-failed`, `provider-outage`, `Neon-unavailable`, `R2-upload-failed` and `credential-rotation`.

## Quality gates

| Gate | Required before staging | Required before production |
| --- | --- | --- |
| Type/unit/contract tests | Pass | Pass on release commit |
| Browser E2E | Critical paths pass | Staging smoke pass |
| Database migration | Upgrade/downgrade policy validated on disposable DB | Backup verified, forward migration rehearsed |
| Security | Secret scan, dependency review, scoped CI permissions | ASVS Level 2 checklist and admin MFA |
| Reliability | Worker retry/DLQ tests | Alert and restoration drill completed |
| Media | QA and signed-preview tests | Staging production-like render and review pass |
| Publishing | Mock adapter tests | Dedicated test-account delivery pass |

## First execution slice

The first code slice after this documentation is deliberately small and reversible:

1. Create the VisionFlow repository layout and root local verification scripts.
2. Add GitHub Actions PR/staging/release pipelines with pinned actions and no production secrets in logs.
3. Add Render blueprint and environment templates containing names only—no credentials.
4. Add the PostgreSQL/Alembic skeleton and migration-test harness before porting individual endpoints.

This order proves the delivery system before changing data or media behavior.

## Success metrics for V1

- 95% of accepted short-form runs reach a terminal state within the declared render SLA.
- 100% of renders record prompt version, asset provenance, QA result, reviewer decision and publish attempt.
- 0 duplicate external publications from retry or redeploy.
- 100% of Studio mutation requests are authenticated, authorized and auditable.
- Mean time to identify a failed workflow is under 10 minutes through correlated traces/logs/metrics.

## Research basis

- Render separates public web services from background workers and uses Redis-compatible Key Value for queues: [Render service types](https://render.com/docs/service-types).
- Neon documents a pooled connection endpoint for concurrent runtime traffic and a direct endpoint for schema migrations: [Neon pooling](https://neon.com/docs/connect/connection-pooling).
- R2 is S3-compatible and supports restricted, time-limited signed URLs: [R2 S3 API](https://developers.cloudflare.com/r2/get-started/s3/), [R2 presigned URLs](https://developers.cloudflare.com/r2/api/s3/presigned-urls/).
- GitHub recommends full commit-SHA pins for immutable Actions use: [GitHub secure use](https://docs.github.com/en/actions/reference/security/secure-use).
- OpenTelemetry supplies the standard trace/metric/log correlation model: [OpenTelemetry instrumentation](https://opentelemetry.io/docs/concepts/instrumentation/).
