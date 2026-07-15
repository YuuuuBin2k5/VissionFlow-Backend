# VisionFlow — Master Execution Playbook

**Status:** authoritative handoff for all remaining delivery phases  
**Audience:** implementation agents, reviewers, technical lead and release operator  
**Read first:** [Engineering Standards](VISIONFLOW_ENGINEERING_STANDARDS.md), [Architecture](VISIONFLOW_ARCHITECTURE.md), [V1 Scope](VISIONFLOW_V1_SCOPE.md), [Delivery Plan](VISIONFLOW_DELIVERY_PLAN.md).  
**Detailed Composition Studio work:** [next phases](VISIONFLOW_COMPOSITION_NEXT_PHASES.md), [agent playbook](VISIONFLOW_COMPOSITION_AGENT_PLAYBOOK.md), [ADRs](VISIONFLOW_COMPOSITION_ADRS.md).

This document replaces neither the engineering standards nor the existing delivery plan. It turns them into executable increments with explicit contracts, owners, dependencies, evidence and stop conditions. There are **no calendar estimates**: advance only when the preceding exit gate has evidence.

## 1. Product outcome and non-negotiable flow

VisionFlow V1 is a web-operated system for producing and approving short videos. Telegram is an optional intake adapter; it is never the authority and it is not required for a creator to finish work.

```mermaid
flowchart LR
  B[Brief and brand constraints] --> P[Creative plan]
  P --> C[Composition timeline]
  C --> L[Lock immutable snapshot]
  L --> R[Render request]
  R --> Q[Technical and policy QA]
  Q --> A[Human approval]
  A --> D[Manual publisher dispatch]
  D --> H[Publication audit history]
```

The Control Plane is the sole PostgreSQL business-state writer. Every box after `Lock` is asynchronous: a command is committed with an outbox event, a worker executes through a port, and the worker sends a typed result command back. The browser reads authoritative APIs only.

### Production definition

A short video is production-complete only when it has all of the following, linked by organization and workflow IDs:

1. a versioned brief, prompt template/model configuration and Creative Document;
2. rights/provenance for each external or generated asset;
3. a locked Composition Document and normalized Render Plan hash;
4. a checksummed durable rendered artifact and machine-readable QA report;
5. an immutable reviewer decision; and
6. a publication attempt/audit record, if it is dispatched.

No UI may represent generated text, preview, progress, quota, success or an action as real unless its API contract supplies it. A temporary optimistic state must be labelled pending and reconciled from the server.

## 2. Global dependency map

| Workstream | Depends on | Unlocks | Parallel-safe boundary |
| --- | --- | --- | --- |
| VF-00 contracts and foundations | Engineering Standards | all workstreams | contracts package and CI only |
| VF-01 identity, tenancy and audit | VF-00 | all authenticated Studio mutations | auth/policy adapters |
| VF-02 creative AI and prompt governance | VF-00, VF-01 | guided plan and Creative Document | AI ports, schemas, prompt registry |
| VF-03 asset and brand supply chain | VF-00, VF-01 | legal input to composition/render | object store adapter and asset API |
| VF-04 composition and render | VF-02, VF-03 | preview, export and short-form completion | Render Plan compiler and render adapter |
| VF-05 QA, review and publishing | VF-01, VF-03, VF-04 | governed delivery | policy and publisher adapters |
| VF-06 reliability and observability | VF-00; instrument every phase | safe release and support | telemetry, runbooks, SLOs |
| VF-07 CI/CD and release | VF-00; can start early | staging then production | workflow and infrastructure code |
| VF-08 long-form enablement | VF-04–VF-07 exit gates | larger format without redesign | format/planning/render extensions |
| VF-09 analytics and cost controls | VF-05, VF-06 | feedback and economic governance | analytics read models only |

## 3. Shared contract rules (apply to every phase)

### 3.1 HTTP and command envelope

Every mutation must validate an `Idempotency-Key`, authenticated principal, organization scope and request payload before invoking an application use case. Responses use the stable problem format from Engineering Standards: `code`, `message`, `trace_id`, safe `detail`.

Every asynchronous command carries at least:

