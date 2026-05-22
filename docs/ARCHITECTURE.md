# Architecture

## Direction

This project is a multi-platform social video automation system. It should evolve as a modular monolith inside a monorepo first, with clear module boundaries that make future microservice extraction possible.

The current target architecture is:

```text
Telegram Bots
  -> Intent Router
  -> Job / Campaign Core
  -> Queue + Scheduler
  -> Render Worker
  -> Publish Targets
  -> Platform Publisher Adapters
```

## Why Modular Monolith First

The system is still changing quickly: TikTok publishing, YouTube publishing, render quality, scheduling, and natural-language command handling are all active product areas. A modular monolith keeps local development, debugging, and refactoring fast while the correct long-term service boundaries become clearer.

Microservices should be introduced only when there is a concrete operational reason, such as:
- render workloads blocking bot responsiveness
- TikTok browser automation needing isolated restarts
- independent scaling of render/publish workers
- multiple developers owning separate runtime services
- deployment or reliability needs that cannot be solved within the modular monolith

## Core Modules

### Bots

Telegram bots are thin controllers. They should:
- receive chat messages
- route through intent parsing
- show previews and confirmations
- enqueue jobs or confirmed actions

They should not render videos, upload videos, or own platform business rules.

### Intent

The intent layer converts natural language into structured actions. Platform detection belongs here when the user says TikTok, YouTube, Shorts, or similar platform-specific words.

### Jobs and Scheduler

`video_pipeline_jobs` is the shared video job record. It owns render state and shared metadata.

The scheduler decides when jobs or publish targets become due and enqueues work. It should not directly upload videos.

### Publish Targets

`publish_targets` stores platform-specific publish state:
- platform
- scheduled publish time
- title/description/tags
- privacy status
- external video id/url
- platform-specific failure state

This allows one rendered video to be published to multiple platforms without duplicating render work.

### Publishers

Platform publishers are adapters:
- TikTok uses the existing browser automation path.
- YouTube uses the YouTube Data API/OAuth path.

Future platforms should follow the same pattern.

## Current Runtime Shape

```text
orchestrator
  Node.js / TypeScript
  Telegram bots
  BullMQ queue
  scheduler
  MySQL access

worker
  Python render/media pipeline
  TikTok browser publisher path

infrastructure
  MySQL
  Redis
  local filesystem media outputs
```

## Future Extraction Path

If the project outgrows one runtime process, extract in this order:

1. Render worker
2. Publish worker
3. Telegram bot service
4. Scheduler service
5. Orchestrator API

Use the Strangler Fig approach: keep the old path running, move one capability at a time, and retire old code only after the new service is proven.

## Repository Rules

- Keep all TikTok and YouTube code in this monorepo.
- Keep shared behavior in core modules.
- Keep platform behavior behind adapters.
- Keep secrets out of Git.
- Use migrations for database changes.
- Use queue-driven execution for heavy or side-effectful work.
