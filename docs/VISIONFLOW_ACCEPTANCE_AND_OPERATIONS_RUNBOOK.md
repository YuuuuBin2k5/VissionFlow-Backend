# VisionFlow — Acceptance and Operations Runbook

**Use with:** [Master Execution Playbook](VISIONFLOW_MASTER_EXECUTION_PLAYBOOK.md) and [Agent Skills Catalog](VISIONFLOW_AGENT_SKILLS_CATALOG.md).  
**Purpose:** a repeatable evidence pack for V1 short-form, staging-to-production release and later long-form expansion.

## 1. Environment boundary

| Environment | Purpose | May use | Must not use |
| --- | --- | --- | --- |
| Local | rapid development and deterministic fixtures | local Postgres/Redis/R2-compatible test, fake AI/render/publisher adapters | production credentials, public publishing |
| CI | contract/migration/build validation | disposable Postgres, conforming test adapters, browser E2E fixtures | paid model calls, real external channel |
| Staging | production-like integration and acceptance | Neon staging, R2 staging prefix/bucket, dedicated test channel, controlled model budget | real customer data or public channel dispatch |
| Production | approved creator workflows | production secrets, approved provider adapters, explicit manual dispatch | unreviewed schema, test account assumptions, direct emergency SQL writes |

Production and staging are separate organizations/credentials/prefixes. Environment is never inferred from a frontend URL; it is configured server-side. Never include actual credential values in a ticket, commit, console screenshot or runbook output.

## 2. Required preflight checks

Before any acceptance suite or deploy, capture:

- service version/SHA and image digest;
- active Alembic revision and compatibility declaration;
- database backup/recovery point; for production, verified restore rehearsal reference;
- required environment variable **names** present, with secrets redacted;
- Control Plane readiness, Redis/queue health and R2 read/write probe;
- test account or destination allow-list confirmation for publishing;
- on-call/reviewer and rollback decision owner.

If any preflight check is absent, stop. Do not work around it with direct database edits.

## 3. Short-form V1 acceptance suite

Run in this order on staging. Save workflow IDs and trace IDs as evidence.

### A1 — Tenant and authentication boundary

1. Register/bootstrap Organization A and create an editor, reviewer and viewer.
2. Create Organization B; try to read/edit A's brief, asset, timeline and audit event using B credentials.
3. Revoke an editor session; retry a mutation with the revoked refresh token.

**Pass:** B receives safe denial without information leakage; revocation prevents new session; allowed actions emit audit events.

### A2 — Brief, prompt and Creative Document

1. Create a short-form brief with target format and brand constraint.
2. Request creative plan with a promoted prompt version and a fixed provider/model configuration.
3. Exercise one malformed model output or policy failure using a conforming test adapter.
4. Promote a new prompt version; verify the existing plan/run still resolves the old immutable version.

**Pass:** valid result is schema-valid and cites version/config; failure is explicit/retryable where policy permits; no client contains AI key.

### A3 — Asset and rights chain

1. Upload valid video/image/audio through signed URL then finalize it.
2. Try wrong checksum/type/size and an object key outside the organization prefix.
3. Add one asset with incompatible/unknown rights to a draft; try lock.
4. Restart a worker and read a finalized asset by object key.

**Pass:** invalid upload is rejected; rights block lock; completed asset survives worker restart and has checksum/provenance.

### A4 — Composition, locking and truthful preview

1. Create draft composition from Creative Document; change scene order, duration, transform/keyframe and one supported effect.
2. Reload Studio; verify server composition is restored.
3. Attempt queue before lock and with a stale lock/version.
4. Verify preview shows its declared capability (`layout`, `partial`, or `rendered`).

**Pass:** changes persist; invalid queue requests fail safely; capability label matches actual output semantics.

### A5 — Render, recovery and artifact lineage

1. Queue locked composition and wait for worker completion.
2. Verify fixture output changes for scene ordering/timing/transform/effect.
3. Inject worker crash/cancel and retry from the controlled operator flow.
4. Verify artifact duration/codec/size/checksum and immutable prompt/creative/composition/Render Plan references.

**Pass:** exactly one terminal workflow result; corrupt temporary output is not durable; retry/recovery does not duplicate artifact record; full lineage is queryable.

### A6 — QA, approval and dispatch gate

1. Run ruleset with a deliberately failing artifact/rights/caption case.
2. Attempt approval and dispatch after QA failure.
3. Run a passing artifact; approve with a reviewer; mutate a policy-relevant input and verify decision invalidation if configured.
4. Dispatch only to an allow-listed test destination; simulate timeout then reconcile.

**Pass:** invalid states block downstream action; decisions are immutable/audited; exactly one provider attempt is active; reconciliation is explicit and idempotent.

## 4. Failure drills and operator responses

