# VisionFlow Composition Studio — Agent Playbook

Use this file to split work among agents without creating incompatible implementations.

## 1. Non-negotiable guardrails

- Read `VISIONFLOW_ENGINEERING_STANDARDS.md` and `VISIONFLOW_COMPOSITION_NEXT_PHASES.md` before coding.
- Work in one bounded slice. Do not refactor legacy Telegram/MySQL modules while changing Composition Studio.
- Never add UI state that cannot be persisted or rendered by a backend contract.
- Never alter a locked version. Every edit is a new draft revision with optimistic concurrency.
- Do not push secrets, `.env`, R2 URLs, Neon URLs, or raw provider responses.
- Commit only scoped files after relevant tests; preserve unrelated dirty worktree files.

## 2. Skill cards

### Skill: Composition domain and migrations

**Owns:** `services/control-plane/app/domain`, `application`, `infrastructure`, Alembic, route DTOs.

**Input:** approved ADR/phase item, exact invariants, expected API examples.

**Procedure:**

1. Model the invariant in a domain policy/value object first.
2. Add append-only migration with FK, unique constraints, query-path index, and downgrade policy.
3. Add repository port and SQLAlchemy adapter; no SQLAlchemy in router.
4. Add FastAPI DTO validation and stable error mapping.
5. Write unit + repository/route contract tests for authorization, tenancy, stale revision, and lock behavior.

**Done when:** migration rehearses against disposable PostgreSQL; tests pass; OpenAPI change documented.

### Skill: Render-plan compiler

**Owns:** `worker/domain`, `worker/application`; does not directly edit FastAPI routers.

**Procedure:**

1. Receive a locked composition DTO from the Control Plane client.
2. Validate exact schema and effect registry version.
3. Produce canonical, deterministic JSON and hash it.
4. Map to typed provider-neutral operations.
5. Add a provider adapter capability matrix; unsupported operations fail before an expensive render.

**Required tests:** deterministic hash, unknown effect rejected, same source snapshot same plan, missing asset/reference error, correct timeline ordering.

### Skill: FFmpeg render adapter

**Owns:** render provider only.

**Procedure:**

1. Translate typed plan into a safely escaped `filter_complex` graph.
2. Use `ffprobe` to validate source duration/codecs before rendering.
3. Render to temporary workspace/output key; validate duration/checksum; atomically upload/promote.
4. Emit provider version, command redacted of secrets, input checksums, and plan hash.

**Prohibitions:** string concatenation of unvalidated user filter expressions; paths outside ephemeral workspace; running ffmpeg from API server.

### Skill: Studio interaction and accessibility

**Owns:** `ClientAgent/src/components/CompositionStudio*`, API client DTOs, frontend unit/E2E tests.

**Procedure:**

1. Represent edits as typed commands, not direct scattered React state mutation.
2. Maintain local undo/redo stack; snapshot only on successful server revision.
3. Debounce autosave; surface conflict and offline states.
4. Add pointer interaction plus keyboard equivalent and live announcement.
5. Verify focus order, keyboard commands, and 200% zoom manually and with browser E2E.

**Prohibitions:** native drag/drop as the only interaction; `any`; fake preview status; silently swallowing HTTP 409.

### Skill: Preview and QA workflow

**Owns:** preview command, worker job, R2 temporary object policy, Studio preview component.

**Procedure:**

1. Create async preview command with idempotency key and range/quality validation.
2. Restrict maximum length/resolution and assign preview queue class.
3. Persist preview linkage to `composition_version_id` and `render_plan_hash`.
4. Return signed, short-lived URL only after checksum verification.
5. Expire objects via R2 lifecycle and display typed expiry state.

## 3. Suggested task decomposition

| Task ID | Agent role | Files/surface | Dependency | Exit evidence |
| --- | --- | --- | --- | --- |
| CS-01 | domain agent | effect registry + migration | none | route tests + migration rehearsal |
| CS-02 | worker agent | typed render-plan compiler | CS-01 | deterministic plan/hash tests |
| CS-03 | render agent | FFmpeg overlay/audio adapter | CS-02 | golden-media integration fixture |
| CS-04 | frontend agent | command history + keyboard model | none | browser tests, no API mock |
| CS-05 | workflow agent | preview job/outbox/worker | CS-02 | preview lifecycle integration test |
| CS-06 | QA/reliability agent | staging E2E/runbook | CS-03, CS-05 | smoke evidence and failure drills |

Only CS-01/CS-04 can safely run in parallel initially. CS-02 waits on the registry contract; CS-03 and CS-05 wait on the typed plan.

## 4. PR / commit template

```md
## Composition slice
- Task: CS-XX
- Invariant protected:
- Public contract / migration:
- Renderer capability affected:
- Tests run:
- Staging evidence:
- Rollback / compatibility:
```

## 5. Review checklist

- [ ] Organization scope is enforced at every read/write.
- [ ] Expected revision is present on edits/locks.
- [ ] Locked snapshot is immutable and referenced by render output.
- [ ] Unsupported provider capability fails explicitly.
- [ ] All pointer actions have keyboard alternatives.
- [ ] Preview/full render cannot run in the API process.
- [ ] New media object has rights metadata, checksum, and cleanup policy.
- [ ] No accidental legacy database write or secret exposure.
