# VisionFlow staging runbook

This runbook deploys the production-shaped VisionFlow V1 short-form path to a **staging** environment. It uses Neon PostgreSQL as the Control Plane database, a TLS Redis-compatible service for the event stream, S3-compatible object storage (Cloudflare R2 or AWS S3), an external OIDC provider, and Render services. No value in this document is a credential; create all secret values in the relevant provider's secret manager.

Staging is an isolated environment. It must not share a Neon database, Redis namespace, object-storage bucket, OIDC client, or Render environment group with production.

## Service inventory

Create the following services in one Render staging environment group. The service names are intentional: they make alerts, logs, and release approvals unambiguous.

| Render service | Type | Source directory / Dockerfile | Start command | Responsibility |
| --- | --- | --- | --- | --- |
| `visionflow-control-plane-staging` | Web Service | `services/control-plane` / `services/control-plane/Dockerfile` | Image default (`uvicorn app.main:app --host 0.0.0.0 --port 8000`) | OIDC-protected API, PostgreSQL transaction boundary, outbox writer |
| `visionflow-migrate-staging` | Pre-deploy job | Same image as Control Plane | `python -m alembic upgrade head` | Applies the additive PostgreSQL schema before application code is released |
| `visionflow-outbox-relay-staging` | Background Worker | Same image as Control Plane | See the deployment gate below | Reads committed outbox rows and publishes Redis Stream events |
| `visionflow-intelligence-worker-staging` | Background Worker | `worker` / `worker/Dockerfile` | `python worker/consume_visionflow_events.py` | Consumes VisionFlow events; creates scripts/storyboards and dispatches render work |
| `visionflow-studio-staging` | Static Site | `../ClientAgent` (separate frontend repository directory) | Standard Vite build and static publish | Operator console; never stores service secrets |

Do not deploy the legacy MySQL orchestrator, old worker `main.py`, or Telegram auto-publish path as a dependency of this staging flow. They are outside the VisionFlow V1 runtime boundary.

## Deployment gate: relay image

The current Control Plane Dockerfile copies `app`, `alembic`, and `alembic.ini`, but does **not** copy `scripts/`. Therefore `python scripts/relay_outbox.py` is not available inside its built image yet. Do not create or start `visionflow-outbox-relay-staging` until that image-build gap is corrected in a reviewed code change.

After the image includes `scripts/relay_outbox.py`, configure the relay command as:

```sh
sh -c 'while true; do python scripts/relay_outbox.py --limit 50 || exit $?; sleep 2; done'
```

This is deliberately a separate process from the API. If Redis is unavailable or a configuration error occurs, it exits non-zero so Render restarts and alerts the service; it does not silently drop events. Running the bounded command once is only a diagnostic action, not a production relay.

## External resources

Create these before creating Render services.

| Resource | Staging requirement |
| --- | --- |
| Neon PostgreSQL | One staging project/database, TLS required. Create a least-privilege application role and a separate migrator role. Use the pooled URL at runtime and direct URL only for Alembic/bootstrap. |
| Redis-compatible broker | A dedicated staging database or namespace, TLS endpoint only. Do not share stream names with production. |
| Cloudflare R2 or AWS S3 | A dedicated private bucket, e.g. `visionflow-staging-assets`. Enable provider-side encryption if available and restrict the worker key to this bucket/prefix. |
| OIDC provider | Separate staging API audience, SPA client, and confidential machine clients. Register the exact static-site redirect URI. Require RS256 or ES256 signing. |
| Render | A distinct staging environment group. Grant secrets only to the service which uses them. |

## Render environment contracts

Set secrets in Render; do not commit a populated `.env` file and do not expose worker or storage secrets to `visionflow-studio-staging`.

### `visionflow-control-plane-staging`