```json
{
  "event_version": 1,
  "event_id": "uuid",
  "occurred_at": "UTC ISO-8601",
  "trace_id": "traceparent-or-uuid",
  "organization_id": "uuid",
  "workflow_run_id": "uuid",
  "idempotency_key": "opaque-string",
  "type": "RenderRequested",
  "payload": {}
}
```

Commands express intent; events are facts in past tense. Unknown additive fields must be ignored by consumers. An unknown major version goes to the DLQ with no side effect.

### 3.2 Required records and lineage

Use UUID primary keys, `timestamptz`, an organization foreign key, `created_at`, `updated_at`, and immutable version references where applicable. Do not store local paths in domain records. Store an `object_key`, checksum, content type, byte size, duration and provenance for media.

| Record | Invariant |
| --- | --- |
| `WorkflowRun` | only its transition policy changes lifecycle state |
| `PromptTemplateVersion` | content/model parameters immutable after creation |
| `CreativeDocumentVersion` | structured, schema-valid plan; a render uses one exact version |
| `CompositionDocumentVersion` | only a locked version may be queued |
| `RenderPlan` | normalized from locked composition; hash identifies exact intent |
| `MediaAsset` | checksum/provenance and rights state known before render |
| `QaReport` | tied to artifact checksum and ruleset version |
| `ApprovalDecision` | append-only actor, decision, reason and timestamp |
| `PublicationAttempt` | one provider dispatch key; retry state is explicit |

## 4. Execution phases

### VF-00 — Contract, repository and engineering foundation

**Purpose:** make the system safe to change before adding product features.

**Implement**

- Establish `packages/contracts` as the home for OpenAPI/event JSON Schema and generated clients; do not create a shared catch-all package.
- Add architecture-boundary tests, API compatibility checks, Python/TypeScript unit commands, database migration test and browser E2E command to the root verification interface.
- Publish a source-of-truth map: Control Plane owns state; Studio owns presentation; Telegram only translates input; workers only execute typed commands; Neon PostgreSQL is authoritative.
- Keep the current repository working while consolidation is reviewed in small commits. Do not rename folders/remotes as a feature task.

**Acceptance evidence**

- Fresh checkout runs documented local verification and produces the same result in PR CI.
- A compatible API/event fixture is accepted; a breaking fixture fails CI.
- Import-boundary test rejects framework/ORM/cloud imports in domain/application packages.

**Do not start** VF-01–VF-05 with a duplicate API schema, direct worker SQL, or a client-only type that claims to be a server contract.

### VF-01 — Identity, organization tenancy and audit

**Purpose:** make every workflow action attributable and organization-isolated.

**Implement**

- Keep self-hosted authentication behind an `IdentityProvider` port; use password hashing, revocable refresh sessions and secure cookie/token handling. Browser never sees provider signing keys.
- Add `Organization`, membership and role policy (`owner`, `admin`, `editor`, `reviewer`, `viewer`, service identity). Scope every query and command by organization inside the application layer.
- Make authorization policy explicit per use case. UI hiding is not authorization.
- Record audit facts for registration/login, role change, prompt change/promotion, asset rights change, lock, render request/result, QA, approval, credential access and publication/replay.
- Add bootstrap/first-owner operation that is single-use, logged and disabled after initial organization creation.

**Contracts**

- `POST /auth/register` and login/refresh/logout return only session-safe information.
- `GET /organizations/{id}` and membership operations require policy checks.
- `GET /audit-events` filters by org, actor, action, target and UTC interval; pagination is mandatory.

**Acceptance evidence**

- Cross-organization reads and writes return a safe 404/403 and create no audit leak.
- Revoked refresh token cannot create a new session; role downgrade blocks protected command.
- All mutation integration tests assert an audit event with `actor_id`, target, trace ID and request ID.

### VF-02 — Creative AI orchestration and prompt governance

**Purpose:** turn an approved human brief into a reviewable, structured creative plan without exposing AI credentials or allowing free-form output to enter rendering.

**Implement**

