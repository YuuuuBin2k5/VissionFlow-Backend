# AGENTS.md

## Architecture Contract

This repository uses a modular monolith monorepo architecture for a multi-platform social video automation system.

Do not introduce microservices, new repositories, or standalone apps unless the user explicitly asks for that architectural change.

Core direction:
- Shared orchestration, scheduling, intent parsing, queueing, database access, approval flow, logging, and render pipeline stay in the core.
- Platform-specific behavior must live behind adapters or platform-specific bot entrypoints.
- TikTok and YouTube must not duplicate core job/render/scheduler logic.

## Module Boundaries

- `orchestrator/src/telegram`: Telegram bot entrypoints and thin chat controllers.
- `orchestrator/src/telegram/intentRouter.ts`: natural-language intent parsing.
- `orchestrator/src/queue`: BullMQ queue integration and worker dispatch.
- `orchestrator/src/scheduler`: scheduling and due-job scans.
- `orchestrator/src/services`: external platform/API services and publishing adapters.
- `orchestrator/src/database`: database helpers and repositories.
- `orchestrator/prisma`: schema and migrations.
- `worker`: Python media/render/publish worker.
- `shared`: assets/types/config shared across runtime layers.

## Publisher Rule

All platform publishing must go through a platform adapter/service.

Allowed:
- TikTok publish logic stays in the TikTok publisher/browser automation path.
- YouTube publish logic stays in the YouTube API publisher path.
- Future platforms should add adapters such as Facebook, Instagram, or Threads.

Not allowed:
- Calling TikTok/YouTube APIs directly from bot handlers.
- Rendering video directly inside Telegram bot handlers.
- Duplicating scheduling, approval, or job-state logic per platform.

## Data Model Rule

Use `video_pipeline_jobs` for shared video/render state.
Use `publish_targets` for platform-specific publish state.

Do not add platform-specific publish columns directly to `video_pipeline_jobs` unless there is a documented migration reason.

## Bot Rule

Bots are thin controllers:
- parse message
- resolve intent/action
- show preview/confirmation
- enqueue work

Bots must not:
- render video directly
- upload directly
- own platform business logic
- bypass queue or approval flow for publish actions

## Security Rule

Never commit secrets.

Do not commit:
- `.env`
- OAuth refresh tokens
- Telegram bot tokens
- Google API keys
- Chrome profiles/cookies
- generated media outputs

Only document required variables in `.env.example`.

## Required Checks

Before finishing code changes in `orchestrator`, run:

```bash
npx tsc --noEmit
```

If generated runtime code is needed, also run:

```bash
npx tsc
```

For Python worker changes, at minimum run a syntax check on changed Python files.
