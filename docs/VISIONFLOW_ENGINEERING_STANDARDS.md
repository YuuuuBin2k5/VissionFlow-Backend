# VisionFlow — Engineering Standards

**Status:** Mandatory for every production change
**Applies to:** Studio, Control Plane, Telegram intake, workers, infrastructure, migrations and automation

## 1. Non-negotiable principles

1. **Domain first:** business rules belong to the domain/application layer, never to React components, Telegram handlers, SQL strings or provider SDK callbacks.
2. **Dependency inversion:** application services depend on ports (interfaces/protocols); infrastructure implements those ports. Dependencies point inward.
3. **Open for extension, closed for modification:** adding an AI provider, render engine, channel, format profile or storage provider adds an adapter/strategy and registration entry. It must not require editing unrelated workflow logic or a growing `if/elif` chain.
4. **One authoritative writer:** only the Control Plane owns workflow and business-state writes in PostgreSQL. Adapters and workers submit typed commands/results; they never patch tables directly.
5. **Explicit failure:** retries, timeouts, cancellation, idempotency and compensation are designed at the command boundary. No silent fallback may publish, lose a job or hide a provider error.
6. **Secure by default:** secrets, credentials, signed URLs and internal service tokens never reach the browser or logs.
7. **Observable by default:** a request or command cannot cross a service boundary without a correlation/trace identifier.

## 2. Required architecture shape

Each deployable module uses Clean/Hexagonal Architecture:

```text
transport / framework adapters
        ↓
application use cases and ports
        ↓
domain entities, value objects and policies
        ↑
infrastructure adapters (PostgreSQL, Redis, R2, LLM, render, platform APIs)
```

### Dependency rules

- Domain code imports no FastAPI, SQLAlchemy, React, Redis, HTTP client, cloud SDK or environment module.
- Application code imports domain and port definitions only; it does not construct clients or read environment variables.
- Infrastructure implements ports and is wired in exactly one composition root per service.
- Transport only authenticates, validates DTOs, invokes a use case and maps result/error to HTTP, Telegram or event responses.
- A module cannot import another module's repository or table model. Cross-module work is performed by a public application interface or domain event.
- New shared code goes in a small `packages/contracts` or `packages/kernel` package only when it has at least two stable consumers. Do not create a generic `utils` dumping ground.

These rules are checked in CI with Python import-boundary tests and TypeScript dependency-cruiser rules. Violations fail the pull request.

## 3. SOLID and pattern selection

| Need | Required design | Example in VisionFlow | Prohibited shortcut |
| --- | --- | --- | --- |
| New provider/channel/render engine | Strategy + Adapter + Factory/registry | `RenderProvider`, `SpeechProvider`, `PublisherAdapter`, `AssetStore` | Provider-specific branches across routers/workers |
| Durable asynchronous work | Command + Handler + Outbox + idempotency policy | `RequestRender`, `RunPromptEvaluation`, `DispatchPublication` | Calling long work synchronously from an API request |
| Workflow lifecycle | State machine + transition policy | Only QA-passed `RENDERED` export can move to `APPROVAL_PENDING` | Writing arbitrary status strings from multiple services |
| Cross-service failure | Saga-style compensation and retry policy | Failed R2 upload cleans incomplete metadata; failed publish records a recoverable attempt | Best-effort multi-service updates with no reconciliation |
| Database access | Repository + Unit of Work | `WorkflowRunRepository` behind a transaction-scoped port | SQL or ORM calls in controller, agent or UI code |
| External API mismatch | Anti-Corruption Layer | TikTok/YouTube metrics map to VisionFlow analytics vocabulary | Provider payload leaking through public APIs |
| Configurable rules | Specification/Policy objects | QA rules, rights checks, publish eligibility | Boolean-flag explosion in one service |
| Shared concerns | Decorator/Middleware | tracing, structured logs, rate limits, retries, circuit breakers | Repeating `try/catch`, logging and metrics in every handler |

Patterns are tools, not ceremony. A pattern is added only when it isolates a genuine axis of change or failure; its purpose is recorded in an ADR.

## 4. Domain modeling rules

- Use immutable value objects for identifiers, prompt references, media keys, time windows, duration, aspect ratio and money/cost values.
- Aggregates enforce invariants: `WorkflowRun` owns state transitions; `PromptTemplate` owns version promotion; `PublicationAttempt` owns delivery retry state.
- Use domain events only for facts that occurred, named in past tense: `RenderRequested`, `QaPassed`, `ExportApproved`, `PublicationFailed`.
- Commands express intent and carry an idempotency key. Events are append-only; an updated state is never represented by mutating a past event.
- Time is UTC in persistence and events. A user timezone belongs to a project/channel preference and is converted at the presentation boundary.
- File paths are forbidden in domain data. Store a provider-neutral `MediaObjectKey` and metadata; the R2 adapter resolves it.
- Store prompt content as immutable versions. A run references the exact prompt version and model configuration that produced it.

