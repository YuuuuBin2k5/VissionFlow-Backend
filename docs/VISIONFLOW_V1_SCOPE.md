# VisionFlow — V1 Scope Freeze

**Status:** Final scope before implementation
**Product release:** V1 Short-form Studio
**Operating model:** one creator brief → one auditable short-video workflow run

## Non-negotiable data platform

VisionFlow V1 and production use **PostgreSQL on Neon as the only system of record**. MySQL is a legacy source for one-time export/reconciliation only; no MySQL table, direct `pymysql` access, Prisma MySQL writer, campaign record or scheduler state is part of the VisionFlow runtime.

- Running services use Neon's pooled `DATABASE_URL` with SSL required.
- Alembic migration jobs use a separate direct `MIGRATION_DATABASE_URL`; application services never run schema creation at startup.
- Local development uses PostgreSQL too, so SQL semantics, JSONB, constraints, UTC timestamps and migrations match staging/production.
- The first data implementation phase creates the PostgreSQL schema and repository layer before any legacy endpoint/worker is ported.

## Included in V1

1. Create a short-form video from one explicit brief in Studio or Telegram.
2. Run Brief Analysis, Script and Storyboard as separate, inspectable workflow steps with pinned prompt versions.
3. Collect/generate permitted assets, TTS, captions and a vertical render from the resulting timeline.
4. Store source/derived/final media in R2 and present a signed preview.
5. Run automated QA, then require a human approval before publication.
6. Allow an operator to manually dispatch one approved video to one connected test/production channel and inspect the real result.
7. Provide prompt administration, audit trail, retry/cancel where safe, failure diagnosis and operational readiness.

## Explicitly excluded from V1

| Excluded capability | Reason | Earliest reconsideration |
| --- | --- | --- |
| 30-day plans, content campaign batches and mass job generation | Optimizes volume before the single-video quality/reliability loop is proven | After V1 quality and cost targets are met |
| Automatic posting calendar and scheduler | Creates a second policy surface before publication reliability is established | V1.1 |
| Auto-publish / autonomous release | Conflicts with mandatory human review and increases channel/account risk | After audited approval reliability is proven |
| Multi-account bot fleet and proxy/stealth controls | Not part of a governed video-production core | Separate compliance review |
| Long-form rendering UI and execution | Larger product, compute and QA scope | V2, using V1 contracts |
| Advanced analytics, optimization agent and automated feedback loop | Requires trustworthy publication data first | V1.1 or later |
| WebGL/WasM in the authenticated work loop | Adds performance/maintenance risk without improving core task completion | Only after measured user need |

## Legacy removal list

During Phase 0/3, remove or retire the legacy paths below instead of porting them into VisionFlow:

- `worker/application/planning_use_case.py` and the `generate_30_day_plan` flow.
- Telegram campaign commands and campaign-specific job creation.
- `startAutoScheduler` and automatic scheduled publication flow.
- Legacy `ChannelsCampaign`, `campaign_id`, `day_number`, MySQL/Prisma writer configuration and auto-publish state as canonical concepts in the new PostgreSQL model.
- UI surfaces that imply a calendar, autonomous dispatch or unverified analytics before a V1 backend contract exists.

The removal happens only after the replacement on-demand workflow has passed staging. No legacy campaign state is migrated into the new V1 production schema.

## V1 success boundary

V1 is complete when an operator can repeatedly create, inspect, render, QA, approve and manually publish a **single short video** without direct database changes, local Docker spawning or fictional UI state. It is not complete merely because it can generate a large batch of videos.
