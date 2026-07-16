# VisionFlow Stream B Legacy Intake Contract

## Scope and activation

This is a new, isolated route from the Control Plane to the legacy MySQL
orchestrator. It does not change `bot.ts`, `botActions.ts`, YouTube bots, or
any Telegram-created job. The consumer is intentionally not imported by
`orchestrator/src/main.ts` until its deployment gate is approved.

## Signed Redis envelope

Only `visionflow.legacy_job.requested.v1` is accepted. The Control Plane signs
the following canonical JSON object using HMAC-SHA256 with sorted keys and no
whitespace:

```json
{
  "aggregate_id": "uuid",
  "aggregate_type": "workflow_run",
  "event_id": "uuid",
  "event_type": "visionflow.legacy_job.requested.v1",
  "payload": {},
  "trace_id": "32 lowercase hex"
}
```

The stream entry adds `signature_key_id` and hexadecimal `signature`. The
consumer accepts `VISIONFLOW_INTAKE_HMAC_KEY` and, during rotation only,
`VISIONFLOW_INTAKE_HMAC_KEY_PREV`; both keys have explicit key IDs. Signature
comparison uses Node `timingSafeEqual`.

Invalid signatures, unknown key IDs, invalid UUIDs, and duplicate source
commands with different ownership are written to the DLQ before the original
message is acknowledged. Transient database/network errors are left pending.

## MySQL transaction boundary

One serializable transaction creates:

1. an on-demand `video_pipeline_jobs` record (`day_number=0`, immediate
   schedule, `QUEUED`);
2. a unique `visionflow_job_links` binding; and
3. a `legacy_outbox` mapping command.

The source command UUID is the idempotency key. An exact replay returns the
prior job; a conflicting replay is dead-lettered. No Control Plane endpoint is
called from this intake transaction.

## Mapping outbox delivery

The mapping processor claims work in deterministic `(next_attempt_at, id)`
order under a unique lease token. Every state update includes `id`,
`status='PROCESSING'`, and `lease_token`; an old worker therefore cannot mark
another worker's lease as delivered.

`200`/`201` are success. Mapping conflicts and client/auth/validation errors
become `DEAD_LETTER`; network, `429`, and `5xx` failures are retried with
bounded exponential backoff. Maximum attempts become `DEAD_LETTER` rather
than silently looping forever.

The separate processor remains dormant until the activation gate. Production
migration is only `npx prisma migrate deploy`; runtime schema creation and
`prisma db push` are prohibited.
