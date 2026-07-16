# VisionFlow Legacy Job Mapping Rollout Runbook

This document details the operational rollout, integrity constraints, and safety guidelines for the `legacy_job_id` and worker execution context mapping.

## 1. Migration Strategy and Alembic Chain Integrity

To resolve the 0-byte file regression of `0007_add_context_fields.py` from commit `b68f90c`, we reject any runtime monkeypatches in production. Instead, `0007_add_context_fields.py` is configured as a valid **historical no-op corrective migration**:

- **Down Revision**: `0006_command_receipts_hardened`
- **Revision ID**: `0007_add_context_fields`
- **DDL Execution**: None (`pass` in `upgrade`/`downgrade`).
- **Chain Security**: Allows `0008_worker_context_lookup` to chain natively.

All automated deployments and DB cutover operations will proceed using standard native Alembic tooling.

## 2. Shadow Control Plane Status

> [!WARNING]
> The **shadow/control_plane** capability and database dual-write features remain strictly **DISABLED** in all production configurations. No traffic should be routed through the new control plane endpoints outside local container validation.

## 3. Production Integration Pre-requisites

Before the legacy MySQL orchestrator is integrated with the PostgreSQL control plane in production, the following is **mandatory**:

- **MySQL Outbox Table & Daemon**: To guarantee mapping consistency, the orchestrator must write mapping tasks to a transactional outbox in MySQL, processed by a reliable publisher.
- **Durable Retries**: Any network calls from the legacy side to the new `RegisterLegacyJobMapping` route must utilize a durable background retry queue to prevent data loss.
- **Worker Client Resiliency**: Narration workers must fetch the context using their OIDC subject token and fail-closed if they receive a `404` or `409` from the Control Plane.

### Stream B activation boundary

`RequestLegacyJob` is intentionally an internal Control Plane use case in the
current slice. It atomically moves a `READY` workflow to `QUEUED`, records a
canonical `visionflow.legacy_job.requested.v1` outbox event, and uses the
existing outbox event UUID as `event_id`. It is not yet wired to a public
route, submit flow, or Redis consumer.

The event contains an immutable `intake` snapshot (title, brief, format
profile, timezone, input payload, and prompt manifest). A consumer must use
this snapshot; it must not infer work from identifiers or reach back into the
Control Plane database.

Before enabling it, deploy the isolated orchestrator consumer and its MySQL
transactional outbox. Configure a separate `VISIONFLOW_LEGACY_MAPPING_*`
client with only `workflow:legacy-mapping:register`; it must never share the
narration worker's credential or scope. This preserves the legacy Telegram
paths unchanged until their separate strangler milestone is approved.

## 4. Testing & Acceptance Disclaimer

> [!NOTE]
> The disposable PostgreSQL test suite (`scripts/test_postgres_disposable.py`) is designed solely for local regression verification. Passing these tests verifies code correctness and migration chain validity, but does **not** constitute deployed staging acceptance, load testing, or production release clearance.