- Define an `AiPlanningProvider` port and a Gemini adapter in infrastructure. Model calls happen server-side through an asynchronous command; manual Gemini-web collaboration remains a labelled user-assisted fallback until server integration exits this phase.
- Use versioned JSON Schema/Pydantic (or equivalent) models for brief analysis, research facts, beat sheet, scenes, voiceover, captions, asset requirements, safety notes and confidence/citations. Validate the response before persisting it.
- Implement a Prompt Registry: immutable template versions, parameter schema, model settings, owner, review state, promotion history, rollback pointer and evaluation suite. A project pins the version it used.
- Add adversarial input controls: allowed tools only, output-size limits, timeouts, model/provider error mapping, content policy checks and a human edit/retry flow. Treat all model output as untrusted.
- Store citations/fact sources separately from generated copy. Never present an unsupported assertion as verified research.

**Contracts**

| Command/event | Minimum payload/result |
| --- | --- |
| `GenerateCreativePlan` | brief version, prompt version, provider config reference, idempotency key |
| `CreativePlanGenerated` | Creative Document version, validation result, usage/cost metadata, citations |
| `CreativePlanRejected` | safe reason code, failing schema/policy location, retry eligibility |
| `PromotePromptVersion` | authorized reviewer, evaluation suite/result IDs, exact version |

**Acceptance evidence**

- A known brief yields a schema-valid Creative Document or an explicit failure—never partial untyped state.
- Same request/idempotency key does not issue a duplicate provider call.
- Prompt promotion requires defined evaluation evidence and the locked run retains prior version content.
- API/browser network logs contain no Gemini key, prompt secret or hidden system instruction.

### VF-03 — Asset, brand and rights supply chain

**Purpose:** ensure composition/render use durable, allowed media with a clear origin.

**Implement**

- Add `AssetStore` port with R2/S3 adapter. Browser uploads through short-lived, scope-limited signed URLs, then calls a finalize API that validates checksum, type, size, dimensions/duration and organization prefix.
- Model brand kit (logos, palette, fonts, voice/style constraints) as versioned project inputs. Generated assets are still assets and carry provider/model/prompt lineage.
- Add rights policy states: `unknown`, `licensed`, `owned`, `generated`, `restricted`, `expired`, `rejected`. Rendering blocks assets not eligible for the intended channel/territory.
- Store derivatives with parent object key, transform/generator version and checksum. Use temporary object keys until integrity validation completes.
- Define R2 lifecycle classes for scratch, previews, source assets and approved exports. Lifecycle rules are applied deliberately per prefix; they are not a substitute for database retention policy.

**Acceptance evidence**

- Invalid media/upload replay/foreign organization object keys are rejected.
- An asset with `unknown`, expired or incompatible rights cannot enter a locked composition.
- Worker can re-read an asset after restart by object key; no workflow depends on local disk.
- Lifecycle/retention policy is reviewed against active render and audit requirements.

### VF-04 — Composition, preview and rendering

**Purpose:** transform the Creative Document and eligible assets into an editable, deterministic short-form export.

**Implement sequence:** execute the detailed Composition Studio documents in this order: CS-01 Render Plan compiler, CS-02 effect registry, CS-03 compositing/caption/audio support, CS-04 truthful preview, CS-05 accessibility UX, CS-06 QA/collaboration. Do not claim CapCut parity before those exit criteria pass.

**System invariants**

- A mutable timeline is a draft. `lock` creates an immutable `CompositionDocumentVersion`; only that version can enqueue render.
- The compiler produces a validated provider-neutral Render Plan. Renderers interpret the plan; they do not invent scene order, timing or effect semantics.
- A renderer emits a temporary artifact, validates codec/duration/size/checksum, promotes durable metadata only on success, then sends a typed result command.
- Preview capability must be truthful: `layout`, `partial`, or `rendered`; never present a placeholder as final output.

**Acceptance evidence**

- Scene order, clip duration, transforms/keyframes and supported effects materially change a deterministic rendered fixture.
- Overlay/caption/audio track behavior has fixture-based render tests before it is enabled in the UI.
- Worker restart/cancel/retry leaves no corrupt durable artifact and produces one terminal workflow state.
- Browser timeline state reloads from server and cannot queue an unlocked/stale snapshot.

### VF-05 — QA, approval and manual publishing

**Purpose:** prevent defective or unapproved content reaching an external channel.

**Implement**