## 5. API, event and schema discipline

- Public HTTP uses OpenAPI-first contracts under `/api/v1`; additive changes are compatible, breaking changes require a new version.
- All mutation endpoints require authentication, authorization, an idempotency key and audit metadata.
- Error responses use a stable problem format with `code`, `message`, `trace_id` and safe actionable detail. Stack traces and provider secrets are never returned.
- Event envelopes are versioned. Consumers must ignore unknown additive fields and reject unknown major versions into the dead-letter stream.
- Database migrations are append-only, reviewed, reversible at the application level and tested on a disposable PostgreSQL database. Never run schema auto-creation at production startup.
- Every index has a documented query path. Every foreign key, uniqueness rule and state constraint expresses a domain invariant.

## 6. Reliability and operational patterns

| Risk | Mandatory control |
| --- | --- |
| Duplicate delivery/retry | Idempotency key, unique constraint, consumer deduplication and provider delivery key where available |
| Slow/unavailable provider | Explicit timeout, bounded retry with jitter, circuit breaker, fallback only if policy permits |
| Worker crash | Ack after durable result commit, visibility/pending-message recovery and resumable workflow step |
| Poison message | Dead-letter stream, reason, trace link and operator replay command |
| Resource exhaustion | Per-provider concurrency limits, queues by workload class, GPU/CPU bulkheads and input-size limits |
| Partial media output | Upload to temporary key, checksum, atomically promote metadata only after validation |
| Incorrect publication | QA gate, human approval, one active publication attempt and immutable audit record |

Render worker tasks must be finite, cancellable and use ephemeral scratch space. The only durable output is an R2 object verified by checksum.

## 7. Testing standards

| Layer | Required tests |
| --- | --- |
| Domain | Fast unit tests for value objects, policies and valid/invalid state transitions |
| Application | Use-case tests with fake ports, including authorization, idempotency and compensation |
| Infrastructure | PostgreSQL repository tests, Redis/R2/provider adapter contract tests in disposable environments |
| Contracts | OpenAPI client/server compatibility and event schema validation |
| Integration | Outbox-to-stream, worker result callback, migration upgrade and recovery paths |
| End-to-end | Login, short project creation, prompt promotion, render request, QA rejection, approval and test-channel publication |
| Non-functional | Security scanning, migration rehearsal, worker restart, queue backpressure and critical API load test |

No production E2E test may call paid model/render APIs or real public channels. Test doubles must conform to the same port contract as production adapters.

## 8. Security and data standards

- Enforce RBAC at the application policy layer and scope every record by organization.
- Passwords use Argon2id; refresh sessions are revocable; owner/admin MFA is required before public production access.
- Secrets live only in Render secret groups or approved local secret stores. CI uses GitHub environment secrets with minimum permissions.
- Encrypt third-party tokens, limit signed URL TTLs, and restrict R2 uploads by content type, size and object prefix.
- Validate untrusted text, JSON, URL, file type and media duration at the boundary. Treat LLM output as untrusted structured input.
- Maintain an audit trail for login, prompt/version changes, approvals, credential use, publication and operator replay actions.
- Run dependency review and secret scanning on every pull request; pin GitHub Actions to verified full commit SHAs.

## 9. Definition of Done

A change is complete only when it has all applicable items below:

- Clear domain owner, use case and extension point; no breach of dependency rules.
- Contract/schema migration reviewed and versioned when the external behavior changes.
- Unit, contract and integration tests cover the happy path, validation failure and retry/recovery path.
- Idempotency, authorization, audit event, timeout and observability attributes are present for every mutation or command.
- Structured logs contain the trace/workflow identifiers and no secrets or user media contents.
- Documentation, runbook and ADR are updated for an architectural decision or operational behavior change.
- CI, staging smoke tests and security scans pass. Production changes also pass the rollback/forward-compatibility review.

## 10. Architecture Decision Record (ADR) policy

Create a short ADR before any change that alters a service boundary, persistence model, queue protocol, security mechanism, provider contract, public API major version or cost model. Each ADR states context, decision, alternatives, consequences, migration and rollback plan.

ADR filenames use `docs/adr/NNNN-short-decision.md`. Approved ADRs are immutable; a later decision supersedes rather than edits the old record.
