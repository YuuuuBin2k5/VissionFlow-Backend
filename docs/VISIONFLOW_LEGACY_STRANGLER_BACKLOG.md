# VisionFlow Legacy Strangler Backlog

This document outlines the concrete execution slices to strangle legacy MySQL direct writes and migrate execution state to the canonical PostgreSQL Control Plane.

---

## Slice VF-01: Aggregate & Schema Handoff Mapping
*Identify MySQL legacy tables containing production data that must be preserved, and define their mapping to PostgreSQL target structures.*

- **Aggregate Owner**: Video Project / Workflow aggregate
- **Legacy Table & Row Counts (Local Dev)**:
  - `channels_campaign`: 113 rows
  - `video_pipeline_jobs`: 166 rows
  - `publish_targets`: 94 rows
- **Mapping Field MySQL → PostgreSQL**:
  - **Campaigns**: `channels_campaign` → `video_projects`
    - `id` (int) → `id` (UUID - generated synthetically or mapped via lookup)
    - `topic` → `title`
    - `target_audience` → `brief`
    - `created_at` → `created_at`
  - **Jobs**: `video_pipeline_jobs` → `workflow_runs` & `workflow_steps`
    - `id` (int) → `workflow_runs.idempotency_key` (e.g. `legacy-job-id-{id}`)
    - `pipeline_state` → `workflow_runs.state` & `workflow_steps.state`
    - `hook_text_3s`, `full_voice_script`, `scenes_layout_json` → `creative_document_versions.script` & `creative_scenes`
  - **Publishing**: `publish_targets` → `publish_approvals` & `media_assets`
    - `external_url` → `media_assets.object_key`
    - `status` → `publish_approvals.decision` (e.g., `PUBLISHED` → `approved`, `PENDING_APPROVAL` → `pending`)
- **Data Reconciliation Query**:
  ```sql
  -- Run on PostgreSQL to verify all legacy jobs exist in the new runs table
  SELECT COUNT(legacy_jobs.id)
  FROM mysql_table_fdw_link.video_pipeline_jobs legacy_jobs
  LEFT JOIN public.workflow_runs target_runs
    ON target_runs.idempotency_key = CONCAT('legacy-job-id-', legacy_jobs.id)
  WHERE target_runs.id IS NULL;
  ```
- **Staging Test**: Run dry-run translator python script `scripts/migrate_mysql_to_postgres.py` locally and verify that row counts match.
- **Rollback Plan**: In case of conversion errors, drop migrated UUID rows matching `legacy-job-id-*` prefixes.

---

## Slice VF-02: Design Typed API Contract for Video Workflow Initiation
*Define the typed contract and authentication guards for initiating a vertical video workflow run.*

- **Aggregate Owner**: Control Plane API (`services/control-plane`)
- **API/Event Contract**:
  - **Endpoint**: `POST /api/v1/workflows/short-form`
  - **Headers**:
    - `Authorization: Bearer <JWT>` (OIDC access token with `workflow:create` scope)
    - `Idempotency-Key: <UUID>`
  - **Request Body**:
    ```json
    {
      "project_id": "uuid",
      "video_title_idea": "Title prompt text",
      "voice_profile": "vi-VN-Standard-A",
      "split_mode": "FULLY_GENERATIVE"
    }
    ```
  - **Response**: Returns the created `workflow_run_id` and the initial sequence of `workflow_steps`.
- **Idempotency/Auth/Audit/Trace Behavior**:
  - **Idempotency**: Checked using the `Idempotency-Key` header against `workflow_runs.idempotency_key` (returns 200 OK with cached response if hit).
  - **Auth**: Resolves client identity through the OIDC bearer token; verifies organization membership.
  - **Trace**: Propagates `X-Request-ID` to all sub-requests and logging streams.
  - **Audit**: Log event `workflow_run.opened` written to `outbox_events` table for downstream consumers.
