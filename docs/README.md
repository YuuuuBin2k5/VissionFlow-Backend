# VisionFlow Documentation

**Current implementation baseline:** [VISIONFLOW_V1_SCOPE.md](VISIONFLOW_V1_SCOPE.md)  
**Release gate:** [VISIONFLOW_ACCEPTANCE_AND_OPERATIONS_RUNBOOK.md](VISIONFLOW_ACCEPTANCE_AND_OPERATIONS_RUNBOOK.md)

## Read in this order

1. [Current Product Scope](VISIONFLOW_V1_SCOPE.md) — implemented product surface and explicit non-claims.
2. [Architecture](VISIONFLOW_ARCHITECTURE.md) — Control Plane, workers, media, tenancy and workflow boundaries.
3. [UI System](VISIONFLOW_UI_SYSTEM.md) — Prism Flow design rules and accessibility/performance constraints.
4. [Acceptance and Operations Runbook](VISIONFLOW_ACCEPTANCE_AND_OPERATIONS_RUNBOOK.md) — the evidence required before a release is called ready.

## Reference groups

| Group | Documents |
| --- | --- |
| Product and execution | `VISIONFLOW_PRODUCT_COMPLETION_PLAN.md`, `VISIONFLOW_DELIVERY_PLAN.md`, `VISIONFLOW_MASTER_EXECUTION_PLAYBOOK.md`, `VISIONFLOW_COMPOSITION_NEXT_PHASES.md` |
| Deployment and operations | `VISIONFLOW_STAGING_RUNBOOK.md`, `VISIONFLOW_RENDER_DEPLOYMENT.md`, `VISIONFLOW_PUBLISHER_DEPLOYMENT.md`, `VISIONFLOW_YOUTUBE_PUBLISHER_ACTIVATION.md`, `VISIONFLOW_R2_OVERLAY_STAGING.md` |
| Migration | `VISIONFLOW_POSTGRES_CUTOVER_ASSESSMENT.md`, `POSTGRES_CUTOVER_PLAN.md`, `CUTOVER_RUNBOOK.md`, `adr/` |
| Legacy context | `VISIONFLOW_LEGACY_*`, `ARCHITECTURE.md`, `DEPLOYMENT.md`, `MULTI_USER_CONNECTIONS.md` |

## Maintenance rules

- Update `VISIONFLOW_V1_SCOPE.md` in the same change set as any material capability expansion or removal.
- Keep roadmap documents future-facing; never use them as evidence of a deployed feature.
- Link to the authoritative document instead of duplicating workflow states, provider lists, release claims or API contracts.
- Mark an unknown, blocked or unverified state explicitly; do not use mock UI or a successful HTTP request as proof of production completion.
