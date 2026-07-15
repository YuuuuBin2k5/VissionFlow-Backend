# VisionFlow PostgreSQL Cutover Assessment

This assessment provides the technical basis and evidence pack for the PostgreSQL cutover decision in the VisionFlow AI Video Operating System.

---

## 1. Target Schema Alignment Audit

### Neon Actual Schema vs. SQLAlchemy Models vs. Prisma Schema
A detailed cross-database audit was conducted on both the active Neon PostgreSQL instance and the local MySQL instance to identify discrepancy patterns.

#### Active Neon PostgreSQL Schema (Actual)
The public schema of the Neon PostgreSQL database contains exactly **26 tables** with **0 rows** in domain tables and a single migration record in `alembic_version`. The table list and structure are:
- **Migration History**: `alembic_version` (contains a single row pointing to migration `0004_composition_studio`).
- **Authentication**: `auth_users` (1 row), `auth_sessions` (1 row), `auth_refresh_tokens` (3 rows), `auth_audit_events` (4 rows).
- **Core Domain**:
  - `organizations` (1 row), `organization_memberships` (1 row), `users` (2 rows) - *these are bootstrap records*.
  - `video_projects` (0 rows)
  - `workflow_runs` (0 rows)
  - `workflow_steps` (0 rows)
  - `outbox_events` (0 rows)
  - `prompt_templates` (0 rows), `prompt_versions` (0 rows), `prompt_audit_events` (0 rows)
  - `media_assets` (0 rows), `publish_approvals` (0 rows)
- **Creative & Timeline Workspace**:
  - `creative_documents` (0 rows), `creative_document_versions` (0 rows), `creative_scenes` (0 rows)
  - `composition_documents` (0 rows), `composition_versions` (0 rows), `composition_tracks` (0 rows), `composition_clips` (0 rows), `composition_effect_instances` (0 rows), `composition_keyframes` (0 rows)

#### SQLAlchemy Models (`services/control-plane`)
The SQLAlchemy declarative base defined in `services/control-plane/app/infrastructure/models.py` maps **100% identically** to the 26 tables in the Neon PostgreSQL database.
- A **Migration Rehearsal** was conducted on a fresh, isolated PostgreSQL database container (`postgres:15-alpine`).
- Running `alembic upgrade head` successfully executed all 4 migration scripts in sequence:
  1. `0001_initial_visionflow_v1`
  2. `0002_local_auth_foundation`
  3. `0003_creative_documents`
  4. `0004_composition_studio`
- The resulting schema matched the Neon PostgreSQL schema exactly, confirming that **`services/control-plane` is the sole author and owner of the PostgreSQL schema on Neon**.

#### Prisma Schema (`orchestrator/prisma/schema.prisma`)
The legacy Prisma schema defined in the Node.js orchestrator targets a **MySQL database** and defines an entirely different schema. It maps tables like:
- `bot_users`, `bot_accounts`, `channels_campaign`
- `video_pipeline_jobs`, `publish_targets`
- `platform_connections`, `user_api_keys`
- `process_realtime_logs`, `cockpit_system_metrics`, `video_performance_timeseries`
- `agent_prompt_templates`, `agent_prompt_versions`, `agent_prompt_audit_logs`

#### Schema Discrepancy Matrix
| Feature Area | MySQL Legacy Table (Prisma) | PostgreSQL Target Table (SQLAlchemy) | Dialect/Design Differences |
| :--- | :--- | :--- | :--- |
| **Authentication / User** | `bot_users` (BigInt autoincrement, Telegram user ID) | `users` (UUID primary key, OIDC sub claim), `auth_users` (Local user credentials) | PostgreSQL uses UUIDs for ID generation, separates local auth credentials from core identity. |
| **Job / Workflow** | `video_pipeline_jobs` (flat structure, state strings, file paths) | `workflow_runs`, `workflow_steps` (structured state machine, JSONB manifests) | PostgreSQL models workflow progression as versioned DAG steps using transactional JSONB fields. |
| **Workspace / Editing** | *None (represented as files/logs)* | `creative_documents`, `composition_documents` | Full timeline multi-track editing workspace schema. |
| **Prompts** | `agent_prompt_templates` (integer keys) | `prompt_templates` (UUID keys, organization scope) | Tenant/Organization-isolated prompts. |
| **Publishing** | `publish_targets` (MySQL specific status) | `publish_approvals`, `media_assets` (UUID keys) | Integrates with media asset inventory and explicit approval audits. |

