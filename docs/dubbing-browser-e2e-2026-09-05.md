# Browser Dubbing E2E evidence — 2026-09-05

## A. Environment Readiness

| Dependency | State |
| --- | --- |
| Frontend | AVAILABLE: real Vite app, Chromium, http://localhost:3000 |
| Control Plane | AVAILABLE: real API at http://localhost:8000/api/v1; ephemeral local signing key |
| Object Storage | MISCONFIGURED: configured R2 bucket `vision-flow`; HeadBucket 401; browser OPTIONS 403, no allow-origin header |
| DB | AVAILABLE: configured Neon read-only SELECT 1 succeeds; all writes/tests used isolated local PostgreSQL 18 on port 55439 |
| Worker | Code/imports available; queue processor was not launched against shared/production DB; no browser workflow reached worker |
| ASR | Groq credential MISSING; Gemini probe 403; faster-whisper installed, transcription NOT RUN |
| Translation | MISCONFIGURED: actual Gemini 2.5 Flash generateContent probe returned 403 |
| TTS | AVAILABLE in independent Edge TTS probe; vi-VN-NamMinhNeural produced real MP3 |
| ffmpeg/ffprobe | AVAILABLE; PATH ffmpeg is obsolete (AAC experimental error); bundled imageio FFmpeg 7.1 and PATH ffprobe successfully generated/probed fixture |

Storage endpoint: `https://ec302240fdb8cad9ae6c9b685f14eeec.r2.cloudflarestorage.com`. Credential values and signed URLs were not captured. No storage CORS write was attempted because configured storage credentials failed authentication.

## B. Exact E2E Runtime Trace

```text
Real Chromium → http://localhost:3000/create/dubbing
→ real local authentication and explicit test organization membership
→ MP4 file input (33.000 s, 285746 bytes)
→ upload intent 201
→ storage OPTIONS 403 (no Access-Control-Allow-Origin)
→ PUT blocked by browser: net::ERR_FAILED
→ UI error; Start Dubbing enabled again
→ complete / READY / dispatch / ASR / translation / TTS / timing / compose / review / OpenCut: NOT REACHED
```

Last source asset: `5d178344-7963-4aef-a06a-db5f00f08976`.
Organization: `67ec135f-fb37-4923-a8af-747c646e3319` (isolated dev only).
DB confirms `source_video`, `video/mp4`, `285746` bytes declared, status `UPLOADING`, and **zero workflows**. Object existence, stored size/MIME and READY were not verified. Current checksum completion design compares signed SHA-256 metadata; it is not full content-hash verification.

Selected settings: Vietnamese, faithful, Nam Minh, burn subtitles on, mute original on, CTA off, loop off. Required PUT headers from code: Content-Type and x-amz-meta-sha256. The actual browser origin was localhost:3000; production-origin CORS was not tested.

## C. Status Timeline

| State/event | Started (UTC) | Duration | Result |
| --- | --- | --- | --- |
| Capability request | 2026-09-05 05:09:29.290 | Not captured | 200; dev enabled |
| Upload intent | 2026-09-05 05:09:29.699 response observed | Not captured | 201, asset UPLOADING |
| R2 preflight | Following intent; exact time not captured | Not captured | OPTIONS 403 |
| Workflow states | Not entered | N/A | No workflow created |

Actual implementation uses QUEUED → RENDERING → APPROVAL_PENDING / FAILED. These transitions were not observed for the browser video; no synthetic ASR/translation state sequence is presented.

## D. ASR Result

NOT RUN for browser workflow. Fixture contains clear synthesized English speech, one voice, no music: Daniel, September 12 2026, 42, San Francisco, a long sentence, punctuation, and a faster final line. No transcript, segment count, detected-language output or ASR confidence was produced. No accuracy claim is made.

## E. Translation Result

NOT RUN for browser workflow. Faithful was selected in the real UI. Independent generateContent translation request returned HTTP 403. Meaning, numbers, proper nouns, omitted sentences, hallucinations and adapted_text runtime authority remain NOT VERIFIED.

