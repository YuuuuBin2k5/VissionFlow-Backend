# VisionFlow — Agent Skills Catalog and Handoff Cards

**Status:** mandatory companion to [Master Execution Playbook](VISIONFLOW_MASTER_EXECUTION_PLAYBOOK.md)  
**Purpose:** let a new implementation agent take a bounded VisionFlow task without rediscovering architecture, inventing mock behavior or crossing ownership boundaries.

## 1. Universal operating skill

Every agent uses this sequence before implementation:

1. Read [Engineering Standards](VISIONFLOW_ENGINEERING_STANDARDS.md), the Master Playbook and the assigned phase card.
2. Locate the existing contract/use case/port before writing code. Do not duplicate a model, queue consumer or API client.
3. State the task as `VF-XX.NN`, explicit inputs/outputs, owner and non-goals.
4. Make the smallest vertically coherent change: domain/contract → application → adapter → transport/UI.
5. Prove success, unsafe input and recovery with tests. Report only behavior that exists in the running code.
6. Give a handoff containing commit SHA, changed schema/contracts, commands/tests, operational impact and remaining limitation.

### Non-negotiable implementation constraints

- Control Plane alone writes business/workflow records in PostgreSQL.
- External services enter through ports and adapters; do not spread provider SDK calls or `if provider == ...` logic across use cases.
- Every command/mutation is organization-scoped, authorized, idempotent, auditable and traceable.
- Use immutable prompt/creative/composition versions and a locked snapshot for render.
- No browser secret, no worker direct SQL, no background work in an HTTP request, no fake completion/progress in the UI.
- Preserve existing dirty worktree changes unless the assigned task explicitly owns them.

## 2. Role cards

### SK-ARCH — System architect and contract steward

**Owns:** bounded-context map, OpenAPI/event schemas, ADRs, dependency direction and compatibility review.  
**Inputs:** product requirement, existing API/event/migration.  
**Outputs:** additive contract, extension-point decision, ADR if a boundary changes.

**Must check**

- Is the behavior part of Control Plane, Studio, intake adapter, worker or analytics read model?
- Does an existing value object/port already represent it?
- Is the change backward compatible? If not, is a versioned replacement and migration plan present?

**Proof:** schema fixtures accept additive change and reject breaking change; architecture boundary test passes.  
**Never:** move domain policy into a router/component or add a generic shared utility for a single consumer.

### SK-IDENTITY — Authentication, RBAC and tenancy engineer

**Owns:** identity adapter, sessions, organization membership, authorization policies, audit querying.  
**Inputs:** actor/session, organization, requested use case.  
**Outputs:** policy decision and append-only audit fact.

**Implementation pattern:** `IdentityProvider` and `AuthorizationPolicy` ports; repository/UoW for durable state; middleware/decorator only for transport concerns.  
**Proof:** cross-tenant negative tests, session revocation, role downgrade and audit assertions.  
**Never:** rely on frontend route visibility for authorization or expose signing/encryption material to Studio.

### SK-AI — Creative agent and Gemini integration engineer

**Owns:** `AiPlanningProvider`, structured input/output schema, prompt execution command, error/cost normalization.  
**Inputs:** immutable brief + prompt version + provider config reference.  
**Outputs:** validated Creative Document version or explicit failure.

**Implementation pattern:** Strategy/Adapter for model providers; Command/Outbox for model call; Specification for schema/content policy; Anti-Corruption Layer for provider response.  
**Proof:** valid schema fixture, malformed output, timeout, duplicate command and provider-unavailable tests.  
**Never:** call Gemini from the browser, persist raw unvalidated response as a plan, or silently use a different prompt/model.

### SK-PROMPT — Prompt registry and evaluation engineer

**Owns:** immutable template versions, variable schema, approval/promotion, rollback pointer, evaluation fixtures and audit history.  
**Inputs:** template draft, model config, evaluation set.  
**Outputs:** a versioned prompt reference safe for workflow pinning.

**Proof:** prior run stays bound to old version after promotion; unauthorized promotion fails; evaluation evidence is retained.  
**Never:** edit a promoted version in place or encode prompt business rules solely in UI text.

### SK-ASSET — Asset, rights and brand supply-chain engineer