---

## 2. Runtime Topology Analysis

The VisionFlow runtime connects to two distinct databases. Below are the specific files and lines establishing connections to MySQL and PostgreSQL:

### MySQL Connections (Legacy System)
1. **Node.js Orchestrator API & Scheduler**
   - **File**: [prisma/schema.prisma](file:///d:/Folder_Learning_2025_2026/MyProject_DuAnCaNhan/AgentBot/AgentTiktok/orchestrator/prisma/schema.prisma)
   - **Line 5-10**: Defines `datasource db` with `provider = "mysql"` using environment variable `DATABASE_URL` (which points to MySQL locally/production).
   - **File**: [src/main.ts](file:///d:/Folder_Learning_2025_2026/MyProject_DuAnCaNhan/AgentBot/AgentTiktok/orchestrator/src/main.ts)
   - **Line 18**: Instantiates `PrismaClient` to interact with MySQL.

2. **FastAPI Gateway (BackendAgent)**
   - **File**: [app/config.py](file:///d:/Folder_Learning_2025_2026/MyProject_DuAnCaNhan/AgentBot/BackendAgent/app/config.py)
   - **Line 16**: Sets `MYSQL_URL = os.getenv("MYSQL_URL")`.
   - **File**: [app/database.py](file:///d:/Folder_Learning_2025_2026/MyProject_DuAnCaNhan/AgentBot/BackendAgent/app/database.py)
   - **Line 10-25**: Establishes raw MySQL connection pool using `pymysql.cursors.DictCursor`.

3. **Python Worker**
   - **File**: [worker/config.py](file:///d:/Folder_Learning_2025_2026/MyProject_DuAnCaNhan/AgentBot/AgentTiktok/worker/config.py)
   - **Line 15-20**: Configures database properties: `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`.
   - **File**: [worker/infrastructure/database.py](file:///d:/Folder_Learning_2025_2026/MyProject_DuAnCaNhan/AgentBot/AgentTiktok/worker/infrastructure/database.py)
   - **Line 11-20**: Instantiates pymysql connection objects using `pymysql.connect()`.

### PostgreSQL Connections (Control Plane)
1. **Control Plane FastAPI App**
   - **File**: [app/core/config.py](file:///d:/Folder_Learning_2025_2026/MyProject_DuAnCaNhan/AgentBot/AgentTiktok/services/control-plane/app/core/config.py#L32-L50)
   - **Line 32-50**: Resolves `DATABASE_URL` (pooled Neon endpoint) and `MIGRATION_DATABASE_URL` (direct Neon endpoint).
   - **File**: [app/infrastructure/database.py](file:///d:/Folder_Learning_2025_2026/MyProject_DuAnCaNhan/AgentBot/AgentTiktok/services/control-plane/app/infrastructure/database.py)
   - **Line 12**: Instantiates SQLAlchemy `create_engine()` with `psycopg` driver targeting PostgreSQL.

---

## 3. Worker Consistency Check

Under the VisionFlow architecture, **the Control Plane is the sole writer** of PostgreSQL workflow state. However, the current code violates this boundary by allowing external worker/gateway processes to directly execute writes:

### python Worker Direct MySQL Writes
- **File**: [video_job_repository.py](file:///d:/Folder_Learning_2025_2026/MyProject_DuAnCaNhan/AgentBot/AgentTiktok/worker/infrastructure/repositories/video_job_repository.py)
  - `update_state` (directly updates `pipeline_state`)
  - `save_script_result` (updates narration scripts, scene layouts, metadata)
  - `save_audio_path` (writes audio file paths)
  - `save_render_result` (writes video output paths)
- **File**: [publish_target_repository.py](file:///d:/Folder_Learning_2025_2026/MyProject_DuAnCaNhan/AgentBot/AgentTiktok/worker/infrastructure/repositories/publish_target_repository.py)
  - `mark_publishing`, `mark_published`, `mark_failed` (directly updates platform publishing states)

### BackendAgent (FastAPI Gateway) Direct MySQL Writes
- **File**: [routers/pipeline.py](file:///d:/Folder_Learning_2025_2026/MyProject_DuAnCaNhan/AgentBot/BackendAgent/app/routers/pipeline.py)
  - `_save_script_to_db` (writes raw script JSON)
  - `api_start_pipeline` (manually sets state to `COMPOSITING`)
  - `api_approve_pipeline_job` (manually sets state to `USER_APPROVED`)
  - `api_reject_pipeline_job` (manually sets state to `FAILED`)

### Architectural Risk
If these write patterns are carried over to PostgreSQL directly, it breaks the transactional outbox pattern, bypasses OIDC authorization, risks lock contention (due to concurrent workers updating state rows), and leads to untraceable state drift.

---

## 4. Safe Cutover Execution Plan

A phased cutover strategy is required to migrate from MySQL to PostgreSQL safely without losing production data.

### Phase 1: Database Adapter & Adapter Implementation
1. **Control Plane Outbox Event Consumers**
   - Configure the worker to stop writing directly to the database. Instead, workers must send requests to the Control Plane API (e.g., `PUT /api/v1/workflows/steps/{id}`) using OIDC tokens.
   - The Control Plane handles the state writes and emits a transactional outbox event (e.g., `workflow_step.completed`).

### Phase 2: Schema Migration and Double Writing
1. **Migrate Historical Data (MySQL -> Postgres)**
   - Since the MySQL and PostgreSQL schemas are structured differently, raw schema dumping is not possible.
   - Write a data translation script (`scripts/migrate_mysql_to_postgres.py`) that maps:
     - `bot_users` -> `users` (using synthetic identity subjects or Telegram integrations)
     - `video_pipeline_jobs` -> `workflow_runs` & `workflow_steps` (mapping the sequential execution steps and JSON payloads)
     - `publish_targets` -> `publish_approvals` & `media_assets`
   - Run this script in a dry-run mode, executing assertions to verify mapping integrity.
2. **Read-Only Verification**
   - Deploy the new code pointing to PostgreSQL, but keep MySQL as the write target. Read from PostgreSQL and log discrepancies.

### Phase 3: Traffic Switch (Cutover)
1. **Maintenance Window Start**
   - Pause intake channels (Telegram bot polling, schedulers).
   - Let active rendering workers finish their current step.
2. **Final Sync**
   - Run the data translation script to sync the remaining MySQL delta rows to PostgreSQL.
3. **Assert Verification**
   - Execute row-count and state assertions between MySQL and PostgreSQL.
4. **Adapter Cutover**
   - Change configuration variables so that the Control Plane FastAPI is the active endpoint.
   - Unpause intake channels and resume execution.

---

## 5. Inventory Mismatch Resolution

### Discrepancy Clarification
Previous audit logs reported that "no Alembic/SQLAlchemy schema or database tables existed" in the project setup. A subsequent detailed audit revealed that the active Neon PostgreSQL database was indeed fully populated with 26 tables matching Alembic revision `0004_composition_studio`.

### Root Cause of the Mismatch
The mismatch occurred due to the following procedural and scope limitations during the initial assessment phase:
1. **Narrow Audit Scope**: The initial search was restricted to the root directories of the legacy systems (`AgentTiktok/orchestrator`, `AgentTiktok/worker`, and `BackendAgent`). It did not traverse subdirectories (specifically, `AgentTiktok/services/control-plane`), where the FastAPI Control Plane and the associated Alembic migrations are located.
2. **Missing Database Inspection**: The early audits did not query the live tables or the `alembic_version` metadata inside the Neon PostgreSQL instance. It relied solely on parsing the codebase's local `.env` and `schema.prisma` configurations.
3. **Implicit Assumption of Monolith**: The previous agent assumed that the Node.js orchestrator was the sole authoritative writer for the entire project state, and because its `schema.prisma` targeted MySQL, they concluded that the database lacked any PostgreSQL schema setup.

### Instructions for Future Agents
- **Always perform live database discovery** (using read-only connection scripts) before making assertions about database contents.
- **Do not assume the root files represent all services**. In multi-service monorepos like VisionFlow, always check under the `services/` folders for specialized applications (e.g. `services/control-plane`).
- **Verify migrations against multiple configurations**. Check both `prisma/` and `alembic/` configurations in parallel across all folders.
