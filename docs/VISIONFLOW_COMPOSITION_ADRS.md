# VisionFlow Composition Studio — Decisions to Record Before Implementation

This document is an ADR backlog. Convert each accepted item into an immutable file under `docs/adr/` before changing the named boundary.

## ADR-CS-001 — Render-plan compiler is the stable boundary

**Decision:** introduce a provider-neutral `CompositionRenderPlan` between locked snapshots and render engines.

**Options considered:**

1. Continue expanding MoviePy calls directly from raw snapshot JSON.
2. Compile typed render plan, then use Strategy adapters for MoviePy/FFmpeg/GPU.
3. Put all composition logic in the browser.

**Recommendation:** option 2. MoviePy is valuable for existing behavior, but FFmpeg filtergraphs are a more appropriate production execution target for multi-input overlay/audio/transition work. WebCodecs can enhance browser preview but does not replace server-side, reproducible exports.

**Consequences:** adds compiler tests and schema validation now; removes future provider branching from workflow logic.

## ADR-CS-002 — Server preview is authoritative

**Decision:** preview is an asynchronous render job that produces a short-lived object and carries the same plan hash as final render.

**Why:** browser preview varies by codec/device; it cannot prove final render behavior. Browser WebCodecs preview is optional enhancement only.

## ADR-CS-003 — Composition times are timeline-global milliseconds

**Decision:** `timeline_start_ms` and keyframe `time_ms` use global composition time in milliseconds. Clip trim is represented separately by `trim_in_ms` and `duration_ms`.

**Why:** supports cross-track alignment and avoids ambiguous anchoring when clips move. The compiler converts global time to adapter-local time.

**Migration note:** validate all clients use this semantic before adding curve/keyframe UI.

## ADR-CS-004 — Effect registry is versioned and capability-aware

**Decision:** effects are registered server-side with JSON schema, target types, minimum renderer capability, deprecation state, and visual version.

**Why:** a string-only `effect_key` accepts invalid configuration and lets UI claim effects a renderer cannot perform.

## ADR-CS-005 — Collaboration uses optimistic revisions first

**Decision:** V2 uses expected-revision conflict handling plus presence/leases only; no CRDT for binary/timeline state initially.

**Why:** locked, auditable render snapshots are a stronger product requirement than character-level concurrent editing. Revisit CRDT only after evidence of simultaneous-editor demand.

## ADR-CS-006 — Preserve short-form constraints while enabling long-form

**Decision:** keep `FormatProfile` as a strategy with max duration, canvas, render class, preview cap, and validation policy. Do not hard-code 9:16 assumptions into new plan/asset abstractions.

**Why:** V1 remains short-form, but long-form must add an adapter/profile rather than redesign Composition data.