**Owns:** `AssetStore`, signed upload/finalize flow, provenance, rights policy, brand-kit versioning and storage lifecycle manifest.  
**Inputs:** permitted upload/generated asset and organization scope.  
**Outputs:** verified `MediaAsset` with durable object key/checksum/rights.

**Implementation pattern:** Adapter for R2/S3; Specification for eligibility; temporary-to-promoted object transaction/saga.  
**Proof:** invalid type/size/checksum, cross-org key, expired/unknown rights, worker re-read after restart.  
**Never:** trust client-provided metadata, use local worker path as durable reference, or let lifecycle expiry delete active evidence without policy review.

### SK-COMPOSITION — Studio timeline and creative editor engineer

**Owns:** Creative-to-Composition UI, timeline commands, immutable locking, capability labels and accessible editing.  
**Inputs:** Creative Document, eligible assets, current composition version.  
**Outputs:** persisted draft or locked Composition Document reference.

**Read first:** [Composition next phases](VISIONFLOW_COMPOSITION_NEXT_PHASES.md) and [Composition agent playbook](VISIONFLOW_COMPOSITION_AGENT_PLAYBOOK.md).  
**Proof:** server reload, stale lock conflict, unauthorized edit, keyboard/reduced-motion behavior and no placeholder preview presented as output.  
**Never:** fabricate timeline/render state locally or implement a renderer in React.

### SK-RENDER — Render Plan and media-engine engineer

**Owns:** Composition compiler, effect registry, renderer adapter, deterministic fixture rendering, artifact validation and cancellation.  
**Inputs:** locked composition plus asset manifest.  
**Outputs:** normalized Render Plan and validated artifact result command.

**Implementation pattern:** Compiler + Registry + Adapter; command handler; resource bulkhead; temporary artifact promotion.  
**Proof:** order/timing/transform/effect fixture differences, failed encode, cancellation, worker restart and checksum validation.  
**Never:** allow a renderer to mutate workflow tables, reinterpret a draft instead of locked snapshot, or report preview parity without a defined capability level.

### SK-QA — Media QA and human-review engineer

**Owns:** versioned `QaPolicy`, rule findings, review queue, approval/rejection policy and signed preview authorization.  
**Inputs:** artifact checksum, format/brand/rights policy.  
**Outputs:** `QaReport` and immutable reviewer decision.

**Implementation pattern:** Specification composite for rules; policy object for approval invalidation.  
**Proof:** QA failure blocks approval; changed relevant input invalidates decision; findings point to exact rule/version.  
**Never:** make QA a visual badge only or permit approval on artifact whose checksum does not match report.

### SK-PUBLISH — Publisher adapter engineer

**Owns:** per-platform `PublisherAdapter`, credential vault interface, dispatch/reconcile command and provider payload mapping.  
**Inputs:** approved locked artifact and explicit authorized dispatch request.  
**Outputs:** attempt record, external reference/status or recoverable failure.

**Implementation pattern:** Adapter + Anti-Corruption Layer + idempotent Command; state machine for attempts.  
**Proof:** duplicate dispatch, expired credentials, timeout/callback outage, test destination and reconciliation tests.  
**Never:** auto-publish merely because render succeeded or place unencrypted provider credentials in database/API response.

### SK-RELIABILITY — Queue, recovery and observability engineer

**Owns:** outbox relay, Redis consumer behavior, retry/DLQ/replay, tracing, metrics, alerts and operational runbooks.  
**Inputs:** command envelopes and service behavior.  
**Outputs:** correlated telemetry and safe recovery controls.

**Implementation pattern:** Transactional Outbox, Command Handler, retry/circuit-breaker decorator, bulkhead and operator-only replay use case.  
**Proof:** crash before/after acknowledgement, poison message, duplicate delivery, trace continuity and bounded metric labels.  
**Never:** ack before durable result, retry forever, or log secrets/media/prompt bodies.

### SK-RELEASE — CI/CD, Docker and platform engineer

**Owns:** local verification parity, Dockerfiles, GitHub Actions, Render/Vercel manifests, migration command and staging/production runbooks.  
**Inputs:** deployable service, environment-variable names, health endpoint and migration revision.  
**Outputs:** immutable build plus release evidence.

**Proof:** fresh build, non-root container, health/readiness, disposable migration upgrade, staging synthetic workflow and no secret in build logs/image layers.  
**Never:** run migrations automatically on every web startup, treat free-preview topology as production worker architecture or paste secret values into version control.

