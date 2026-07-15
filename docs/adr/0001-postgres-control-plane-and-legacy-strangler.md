# ADR 0001: PostgreSQL Control Plane and Legacy Strangler Plan

## Status
Proposed

## Context
The VisionFlow system currently operates with a dual-database runtime topology:
1. **Neon PostgreSQL Database**: Initialized via Python Alembic migrations in `services/control-plane`. It contains 26 tables modeling versioned workflows, timelines, creative documents, and local credentials. It is hosted on Neon.
2. **Local/Production MySQL Database**: Accessed by the Node.js `orchestrator` (using Prisma Client) and the Python worker/FastAPI gateway (using raw PyMySQL connections). It handles flat `video_pipeline_jobs` and legacy channel campaigns.

A previous inventory incorrectly reported that there was no Alembic or SQLAlchemy setup. A deep-dive audit has shown that the Neon PostgreSQL schema aligns 100% with the Alembic models in `services/control-plane` (at revision `0004_composition_studio`).

Transitioning the legacy Node.js/worker database access directly to PostgreSQL by modifying the Prisma schema or running raw MySQL queries on Neon poses significant architectural risks, including breaking the outbox pattern, state machine integrity, and violating the principle of least privilege.

## Decision
1. **Canonical System of Record**: `services/control-plane` (using SQLAlchemy and Alembic) is established as the sole canonical owner and direct writer of the Neon PostgreSQL database.
2. **No Direct Cutover**: The Prisma schema and legacy MySQL tables will not be cut over directly to Neon PostgreSQL. No raw SQL schema auto-creation or Prisma migrations will be executed on Neon.
3. **Legacy Strangler Pattern**: The legacy components (`orchestrator`, `BackendAgent` gateway, and Python worker) will be progressively migrated to interact with the PostgreSQL state machine via the Control Plane's typed command APIs instead of making direct database writes.
4. **Intake Adapter Status**: The Telegram bot and schedulers are categorized as intake adapters only. They will submit intake events to the Control Plane rather than writing state rows.
5. **Phased Aggregate Migration**: Data migration from MySQL to PostgreSQL will be performed in slices per aggregate boundary (e.g., Prompt Template aggregate, Video Project aggregate, and Workflow Run aggregate) with explicit dry-runs and reconciliation checks.

## Consequences
- The legacy MySQL instance will remain active for current operations during the migration.
- Direct database writes in legacy components must be replaced with typed API commands targeting the Control Plane.
- All schema updates in the target system will be managed through Alembic migrations in `services/control-plane`.
- No runtime auto-creation of database tables or columns will occur in production.
- Clean separation of concerns will prevent race conditions and lock contentions between concurrent workers.
