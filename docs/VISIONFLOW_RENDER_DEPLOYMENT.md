# VisionFlow: Render Staging Deployment

This is the deployment path for the new VisionFlow Control Plane and worker.
It is separate from the legacy Telegram/MySQL stack.  Do not point VisionFlow
at MySQL and do not add database credentials to the Vercel frontend.

## 1. Create the Blueprint

In Render, create a **Blueprint** from the backend repository and select
`render.yaml`.  Render will create:

- `visionflow-control-plane-staging` (web service)
- `visionflow-outbox-relay-staging` (background worker)
- `visionflow-intelligence-worker-staging` (background worker)

Use the Control Plane's generated HTTPS URL as `CONTROL_PLANE_URL` below.

## 2. Set secrets before the first deploy

Set these values in Render's secret environment group, then link the group to
all three services where applicable.  `DATABASE_URL` is the Neon pooled URL;
`MIGRATION_DATABASE_URL` is the Neon direct URL used only by the Control Plane
pre-deploy migration.

| Service | Key | Value |
| --- | --- | --- |
| Control Plane + relay | `DATABASE_URL` | Neon pooled PostgreSQL URL |
| Control Plane | `MIGRATION_DATABASE_URL` | Neon direct PostgreSQL URL |
| Control Plane + relay + worker | `REDIS_URL` | TLS Redis-compatible URL |
| Control Plane | `VISIONFLOW_AUTH_ISSUER` | `https://<control-plane>.onrender.com` |
| Control Plane | `VISIONFLOW_AUTH_PRIVATE_KEY_PEM_BASE64` | base64 of an unencrypted RSA private PEM |
| Control Plane + worker | `VISIONFLOW_WORKER_CLIENT_ID` | `visionflow-intelligence-worker` (or a unique opaque ID) |
| Control Plane + worker | `VISIONFLOW_WORKER_CLIENT_SECRET` | the same long random secret |
| Worker | `VISIONFLOW_TOKEN_URL` | `https://<control-plane>.onrender.com/api/v1/auth/token` |
| Worker | `VISIONFLOW_CONTROL_PLANE_URL` | `https://<control-plane>.onrender.com/api/v1` |
| Worker | `VISIONFLOW_ORGANIZATION_ID` | organization UUID created in step 4 |
| Worker | object-store / AI / TTS values | real provider credentials for the renderer |

Generate the worker secret with a password manager or `openssl rand -base64 48`.
Generate the RSA key outside source control.  The private key must never be
committed, echoed into CI logs, or configured in Vercel.

## 3. Deploy and migrate PostgreSQL

Deploy the Control Plane first.  Its Render `preDeployCommand` runs:

```text
python -m alembic upgrade head
```

Confirm `GET /api/v1/health` returns HTTP 200.  If it fails, inspect the
Control Plane deploy logs before enabling either worker.  A migration failure
must be fixed and redeployed; do not create VisionFlow tables manually.

## 4. Bootstrap organization and service membership

From a trusted machine that has both `DATABASE_URL` and
`MIGRATION_DATABASE_URL` set, run the bootstrap command once for the worker:

```powershell
Set-Location 'services/control-plane'
python scripts/bootstrap_admin.py `
  --organization-slug visionflow `
  --organization-name 'VisionFlow' `
  --identity-subject 'service|visionflow-intelligence-worker' `
  --role service `
  --confirm
```

Copy the printed `organization_id` into the worker's
`VISIONFLOW_ORGANIZATION_ID` variable.  A local operator registers through the
Studio, then is added with the same command using the `sub` value from their
access token and `--role administrator`.

## 5. Configure Vercel last

Set only public browser configuration in Vercel:

```text
VITE_VISIONFLOW_API_URL=https://<control-plane>.onrender.com/api/v1
VITE_VISIONFLOW_ORGANIZATION_ID=<organization UUID>
```

Redeploy the Console after setting the variables.  The backend CORS allowlist
is already restricted to `https://vision-flow-console.vercel.app`; add any
custom production domain to `VISIONFLOW_WEB_ORIGINS` before using it.

## 6. Staging acceptance sequence

1. Register the first operator and log in from Vercel.
2. Create one short-form workflow.
3. Confirm Redis contains/consumes its event and the intelligence worker
   advances the state.
4. Confirm the render artifact reaches the configured object store.
5. Review logs and audit events, then promote the same immutable Git commit to
   production with production-only secrets.

Never promote merely because a Docker image builds.  A real short-form run is
the acceptance criterion.