### SK-LONGFORM — Long-form extension engineer

**Owns:** format profiles, multi-act/chapter plan, segment lifecycle, join strategy and chapter review UI.  
**Inputs:** existing proven short-form contracts.  
**Outputs:** format extension and parent/child workflow lineage.

**Proof:** short-form compatibility suite remains green; segment rerender/join fixture works; resource budget enforced.  
**Never:** make a parallel long-form database/workflow system or start this work before short pipeline/reliability exit gates.

### SK-ANALYTICS — Analytics and cost-read-model engineer

**Owns:** organization-scoped read models, cost normalization, provider metrics normalization and evaluated improvement signals.  
**Inputs:** append-only operational facts.  
**Outputs:** queryable dashboards/reports that do not affect workflow state.

**Proof:** reconciliation with source facts, cross-tenant denial and cost anomaly drill.  
**Never:** update business state from analytics, store sensitive prompt/media in metric labels, or automatically promote prompts from a single engagement metric.

## 3. Task handoff template

Copy this block into a task before assigning it to an implementation agent.

```md
## VisionFlow task: VF-<phase>.<number> — <short outcome>

### Scope
- Owner role: SK-<role>
- Phase/predecessor gate: VF-<phase>; requires <evidence>
- In scope: <bounded behavior and modules>
- Explicitly out of scope: <nearby work to avoid>

### Existing source of truth
- Contracts/use cases/ports: <absolute repository paths or symbols>
- Database/migration owner: <path>
- UI/API/event consumers: <paths>

### Required design
- Domain invariant:
- Extension point/pattern:
- Idempotency/auth/audit/trace behavior:
- Failure and compensation behavior:

### Acceptance tests
1. Happy path:
2. Validation/authorization failure:
3. Retry/restart/recovery:
4. Contract or browser behavior:

### Handoff evidence
- Commit SHA:
- Changed contracts/migrations:
- Commands + results:
- Staging trace or fixture:
- Known limitation / next dependency:
```

## 4. Review checklist for the lead agent

Reject or return a task when any answer is missing:

| Question | Required answer |
| --- | --- |
| Who owns the state? | Control Plane aggregate/use case, not a UI/worker/adapter |
| What can vary later? | named port/strategy/registry with one composition-root registration |
| What happens on duplicate delivery? | idempotency key + durable dedupe/attempt policy |
| What happens on crash/timeout? | bounded retry, terminal state/DLQ and operator action |
| Can another organization access it? | application policy and scoped query test |
| Can we reproduce output? | immutable versions, asset checksums and Render Plan hash |
| Does UI claim too much? | capability status and API-backed state only |
| How is it released? | migration, test/smoke and rollback/forward plan |

## 5. Recommended division of concurrent work

Parallelization is allowed only where rows have no shared migration/contract ownership. The technical lead serializes changes to a shared schema or event envelope.

| Lane | May run together | Synchronization point |
| --- | --- | --- |
| A: contracts/foundation | VF-00 | publish schema baseline before consumers |
| B: identity/audit | VF-01 | merge org context before other mutations |
| C: AI/prompt | VF-02 | consume published Creative Document schema |
| D: asset/brand | VF-03 | consume org policy; publish asset manifest |
| E: composition/render | VF-04 | waits for Creative/asset contracts; detailed CS sequence internal |
| F: QA/publish | VF-05 | can design ports early; integration waits for artifact lineage |
| G: reliability/release | VF-06/VF-07 | instrumentation hooks merge with each lane; release gate last |
| H: long-form/analytics | VF-08/VF-09 | design only until V1 gates pass |

## 6. Evidence format at phase exit

The lead records the following in the phase PR/release note:

1. completed task IDs and immutable commit SHAs;
2. contract versions, migration revisions and compatibility result;
3. test commands/results, including negative/recovery cases;
4. staging workflow ID, trace ID and artifact/QA evidence where applicable;
5. operational changes: environment-variable names, dashboards, alerts, runbooks;
6. deliberately deferred capability and the next phase that owns it.

An agent has completed a task only after this evidence exists. A merged UI without an API contract, an adapter without recovery tests, or a document without executable acceptance checks is not a completed task.