- **Staging Test**: Run postman/curl test suite against staging Control Plane app running locally with mock OIDC tokens.
- **Rollback Plan**: Standard API rollback. Disable route via feature flag if database connections spike.

---

## Slice VF-03: First Legacy Write Path strangler (Worker Narration State)
*Choke the first write path in the Python worker that saves AI voice scripts directly to the MySQL database, routing it through the Control Plane instead.*

- **Aggregate Owner**: Creative Document Aggregate
- **Write Path Modification**:
  - **Legacy Code**: `worker/infrastructure/repositories/video_job_repository.py` line 70-85 (`save_script_result` writing directly to MySQL).
  - **New Adapter**: Replace raw SQL update queries with a secure HTTPS call to the Control Plane API:
    `PUT /api/v1/workflows/runs/{run_id}/steps/generate-narration`
- **Mapping Field MySQL → PostgreSQL**:
  - `full_voice_script` → `creative_document_versions.script`
  - `scenes_layout_json` → `creative_scenes` positions and prompts
- **Idempotency/Auth/Audit/Trace Behavior**:
  - The worker retrieves a service account token via OIDC.
  - Passes the trace ID (from input payload) in the API header.
  - Control Plane logs audit entry for version change in `prompt_audit_events`.
- **Staging Test**: Run the video generator pipeline using mock scene input, checking that the narration step completes in the postgres `workflow_steps` table.
- **Rollback Plan**: Keep legacy write code active behind a boolean switch `VISIONFLOW_USE_PG_ADAPTER=false`. Revert to MySQL direct writes immediately if API fails.
- **Criteria to Disable Legacy Path**: Staging completes 100 consecutive successful runs.

---

## Slice VF-04: Dual-Read and Reconciliation Verification
*Read from both databases concurrently to verify that the PostgreSQL Control Plane state reflects legacy MySQL state accurately before migration.*

- **Aggregate Owner**: Sync and Observability Engine
- **Verification Strategy**:
  - Enable double-reading in the FastAPI gateway (`BackendAgent`).
  - For every campaign/job lookup, fetch from both MySQL and the Control Plane.
  - Check for mismatches in status, file paths, and scripts.
  - Log errors in logging platform if mismatch occurs.
- **Data Reconciliation Query**:
  ```python
  # Python validation snippet
  def reconcile_states(mysql_state, pg_state):
      mapping = {"QUEUED": "queued", "COMPOSITING": "running", "SUCCESS": "completed"}
      assert mapping[mysql_state] == pg_state, "State mismatch identified!"
  ```
- **Staging Test**: Deploy gateway to staging env and run automated regression scripts.
- **Criteria to Disable Legacy Path**: No mismatches reported for 48 hours of continuous operation.

---

## Slice VF-05: Cutover Staging Proof
*Execute cutover rehearsal in a staging environment to prove zero-data-loss transition of intake channels.*

- **Aggregate Owner**: Intake & Release Operations
- **Steps**:
  - Pause Telegram intakes on staging.
  - Run `scripts/migrate_mysql_to_postgres.py`.
  - Assert that all records are successfully synchronized.
  - Configure the staging gateway to use PostgreSQL exclusively.
  - Unpause intakes and verify that incoming jobs write to PostgreSQL.
- **Rollback Plan**: Point gateway host variables back to the MySQL instance.
- **Criteria to Disable Legacy Path**: Successful execution of staging verification checks.

---

## Slice VF-06: Clean and Reclaim Legacy Database Code
*Decommission the legacy MySQL write paths and remove unused code after the validation retention window.*

- **Aggregate Owner**: Release Operations
- **Steps**:
  - Delete `video_pipeline_jobs` and `publish_targets` from the local MySQL configuration.
  - Remove PyMySQL dependency from the Python worker.
  - Delete unused raw MySQL repository files.
- **Staging Test**: Verify that the entire project compiles and runs with only PostgreSQL configured.
- **Rollback Plan**: Revert commit from Git version history.
