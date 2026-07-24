# VisionFlow — Current Product Scope

**Status:** Current implementation baseline as of 2026-07-24
**Purpose:** define what the shipped code supports today. This is not a release acceptance claim; production readiness still requires the evidence gates in [VISIONFLOW_ACCEPTANCE_AND_OPERATIONS_RUNBOOK.md](VISIONFLOW_ACCEPTANCE_AND_OPERATIONS_RUNBOOK.md).

## Product loop

VisionFlow is an organization-scoped AI video-production console. Its primary loop is:

```text
Readiness → brief → creative plan → storyboard → composition → render →
review/approval → publish or schedule → publication history/recovery
```

The Control Plane owns business state in PostgreSQL. The Console uses authenticated APIs; workers perform external work and report results through the Control Plane. Browser clients and workers must not write workflow state directly to PostgreSQL.

## Implemented capability surface

1. **Guided short creation.** The Console provides readiness, brief, AI/manual creative planning, storyboard acceptance and composition hand-off.
2. **Creative and composition state.** Creative documents and composition snapshots can be edited, locked and used to create a render plan.
3. **Media workflow.** The product supports TTS/captions, overlay uploads, private preview URLs and rendered-video review artifacts. R2/S3-compatible object storage is the intended durable media boundary.
4. **AI providers.** Gemini planning and credential-vault managed AI-video providers are exposed through the Control Plane. Current provider support includes fal, Replicate, Kling, Runway, Luma and Minimax. Provider health or configuration is not proof that a generation has succeeded.
5. **Governed publishing.** Review, approval, YouTube OAuth, manual dispatch, retry/reconciliation, publication history and real resumable uploads are implemented. A scheduled timestamp may be supplied for YouTube publishing.
6. **Operations.** The Console has Control Tower, queues, credential vault, workflow progress and failure/history surfaces; backend services include authorization, audit-oriented state transitions, outbox/worker contracts and deployment runbooks.

## Active product boundary

The following are in the current codebase and must be treated as supported *implementation surface*, subject to staging acceptance:

| Capability | Current rule |
| --- | --- |
| Scheduled publishing | Only after an explicit approved workflow transition. The server remains the source of truth for schedule and final provider result. |
| Manual publishing | Requires an approved artifact and a connected destination. A UI action must not claim success before provider confirmation/reconciliation. |
| Calendar and history | Operational views of approved, publishing and posted work; they are not campaign-planning or autonomous publishing authority. |
| AI video generation | Provider keys are resolved server-side from the credential vault. Browser code never handles provider secrets. |
| Long-form/editor expansion | Not an acceptance promise for the current release. The durable short-video path remains the product-critical flow. |

## Deliberately not accepted as complete

The project must not represent any of the following as release-complete until its evidence exists:

- autonomous/batch campaign publishing;
- cross-provider AI-video quality guarantees or cost governance;
- a full non-linear long-form editor;
- analytics/optimization claims based on incomplete publication data;
- production launch without migration, tenant isolation, real render, approval, provider-failure and recovery evidence.

## Release definition

A release is acceptable only when a staging-like environment proves the full short-video loop with real data: create → render → QA → approval → dispatch or schedule → provider result/reconciliation. Unit tests, an attractive Console, or a queued job alone do not satisfy this definition.

## Document precedence

1. This document describes current product scope.
2. `VISIONFLOW_ARCHITECTURE.md` and ADRs define architectural decisions.
3. `VISIONFLOW_ACCEPTANCE_AND_OPERATIONS_RUNBOOK.md` defines release evidence.
4. `VISIONFLOW_PRODUCT_COMPLETION_PLAN.md` is the backlog and may describe unimplemented work; it must not override current implementation facts.