| Scenario | First response | Safe recovery evidence |
| --- | --- | --- |
| `render-stalled` | inspect workflow trace, queue age and worker heartbeats; do not requeue blindly | one controlled retry/replay with same idempotency key; terminal state reconciles |
| worker crash | inspect pending stream entry and artifact temporary key | ack only after durable result; no duplicate artifact/workflow transition |
| `R2-upload-failed` | inspect object-store error/checksum and temporary prefix | retry upload/finalize; no dangling finalized metadata |
| `Neon-unavailable` | stop mutations, use readiness/degraded state, preserve outbox | recovery verifies schema head and queued commands resume safely |
| provider/model outage | trip circuit/bound retries, show explicit retryable status | provider recovery does not reissue completed plan/render |
| `publish-failed` | freeze new dispatch, inspect attempt/provider reference | reconciliation/update attempt; never claim published without provider confirmation |
| credential rotation | revoke/replace in secret manager; invalidate affected sessions/adapter clients | health/test authorization, audit entry and no secret in logs |
| suspected cross-tenant access | disable impacted endpoint/credential, preserve evidence | scoped investigation, remediation test and user notification process per policy |

Only an authorized operator can replay a dead-letter command. The replay command includes original event ID, reason, actor and new trace ID; it cannot mutate payload content silently.

## 5. Staging → production release procedure

### Stage 1 — Build and validate

1. Run local/CI verification: lint, type, domain/application, contract, integration, disposable migration and browser E2E.
2. Build immutable images. Inspect that runtime user is non-root and image contains no `.env`/secret artifact.
3. Deploy the exact candidate SHA to staging. Run schema migration once via explicit migration job using migration database URL.
4. Run readiness and the full A1–A6 suite with staging-safe adapters; record evidence.

### Stage 2 — Production decision

The independent approver reviews: candidate SHA/image digest, migration revision, test output, staging evidence, changes to secrets/permissions, active alerts, backup/restore reference, rollout owner and explicit forward/rollback plan.

If any approval or required protection is unavailable because of account-plan constraints, record a named manual approver and immutable release note. Do not describe that as an automated protection gate.

### Stage 3 — Deploy and smoke

1. Create/verify production backup and confirm compatibility with target migration.
2. Run forward migration once; stop on unexpected revision/state and choose a documented continue/rollback-at-application decision.
3. Deploy services using the exact approved SHA/image digest, in the declared dependency order.
4. Run health/readiness, authenticated API smoke and one controlled synthetic short workflow that never public-publishes.
5. Monitor error, queue-age, render failure and provider-error alerts during the defined observation window; attach trace IDs to release record.

### Stage 4 — Rollback and forward compatibility

- Roll back service image/config when application behavior fails and latest schema remains compatible.
- Do not execute destructive schema rollback by reflex. Migrations are forward-only in production; use a corrective migration or feature flag when required.
- Pause new dispatches before investigating publication ambiguity. Reconcile existing provider attempts rather than create replacements.

## 6. Long-form acceptance extension

Do not run this suite until all short-form A1–A6 gates pass.

1. Create a long format profile and multi-act plan; verify short formats unchanged.
2. Render segmented chapters; fail and rerender one segment only.
3. Join segments; verify chapter references, output checksum and parent/child workflow lineage.
4. Run chapter QA/review then final QA/approval.
5. Verify format-specific concurrency/cost ceiling and cancellation cleanup.

**Pass:** no separate database/control-plane state model was introduced; a chapter retry does not invalidate unrelated validated segments; final audit links every segment and join.

## 7. Operational readiness scorecard

Mark each item with evidence link/trace, not a verbal confirmation.

| Area | Required evidence |
| --- | --- |
| Security | tenant isolation, secret scan, dependency review, session/credential rotation drill |
| Data | migration revision, backup/recovery drill, R2 metadata/retention manifest |
| Workflow | duplicate/restart/DLQ recovery fixture |
| Media | locked snapshot → checksummed artifact → QA report fixture |
| Approval/publish | rejected/approved/timeout/reconcile test-destination evidence |
| Observability | trace across all services, alert test, runbook owner |
| Release | SHA/digest, staging acceptance, independent approval, production smoke |
| UX | server-reload state, capability truthfulness, keyboard/reduced-motion checks |

## 8. Research basis

- GitHub supports deployment environments, protected deployment jobs and concurrency controls: [GitHub Actions deployments and environments](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments).
- OpenTelemetry defines correlated traces, metrics and logs for service behavior: [OpenTelemetry instrumentation](https://opentelemetry.io/docs/concepts/instrumentation/).
- R2 lifecycle rules have asynchronous transition/deletion behavior, so active evidence must be modelled before retention expiry: [Cloudflare R2 lifecycles](https://developers.cloudflare.com/r2/buckets/object-lifecycles/).
