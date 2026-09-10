# Asset download queue starvation — 2026-09-10

Read-only production evidence: job `22d60497-72db-4938-92ab-cf6ab01cc104` (run `run_41aaca8218a3`) held desktop-main's capacity in DOWNLOADING attempt 3. Runs `run_3161520486f5` and `run_607555966f6a` had durable WAITING_FOR_WORKER rows, attempt 0.

All five TTS dependencies of the old job returned canonical HEAD 404. Each corresponding bucket-prefixed source returned 200 with matching size and SHA metadata. These are inputs, not the five historical MP4 outputs previously approved for migration. No objects were copied or deleted, and no job rows were manually changed during diagnosis.

Worker root cause: ASSET_DOWNLOAD_FAILED bypassed the media-failure reporting branch. The process retained its active job and renewed the lease indefinitely. Report this error through the existing attempt-fenced failure endpoint; the repository already enforces max_attempts and releases worker capacity. Control-plane transport errors and durable output checkpoints remain protected. Log only download HTTP status, never signed URL or response body.

Runtime dependency root cause: production uses `from google import genai`, but its requirements only installed the legacy google-generativeai package. Add google-genai and a Docker build-time import smoke check. Keep the legacy dependency for existing callers; no planner logic or provider key changes.

The existing worker process must be restarted to load the fix. Do not run a second worker against the same work directory. Once stopped, let expired leases be handled by the normal repository flow. Do not create synthetic runs or manually approve/publish anything. Repairing the five legacy input objects requires its own explicit scope approval.