```env
APP_ENV=staging
PORT=8000
API_PREFIX=/api/v1
DATABASE_URL=postgresql+psycopg://<app-role>:<secret>@<neon-pooled-host>/<database>?sslmode=require
MIGRATION_DATABASE_URL=postgresql+psycopg://<migrator-role>:<secret>@<neon-direct-host>/<database>?sslmode=require
OIDC_ISSUER=https://<staging-issuer>/
OIDC_AUDIENCE=visionflow-control-plane-staging
OIDC_JWKS_URL=https://<staging-issuer>/.well-known/jwks.json
OIDC_ALLOWED_ALGORITHMS=RS256,ES256
REDIS_URL=rediss://<user>:<secret>@<redis-host>:<port>/0
VISIONFLOW_EVENTS_STREAM=visionflow.staging.workflow-events.v1
```

Use the same database and Redis environment values for `visionflow-migrate-staging` and, after the deployment gate is cleared, `visionflow-outbox-relay-staging`. The migrator URL must never be injected into the web API if deployment policy permits service-specific secrets; the current application config loads it for migration tooling, so keep access restricted to the environment group.

### `visionflow-intelligence-worker-staging`

```env
VISIONFLOW_CONTROL_PLANE_URL=https://<control-plane-host>/api/v1
VISIONFLOW_ORGANIZATION_ID=<staging-organization-uuid>
VISIONFLOW_OIDC_TOKEN_URL=https://<staging-issuer>/oauth/token
VISIONFLOW_OIDC_CLIENT_ID=visionflow-intelligence-worker-staging
VISIONFLOW_OIDC_CLIENT_SECRET=<secret-manager-value>
VISIONFLOW_OIDC_AUDIENCE=visionflow-control-plane-staging
REDIS_URL=rediss://<user>:<secret>@<redis-host>:<port>/0
VISIONFLOW_EVENTS_STREAM=visionflow.staging.workflow-events.v1
VISIONFLOW_WORKER_GROUP=visionflow-intelligence-staging-v1
VISIONFLOW_WORKER_CONSUMER=<render-instance-id>
VISIONFLOW_OBJECT_STORE_ENDPOINT=https://<account-endpoint>
VISIONFLOW_OBJECT_STORE_BUCKET=visionflow-staging-assets
VISIONFLOW_OBJECT_STORE_ACCESS_KEY_ID=<secret-manager-value>
VISIONFLOW_OBJECT_STORE_SECRET_ACCESS_KEY=<secret-manager-value>
VISIONFLOW_OBJECT_STORE_REGION=auto
GEMINI_API_KEY=<secret-manager-value>
```

Use a distinct `VISIONFLOW_WORKER_CONSUMER` value for each concurrent replica. Configure only the source-provider/TTS credentials actually needed by the selected render adapters. Legacy `DB_*` variables are not a VisionFlow requirement and must not be used by `consume_visionflow_events.py`.

### `visionflow-studio-staging`

These are build-time public values, not secrets:

```env
VITE_VISIONFLOW_API_URL=https://<control-plane-host>/api/v1
VITE_VISIONFLOW_ORGANIZATION_ID=<staging-organization-uuid>
VITE_OIDC_AUTHORIZATION_ENDPOINT=https://<staging-issuer>/authorize
VITE_OIDC_TOKEN_ENDPOINT=https://<staging-issuer>/oauth/token
VITE_OIDC_CLIENT_ID=visionflow-studio-staging
VITE_OIDC_REDIRECT_URI=https://<studio-host>/login
VITE_OIDC_SCOPE=openid profile email
VITE_OIDC_AUDIENCE=visionflow-control-plane-staging
```

Register `https://<studio-host>/login` exactly with the OIDC provider before publishing the static site. Never put client credentials, database URLs, Redis URLs, Gemini keys, or object-storage keys in a `VITE_*` variable.

## Ordered release procedure

