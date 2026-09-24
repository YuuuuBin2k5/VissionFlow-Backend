# Remote worker reliability — 2026-09-09

## A. Root Cause in Existing Worker

Independent control-plane calls had no shared admission/backoff policy. Aggressive idle polling and overlapping failure paths could continue requesting after edge throttling. A 429 does not establish whether Cloudflare or application quota is responsible; challenge headers/body are classified separately.

## B. Previous Incorrect Failure Behavior

Completion transport errors could exhaust local retries and enter the generic failure path. The worker now separates control-plane delivery failures from media failures. Successful output is checkpointed before further control-plane calls; delivery errors never invoke `/fail`.

## C. New HTTP Error Classification

AUTH_FAILURE, RATE_LIMITED, EDGE_CHALLENGE, TRANSIENT_NETWORK, SERVER_UNAVAILABLE, PERMANENT_REQUEST_ERROR, JOB_REJECTED. Authentication failures stop requests and require operator intervention. No response HTML or credentials are logged.

## D. Backoff / Jitter

Shared exponential delay, numeric/date Retry-After, rate-reset headers, and positive jitter. Limits use 30/60/120-second minimum cooldowns; a longer server Retry-After always wins. Successful quota headers defer only when exhausted. Network/server backoff caps at 60 seconds before jitter; circuit cooldown caps at 120 before server hints/jitter.

## E. Circuit Breaker

Three consecutive rate-limit/challenge responses open the shared circuit. Claims, heartbeats and completion share serialized admission and HTTP I/O. One request probes after cooldown; a failed probe reopens the circuit. Same-workdir process locking prevents overlapping workers, but cannot prevent another machine/workdir using the same worker identity.

## F. New Poll / Heartbeat Cadence

Idle claim 20 seconds, idle heartbeat 60 seconds, active heartbeat 25 seconds. One heartbeat loop coalesces concurrent heartbeat attempts. Cooldown applies across request types. Backend advertises a 180-second lease. Long outages can still expire a lease; the worker does not bypass fencing.

## G. Completion Idempotency

Completion retries retain the job attempt, checksum and storage reference. The existing backend completion handler remains authoritative. A missing acknowledgement is not evidence of render failure.

## H. Completion Reconciliation

New authenticated GET `/api/v1/render-workers/jobs/{job_id}/status?attempt=N` checks worker ownership and attempt. Matching accepted checksum/ref completes local recovery without rerender/upload. Expired/conflicting attempts retain output and stop for operator review, never revive a lease or overwrite another attempt.

## I. Local Durable Worker State

`<workdir>/jobs/<job-id>/state.json`, atomically replaced after flush/fsync. Phases: RENDER_OUTPUT_READY, UPLOAD_PENDING, COMPLETION_PENDING, COMPLETION_UNKNOWN, COMPLETED, RECONCILIATION_REQUIRED. Contains job identity, checksum, metadata and storage reference, not token/signed URLs. Local MP4 stays available. This does not guarantee recovery from physical disk failure.

## J. Worker Startup Recovery

Pending checkpoints are reconciled before claiming new work. Corrupt or mismatched checkpoints fail closed. Completed remote uploads are reused; expired attempts need manual reconciliation. The worker must run as the Windows account that encrypted the DPAPI token.

## K. Cloudflare 429 Handling

Stable `VisionFlow-RenderWorker/1.0` User-Agent, pooled HTTP client, connect/read/write timeouts 10/30/15 seconds, completion read timeout 120 seconds. Origin remains configurable. Challenge logging includes only safe status/category/cf-ray and retry timing. No browser impersonation or challenge bypass.

## L. Worker Console / Health State

ONLINE, DEGRADED, RATE_LIMITED, BACKEND_UNAVAILABLE, AUTH_FAILED. Failure diagnostics show state/circuit; shutdown prints counters. Backend freshness defaults to 180 seconds (`VISIONFLOW_WORKER_ONLINE_SECONDS`, validated 90–300), so stale worker records are shown offline, not indefinitely online. Local ONLINE during an idle soak is not proof of successful rendering.

## M. Automated Tests

Isolated PostgreSQL + HTTP + real FFmpeg suite: 116 passed, six existing dependency/OpenAPI warnings. Includes shared Retry-After, categories, challenge redaction, circuit recovery, heartbeat coalescing, singleton lock, completion 429, acknowledgement loss/restart, actual MP4 rendering during a virtual 60-second outage, and a virtual hour of idle requests with 429/503 and one checkpoint reconciliation. The virtual-hour test is not a real hour of production operation.

## N. Production Soak Result

Bounded 180-second Windows soak against the existing production backend, 2026-09-09 00:40:08–00:43:08 local time (UTC+7). Clean exit 0; health ONLINE; 13 requests: one registration 200, three successful heartbeats 200, nine empty claims 204. Claims were approximately 20.2–20.5 seconds apart; heartbeat approximately 60 seconds. Zero 429, zero circuit openings, no challenge cf-ray to report. Worker stopped at the deadline. No synthetic production video or job was created. This short idle sample cannot establish long-term edge reliability. The production OpenAPI check returned 200 but did not include the new reconciliation route, so idle connectivity cannot certify recovery against the deployed backend.

## O. Remaining Cloudflare/Render Edge Issues

The worker cannot guarantee an edge provider will accept automated API traffic. If challenges recur, use cf-ray/time evidence with the operator/provider to correct the rule or approve a dedicated API origin; do not disable authentication. Backend reconciliation changes still require deployment. A previously hardcoded token was removed from the launcher; if that token was committed/shared, rotate it on Render and in the local DPAPI file. Removing the working-tree literal does not remove Git history.

## P. Exact Windows Start Command

Only start after the matching backend reconciliation route is deployed. From PowerShell:

```powershell
Set-Location D:\VisionFlow\VisionFlow_Bakend
$env:PATH = 'C:\Program Files (x86)\Digiarty\VideoProc Converter AI;' + $env:PATH
.\scripts\start_remote_worker.ps1 -ApiBaseUrl 'https://visionflow-control-plane-free.onrender.com'
```

Requires the existing backend virtualenv with `worker/requirements.txt` installed, FFmpeg/FFprobe and the existing DPAPI token file. No DATABASE_URL is required. Use `-Check` for registration-only validation, or `-SoakSeconds 180` for a bounded worker run that may claim queued jobs. Do not run the old launcher simultaneously.

## Q. Final Status

`WORKER_RELIABILITY_STILL_BLOCKED`: local reliability tests pass, but the new backend route is not deployed and the real Vercel UI → render → playable video → operator review has not been verified.