- Define `QaPolicy` specifications and versioned rulesets: media integrity, duration/aspect ratio, audio peaks, caption safe area/readability, prohibited content/rights and required brand constraints. Rules return structured findings, not only pass/fail text.
- Build reviewer queue with signed preview, artifact checksum, Creative/Composition/Prompt version links, findings and an immutable approval/rejection reason.
- Implement each external platform as `PublisherAdapter` + anti-corruption mapper. Provider credentials are encrypted and never return from APIs. Start with a dedicated staging/test destination.
- Dispatch is a separate authorized command after approval. Enforce one active attempt, provider idempotency key where available, timeout/reconcile path and audit link.

**Acceptance evidence**

- QA failure blocks approval; rejection blocks dispatch; approved version changes invalidate approval according to explicit policy.
- Duplicate dispatch/retry cannot create duplicate external publication in adapter contract tests.
- Provider failure/expired token records a recoverable attempt and actionable operator state without exposing provider secrets.
- A test-channel publication is attributable through all lineage records and can be reconciled after a simulated callback outage.

### VF-06 — Reliability, observability, security and operations

**Purpose:** make failures diagnosable, bounded and recoverable before production.

**Implement**

- Propagate trace/correlation IDs from browser request through Control Plane, outbox, stream, worker, artifact and publisher. Emit structured logs, traces and bounded-cardinality metrics.
- Instrument queue depth/age, command latency, provider latency/error rate, render duration/failure, QA pass rate, object upload failures, publication attempts and authenticated mutation rate. Do not put user IDs, prompt text or object keys as high-cardinality metric labels.
- Add bounded retry with jitter, timeout, circuit breaker, workload bulkhead, DLQ record/replay command and an operator-only recovery UI/runbook.
- Document and test backup/restore for Neon data and object metadata, credential rotation, provider outage, worker crash, stalled render and R2 failure. Recovery actions must be auditable.
- Run threat-focused review for auth/session theft, cross-tenant access, prompt injection, malicious upload, SSRF/URL fetch, token leakage and unsafe publication.

**Acceptance evidence**

- One workflow trace follows a synthetic request across services with no secrets in logs.
- DLQ message has cause, attempt count, trace link and controlled replay; replay is idempotent.
- Restore rehearsal proves application compatibility with latest schema and expected artifact manifest.
- Critical alerts have owner, threshold, runbook and test alert outcome.

### VF-07 — CI/CD, infrastructure and release control

**Purpose:** make `staging → production` repeatable, reviewable and reversible at the application level.

**Implement**

- Keep local scripts and GitHub Actions equivalent: lint/type/unit/contract, migration test on disposable Postgres, container build, browser E2E with conforming non-paid adapters, and staging smoke.
- Build immutable Docker images with non-root runtime user, explicit health check, pinned base image digest where practical, minimal runtime dependencies and no baked secret.
- Use Neon pooled runtime URL for application traffic and direct migration URL only for migration jobs. Run Alembic as an explicit release step, never implicit server startup.
- Configure Render services and Vercel only through environment variables/secret stores. Use one free-preview web service only where cost constraints require it; persistent relay/worker topology is a staging/production decision, not silently emulated.
- GitHub Actions requires least permissions, pinned actions, separate staging/production environments, concurrency per target and production approval when the repository plan supports it. If plan limitations prevent platform protections, document compensating manual release approval in the release record.

**Release gates**

| Gate | Staging | Production |
| --- | --- | --- |
| Build, tests, contract/migration checks | required | rerun on release SHA |
| Secrets/dependency review | required | required and unresolved critical finding blocks |
| Database | disposable upgrade | backup verified + forward rehearsal |
| Smoke | health + authenticated synthetic short workflow | same workflow on production-safe test destination |
| Approval | deployer review | independent human release approval |
| Rollback | service image rollback | application compatibility + explicit data-forward plan |

**Acceptance evidence**

- A release record links SHA, image digest, migration revision, deployed config version (never secret values), smoke trace IDs and approver.
- Failed staging deployment does not advance production.
- Redeploying the same SHA is safe; interrupted migration procedure has a documented stop/continue decision.

### VF-08 — Long-form enablement on the same architecture