1. Run repository gates from a clean checkout: Control Plane verification, worker VisionFlow tests, and Studio lint/test/build. Stop on any failure.
2. Provision Neon, Redis, R2/S3, and OIDC resources above. Store each credential only in its service-specific Render environment.
3. Deploy `visionflow-migrate-staging`. Verify it exits successfully. Do not start the API against an unknown schema version.
4. From a secured operator terminal with `MIGRATION_DATABASE_URL`, bootstrap the staging organization and first operator. Bootstrap the OIDC subject exactly as emitted by the provider. Bootstrap the worker client subject with `--role service`.
5. Deploy `visionflow-control-plane-staging`; wait for both `/health` and `/ready` to succeed.
6. Clear the relay image deployment gate, then deploy `visionflow-outbox-relay-staging`.
7. Deploy `visionflow-intelligence-worker-staging`; confirm its consumer group is created and it is blocked waiting for stream messages rather than restarting.
8. Publish `visionflow-studio-staging`; test OIDC login and organization-scoped access.
9. Run the end-to-end smoke check below using a non-production brief and a dedicated test asset prefix.
10. Capture the release evidence (commit SHA, Render deploy IDs, migration output, smoke workflow ID, and timestamps). Only then mark staging ready for promotion.

## Smoke checks and acceptance evidence

Run these in order. Redact bearer tokens, database URLs, and credentials from saved logs.

### 1. API and database readiness

```sh
curl --fail --show-error https://<control-plane-host>/api/v1/health
curl --fail --show-error https://<control-plane-host>/api/v1/ready
```

Expected: `health` returns `status: ok`, `service: visionflow-control-plane`, `environment: staging`; `ready` returns `status: ready`, `database: postgresql`.

### 2. Authorization boundary

With a valid Studio OIDC access token and a unique idempotency key, create one short-form workflow. Repeat the exact request with the same key; it must return the same logical workflow rather than create a duplicate. A token from another organization must receive 403/404 and must not reveal the workflow.

### 3. Outbox and worker hand-off

Submit the created workflow. Confirm its state progresses `DRAFT → READY → QUEUED`. Inspect relay logs for the stable `event_id` and worker logs for the matching workflow/trace ID. Restart the worker once during this test; redelivery must not create a second workflow or repeat an already accepted transition.

### 4. Intelligence and render path

Confirm Control Plane workflow steps contain validated Script and Storyboard outputs, then confirm the workflow progresses through:

```text
PLANNING → SCRIPTED → STORYBOARDED → ASSETS_READY → RENDERING → QA_PENDING
```

Confirm all temporary media is under the worker workspace and all retained assets/exports use the staging object-storage prefix:

```text
visionflow/<workflow-run-id>/
```

No MySQL write, `job_id`, or legacy job lookup may appear in the VisionFlow worker logs for this run.

### 5. QA, approval, and tenant isolation

Verify QA either rejects the artifact without changing state, or accepts it and moves it to `RENDERED`. Execute the manual approval path and verify the canonical state sequence:

```text
RENDERED → APPROVAL_PENDING → APPROVED
```

Verify an operator from another organization cannot read the execution context, approve, or transition the workflow.

## Rollback and incident rules

- **API deploy failure:** roll back only the API/worker image to the last known-good immutable image. Do not roll back an already-applied PostgreSQL migration; migrations must be additive and forward-fixed.
- **Redis outage:** pause relay/worker processing. Outbox records remain unpublished and can be relayed after recovery. Do not manually mark unverified events as published.
- **Worker/render failure:** leave the workflow in its current server-side state, preserve trace ID and object keys, then retry through the approved workflow transition/retry policy. Do not alter PostgreSQL rows manually.
- **Credential exposure:** revoke the affected provider credential, rotate it in Render, redeploy the affected service, and audit object-storage/Neon/OIDC logs.
- **Staging data:** use synthetic briefs and assets only. Delete staging objects by the workflow prefix after evidence retention requirements are met.

## Promotion prerequisite

Production promotion is a new release, not a rename of staging. It requires a separate production environment group, separate Neon/Redis/bucket/OIDC clients, the same smoke checklist, and explicit approval after staging evidence is reviewed.