## F. Timing QC

| Segment | Target | Actual | Drift | Result |
| --- | ---: | ---: | ---: | --- |
| Browser workflow | N/A | N/A | N/A | NOT RUN |

Max/average drift and segments over tolerance: unavailable, not zero. Independent TTS probe produced a 31536-byte MP3 measured by ffprobe at 5256 ms; it has no source segment timing target and is not counted as a dubbing segment.

Code audit: `DubbingService.execute_dubbing_pipeline` probes generated raw audio, applies FFmpeg atempo clamped to 0.85–1.45 (and conditional pitch adjustment), probes aligned WAV, then stores rendered_audio_duration_ms. Reported segment duration is post-alignment, not raw TTS. Timeline shift is clamped to 600 ms; final mixing uses apad and a source-duration limit. These are existing correction mechanisms, distinct from QC; no correction engine was added. QC regression now returns REVIEW_REQUIRED above 250 ms and INCOMPLETE when segment measurements are missing. Negative drift remains in each segment; max/average are absolute-drift aggregates.

## G. Render Verification

Source: 33.000 s; H.264 640×360 video and AAC audio confirmed by ffprobe. Final dubbed video, final duration/delta, final streams, burned subtitles and audible mute/mixing behavior: NOT RUN. Source fixture and independent TTS file are not final exports.

## H. Metadata Verification

Real PostgreSQL regression fixtures only:

- Legacy generated SEO description A (700 characters), title Daniel, hashtag test and pinned comment map to canonical YouTube fields.
- `/dubbing/status` preview description equals `resolve_publish_metadata` result, all 700 characters preserved before platform trimming.
- Separate transaction persists user description B; reload and two bridge retries carrying stale OLD retain B and resolver provenance user.
- Bridge previously replaced completed package with empty defaults; now timeline/QC survive DB reload.
- Review response now includes subtitle/audio settings, source transcript projection and render reference.

Actual publisher upload/schedule and user edit through the publish UI: NOT RUN. Existing manual-dispatch code persists overrides; the regression here verifies storage/reload/retry and resolver, not an external publication.

## I. OpenCut Handoff

FAIL acceptance / runtime NOT REACHED. No final media exists. Code inspection also shows the current callback only navigates to master_studio; it does not pass the rendered asset, and that route opens ShortStudio. No project/media/timeline preview is claimed verified. No large UI change was made behind the upload blocker.

## J. Failure Path

Real browser upload failure displays an actionable alert and releases busy state. Real API dispatch of the non-READY asset returns 409. DB still contains zero workflows, so no FAILED transition should be fabricated for this pre-dispatch rejection. Post-dispatch worker failure is NOT RUN.

## K. Tests

| Type | Result |
| --- | --- |
| Focused unit/regression | 22 passed: gate, dubbing contract/QC, publishing resolver, source policy |
| PostgreSQL integration | 6 passed in isolated per-test schemas; real SQL/commits |
| Browser E2E | BLOCKED at storage preflight; real browser attempt performed |
| Frontend build | TypeScript and Vite production build passed; pre-existing large-bundle warning |
| Backend | Changed Python syntax passed; restarted API seeds 2 prompt versions successfully |
| Orchestrator | TypeScript noEmit passed |
| Legacy worker dubbing suite | 29 passed, 8 failed: old dispatch fixtures omit organization_id and expect obsolete URL/unauthenticated behavior |
| PostgreSQL concurrency | Two simultaneous claimers: exactly one success; active lease rejected; expired lease reclaimed; 51 active leases no longer starve queued work; missing rendering lease not reclaimed |

Idempotency integration: same request/key returns same workflow against a READY **DB fixture** with real membership. This is not verification of a successful browser-uploaded asset.

Reproduce focused integration from backend root with an explicitly isolated local test database:

```powershell
$env:DUBBING_TEST_DATABASE_URL='postgresql+psycopg://dubbing_e2e@127.0.0.1:55439/dubbing_e2e_tests'
$env:PYTHONPATH="$PWD;$PWD/services/control-plane"
.\venv\Scripts\python.exe -m pytest services/control-plane/tests/test_dubbing_runtime_regressions.py services/control-plane/tests/test_web_dubbing_gate.py worker/tests/test_dubbing_contract.py worker/tests/test_publish_metadata.py services/control-plane/tests/test_source_media.py -q
```

## L. Fixes Made During E2E

| File / function | Observed failure | Fix |
| --- | --- | --- |
| services/control-plane/app/core/dubbing_claim.py / claim_next_dubbing_workflow | Real PG regression: 51 active leases hid queued job | Filter dubbing and expired leases in SQL before lock/limit |
| services/control-plane/app/core/dubbing_bridge.py / sync_dubbing_job_to_control_plane | Real PG regression: timeline wiped; retry can overwrite user snapshot | Preserve completed package and durable user override under row lock |
| worker/domain/dubbing_contract.py / record_timing_qc | Unit regressions: excessive/missing drift falsely PASSED | REVIEW_REQUIRED / INCOMPLETE with signed segment drifts retained |
| services/control-plane/app/routers/dubbing.py / get_dubbing_job_status | Regression: subtitle/audio review settings absent | Add settings, source transcript projection, render reference |
| services/control-plane/app/routers/dubbing.py / web gate and source intake | No production gate despite incomplete browser E2E | Capability endpoint; intake defaults OFF unless ENABLE_WEB_DUBBING=true |
| services/control-plane/.env.example | No documented web gate | Default web and URL flags false |
| client src/components/DubbingStudio.tsx / upload and capability check | Browser showed only Failed to fetch; no gate | Actionable upload error, capability-controlled access |
| services/control-plane/app/main.py / _seed_prompt_baselines | Actual dev startup SQL syntax error at :config::jsonb | CAST(:config AS jsonb); restart confirms 2 versions seeded |

Added regression tests and read-only preflight script provide evidence; they are not pipeline components. Existing unrelated working-tree changes were preserved.

## M. Production Gate

| Feature | State |
| --- | --- |
| Browser Dubbing | OFF by default in patched code; not safe to enable |
| Object Storage upload | OFF / blocked by 401 and browser CORS 403 |
| ASR | PARTIAL: runtime not reached |
| Faithful Translation | OFF for tested configuration: Gemini 403 |
| TTS | PARTIAL: independent provider probe passes, browser pipeline unverified |
| Timing QC | PARTIAL: regression passed, real segment QC not reached |
| Final Render | OFF / not reached |
| Review | PARTIAL: DB regression verified, real review not reached |
| OpenCut handoff | OFF / acceptance failed |
| Canonical metadata | PARTIAL: DB/resolver regressions pass; end-to-end publish not run |
| Multi-worker concurrency | READY for tested local PostgreSQL scenarios only |
| URL import | OFF, unchanged default and dev setting |
| Telegram file dubbing | Legacy; TypeScript passes; live file path NOT VERIFIED; 8 stale tests fail |

Remote deployment environment flag values and rollout completion are not verified by these local tests. Keep production ENABLE_WEB_DUBBING=false and ENABLE_DUBBING_URL_IMPORT=false.

## N. Remaining Limitations

R2 credentials fail bucket authentication; browser origin preflight fails; Gemini translation request is forbidden. These require working dev credentials and an allowed-origin storage CORS policy before the same browser flow can continue. No checksum/full-content verification, complete/READY, ASR, translated timeline, generated segment audio, final render, audible mixing, review or OpenCut completion is claimed.

Additional code-audit limitations: silence fallback can substitute for failed TTS, empty ASR can remux source without dubbing, and OpenCut callback does not carry media. They have not been exercised by this browser run and were not rewritten. Old legacy dispatch tests remain incompatible with required organization authentication. Local PostgreSQL schemas were created via current model metadata (not a full migration rehearsal). No production DB data or Telegram jobs were mutated.
