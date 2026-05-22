## Summary

What changed and why?

## Architecture Checklist

- [ ] Change keeps the modular monolith structure.
- [ ] Shared job/render/scheduler logic was not duplicated in platform bots.
- [ ] Platform publish behavior goes through publisher adapters/services.
- [ ] Shared video state remains in `video_pipeline_jobs`.
- [ ] Platform publish state uses `publish_targets`.
- [ ] Heavy or side-effectful work is queued instead of run directly in bot handlers.
- [ ] No secrets, tokens, cookies, generated media, or profiles were committed.

## Verification

- [ ] `npx tsc --noEmit` passes for orchestrator changes.
- [ ] Python syntax check passes for changed worker files.
- [ ] Relevant bot command or intent scenario was tested.
