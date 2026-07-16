# Narration Handoff Operations Guide & Runbook

This document details the configuration, operations, and diagnostic procedures for the staged rollout of the PostgreSQL-based Control Plane narration handoff.

---

## 1. Environment Configurations

Configure the following environment variables on the worker to manage rollout staging.

### Environment Variable Reference

| Variable Name | Allowed Values | Default | Description |
| --- | --- | --- | --- |
| `VISIONFLOW_NARRATION_HANDOFF_MODE` | `legacy`, `shadow`, `control_plane` | `legacy` | Rollout mode for LLM script/narration saving (see Modes below). |
| `APP_ENV` | `development`, `staging`, `production` | `development` | Deployment environment name. Controls safety guards. |
| `VISIONFLOW_ORGANIZATION_ID` | Valid UUID string | None | Authoritative organization ID. Required for `shadow` & `control_plane`. |
| `VISIONFLOW_CONTROL_PLANE_URL` | Valid HTTP/HTTPS URL | `http://localhost:8000/api/v1` | URL prefix of the Control Plane API. |

### Handoff Rollout Modes

1.  **`legacy`**: Only writes narration scripts to the legacy MySQL database. The Control Plane path is completely skipped.
2.  **`shadow`**: (Recommended for Staging) Writes to MySQL (primary source-of-truth) and also sends a shadow write request to the PostgreSQL Control Plane via client credentials. Compares results and logs a structured comparison report.
3.  **`control_plane`**: Only writes narration results to the Control Plane PostgreSQL database. Skip legacy MySQL writes. **Note: Prohibited on production environment for this phase.**

### Safety Guards (Fail-Closed)

To prevent accidental production outages or misconfiguration:
*   If `APP_ENV=production` and `VISIONFLOW_NARRATION_HANDOFF_MODE` is set to `shadow` or `control_plane`, the worker **fails closed and crashes on startup** with a `ConfigurationError`.
*   If `shadow` or `control_plane` is active, a valid `VISIONFLOW_ORGANIZATION_ID` and `VISIONFLOW_CONTROL_PLANE_URL` must be provided, or else the worker fails closed.

---

## 2. Staging Runbook

Follow these steps to run and verify shadow mode on the staging environment.

### Phase 2.1 — Resource Setup
1.  Verify the PostgreSQL database has migrations applied up to `0006_command_receipts_hardened`.
2.  Obtain or bootstrap a staging organization ID in PostgreSQL.
3.  Ensure the worker has service-principal capability `workflow:narration:complete` and proper OIDC credentials.

### Phase 2.2 — Worker Configuration
Configure the worker environment group with:
```env
APP_ENV=staging
VISIONFLOW_NARRATION_HANDOFF_MODE=shadow
VISIONFLOW_CONTROL_PLANE_URL=https://visionflow-control-plane-staging.onrender.com/api/v1
VISIONFLOW_ORGANIZATION_ID=de305d54-75b4-431b-adb2-d0459b1e50df
```

### Phase 2.3 — Execution & Shadow Monitoring
1.  Trigger a standard or split-screen narration/rendering job (e.g., job ID `165`).
2.  The job executes B2 script generation.
3.  Observe worker logs for progress updates and shadow reconciliation.

---

## 3. Operator Diagnostics & Reconciliation

Reconciliation reports are logged in JSON format under the logger name `visionflow.shadow_reconciliation`.

### Log Structure
```json
{
  "workflow_run_id": "a988d446-2489-53b7-be18-b2efce863bc0",
  "legacy_job_id": 165,
  "idempotency_key": "narration-a988d446-2489-53b7-be18-b2efce863bc0-a1b2c3d4",
  "control_plane_version_id": "8f3152d2-80b6-4d15-9bd3-d0459b1e50df",
  "normalized_script_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "normalized_scenes_hash": "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
  "result": "matched",
  "trace_id": "5f1b1c3132e4d0df2c0500e28f321ca1",
  "timestamp": "2026-07-16T04:10:00.123Z"
}
```

### Reading Comparison Results

1.  **`matched`**: The Control Plane API succeeded and transitioned to state `SCRIPTED`. MySQL write was also successful.
2.  **`mismatched`**: The Control Plane saved successfully but the returned state or payload did not match expected staging parity.
3.  **`control-plane-failed`**: The Control Plane API call timed out or failed (e.g. 404, 403, 500). Staging continues smoothly because MySQL write is the active source.

### Incident Handling & Troubleshooting
*   **Action for `control-plane-failed`**: Check the worker warning logs for the exact exception detail. Verify OIDC token validity and organization configuration.
*   **Action for `mismatched`**: Do not retry manually. Inspect the database `command_receipts` or `workflow_runs` to see the discrepancy in active revision.
