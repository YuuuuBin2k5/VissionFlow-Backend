# VisionFlow Stream B Activation Gate

## Current status

All Stream B modules are **dormant**. `orchestrator/src/main.ts` does not
import the runtime. `VISIONFLOW_LEGACY_INTAKE_ENABLED` defaults to disabled;
only the exact string `true` can construct Redis consumers or HTTP clients.

The activation commit must call `attachLegacyIntakeRuntime(app)` from
`orchestrator/src/visionflow/legacyIntakeStartup.ts` after `dotenv.config()`.
It must retain the returned runtime and await `runtime.stop()` on `SIGINT` and
`SIGTERM`. This adapter exposes `GET /health/visionflow/legacy-intake` without
leaking secrets or event payloads.

For production, prefer the isolated entrypoint
`npx ts-node src/visionflow/runLegacyIntake.ts` over attaching Stream B to the
Telegram web process. It has its own health port and shutdown lifecycle, so it
can be deployed as a separately scaled worker service.

Use `orchestrator/Dockerfile.legacy-intake` for that service. It uses Render's
`PORT` automatically when `VISIONFLOW_LEGACY_INTAKE_PORT` is unset; configure
the health check as `/health/visionflow/legacy-intake`.

`render.stream-b.staging.yaml` is the opt-in Render Blueprint. It deliberately
starts with `VISIONFLOW_LEGACY_INTAKE_ENABLED=false`; deploy and health-check
that inert service before changing the flag through Render's secret settings.

## Required deployment configuration

Configure these as Render secrets, never in Git:

```text
VISIONFLOW_LEGACY_INTAKE_ENABLED=true
REDIS_URL=<redis-tls-url>
VISIONFLOW_INTAKE_HMAC_KEY_ID=<current-key-id>
VISIONFLOW_INTAKE_HMAC_KEY=<current-key>
VISIONFLOW_INTAKE_HMAC_PREV_KEY_ID=<previous-key-id, optional paired value>
VISIONFLOW_INTAKE_HMAC_KEY_PREV=<previous-key, optional paired value>
VISIONFLOW_LEGACY_MAPPING_CLIENT_ID=visionflow-legacy-intake
VISIONFLOW_LEGACY_MAPPING_CLIENT_SECRET=<different-secret>
VISIONFLOW_LEGACY_MAPPING_SUBJECT=service|visionflow-legacy-intake
VISIONFLOW_CONTROL_PLANE_BASE_URL=https://<control-plane>
VISIONFLOW_AUTH_AUDIENCE=visionflow-control-plane
```

Before activation, apply MySQL only through `npx prisma migrate deploy` and
seed the legacy mapping service subject as a `service` organization member in
the Control Plane. Do not use `db push` or runtime table creation.

Run `node orchestrator/scripts/validate-visionflow-stream-b-config.js` in the
target deployment environment immediately before enabling the flag. It makes
no network calls and never prints secrets.

## Readiness checks

1. Rehearse the MySQL migration on a disposable database with
   `powershell -ExecutionPolicy Bypass -File orchestrator/scripts/rehearse-visionflow-mysql-migration.ps1`.
   The `VisionFlow Stream B CI` workflow must also be green.
2. Build `orchestrator/Dockerfile.legacy-intake` and run its dormant health
   check locally before deploy; leave the feature flag unset in Render.
3. Confirm the Control Plane outbox relay has `REDIS_URL` and the HMAC current
   key configured.
4. Create one non-production workflow and manually invoke the internal
   `RequestLegacyJob` use case.
5. Enable one consumer replica. Verify a link, one MySQL job, and one
   successful mapping receipt.
6. Force a consumer interruption and verify `XAUTOCLAIM` reclaims the PEL.
7. Run 100 staging jobs with no mapping mismatch before expanding traffic.

## Rollback

Set `VISIONFLOW_LEGACY_INTAKE_ENABLED=false` and restart only the intake
runtime. Existing rows remain durable in `legacy_outbox`; do not delete or
replay them manually without an operator incident record.

After deploy, run `VISIONFLOW_LEGACY_INTAKE_BASE_URL=https://<service> node
orchestrator/scripts/probe-visionflow-legacy-intake.js`. Add
`VISIONFLOW_EXPECT_LEGACY_INTAKE_ENABLED=true` only after intentionally
enabling the service. The endpoint returns `503` while an enabled intake has
not initialized its Redis consumer group or its consumer connection has
failed; this is deliberate so Render health checks cannot mask a disconnected
intake. Mapping-delivery failures are retained in the durable MySQL outbox and
exposed through `lastErrorCode` for operator investigation.