**Purpose:** extend the proven short pipeline without a database/control-plane rewrite.

**Implement only after VF-04–VF-07 gates pass.**

- Add format profiles (duration range, aspect ratio, bitrate, caption policy, render resource budget) through the existing policy/registry extension point.
- Add a multi-act Planning Document: premise, audience promise, chapters, research/citation packets, recurring visual motifs, transitions and chapter-level approvals.
- Partition long rendering into resumable segments with deterministic joins, shared asset/voice caches and per-segment QA. Preserve a parent workflow and child segment lineage.
- Add chapter navigation, review markers and localized re-render commands; do not add a separate hidden long-form workflow state machine.
- Enforce per-format cost/concurrency budgets and explicit human approval after joined output QA.

**Acceptance evidence**

- A long-form profile adds data/policy/adapter registrations only; existing short contracts continue passing compatibility tests.
- Segment retry changes only the intended segment and preserves final lineage.
- At least one chapter-level failure/re-render/rejoin E2E fixture is reproducible.

### VF-09 — Analytics, cost and continuous improvement

**Purpose:** convert completed delivery data into decisions without contaminating command ownership.

**Implement**

- Build organization-scoped read models from append-only workflow/publication facts. Analytics never updates workflow state.
- Track operational cost: model tokens, asset generation, render CPU/GPU time, storage class/bytes and provider dispatch. Store currency/units precisely and show attribution per workflow.
- Add outcome adapters only after user authorization and platform API review. Normalize provider metrics through an anti-corruption layer; retain source timestamp and collection status.
- Use approved, anonymized/evaluated outcomes to improve prompt evaluation suites. Do not automatically promote prompts based only on vanity metrics.

**Acceptance evidence**

- Dashboard numbers reconcile to source workflow records for a selected time range.
- Access control prevents cross-organization analytics aggregation.
- A cost anomaly alert identifies affected workflow/provider without exposing sensitive prompt/media data.

## 5. Agent execution protocol

1. Read this playbook, Engineering Standards and the phase-specific document before touching code.
2. Declare one bounded task ID, files/modules in scope, interfaces to add/change and its predecessor gate.
3. Inspect existing contracts and migrations before designing an alternative. Preserve unrelated dirty files.
4. Implement from domain/contract inward, then adapter, then transport/UI. Register extensions in one composition root.
5. Add tests for success, invalid input/authorization and retry/recovery. Run the smallest relevant test first, then repository verification.
6. Update ADR when a boundary, persistence protocol, provider, security model or cost model changes.
7. Submit evidence: commit SHA, changed contracts/migration, test output, staging behavior/trace and known limitations.

An agent must stop and request a decision when its task needs a new paid provider, an irreversible data operation, a public external dispatch, a breaking contract or a contradiction between source-of-truth documents.

## 6. Cross-phase completion checklist

- [ ] Contract/API/event schema and migration are additive/versioned.
- [ ] Authorization, organization scope, idempotency, audit and trace ID are proven for every mutation.
- [ ] No worker/Telegram/browser performs direct authoritative PostgreSQL write.
- [ ] Provider/media secrets never appear in client bundle, logs, docs or fixtures.
- [ ] Artifact/prompt/composition/QA/approval lineage is queryable for a selected workflow.
- [ ] Test double follows the same port contract as its production adapter.
- [ ] UI renders backend state and communicates unsupported/partial capability truthfully.
- [ ] Runbook/ADR/release evidence updated as applicable.

## 7. Research basis

- Gemini structured output supports JSON-schema-constrained responses, appropriate for validating AI planning results: [Google Gemini structured outputs](https://ai.google.dev/gemini-api/docs/structured-output?lang=rest).
- R2 lifecycle rules can transition/expire objects by prefix; retention must be designed around durable media classes: [Cloudflare R2 object lifecycles](https://developers.cloudflare.com/r2/buckets/object-lifecycles/).
- OpenTelemetry uses traces, metrics and logs as correlated observability signals: [OpenTelemetry signals](https://opentelemetry.io/docs/concepts/signals/).
- GitHub Actions environments, concurrency and protection rules support controlled staging/production release workflows: [GitHub deployment controls](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/control-deployments).
