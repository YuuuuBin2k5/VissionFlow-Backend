# Real UI integration repair — local checkpoint, 2026-09-09

Historical checkpoint below records local validation on 2026-09-09. On 2026-09-10 the operator explicitly authorized the full repair push: frontend `ab4fe10` is on main and the corresponding backend repair is being released on production. Live deployment and real operator acceptance must be checked separately. No production run was created, approved, or published by these validation steps. CanonicalRenderer is unchanged.

## A. Root Causes

- Visual preview: assumed `/static` resources for logical graphic candidates; no materialized preview.
- Retrieval: stock candidate descriptions missing from scoring evidence; Scene Library source media/rights were read from the wrong record; provider failures could return a hardcoded catalog.
- Metrics: graphic fallback `.75` was not a measured score; aggregate coverage did not count actual render representations.
- Controls: visual lock was frontend-only; swap did not update the affected timeline and durable remote snapshot; voice control had no voice selector. Condensed timelines also need explicit resolution-to-shot mapping.
- Render state: editor readiness incorrectly caused an empty video player to appear.
- Playback: protected API URL used directly by HTML video; actual operator run `run_41aaca8218a3` had no render artifact.

## B. Mock/Placeholder Values Found

Removed runtime fallback scores `.75`, missing-evidence technical `.90` and shot-type `.85`, assumed static graphics and editor fallback `.50`. Unknown match is labeled `Chưa đánh giá`. CSS opacity `.75` and input placeholder text are not fake production data.

## C. Visual Asset Contract Changes

Added asset type, graphic spec, preview URL, durable media/preview storage references, renderability, preview error and score source. Review responses sanitize visual media to HTTP(S), re-sign stored objects, and do not return visual filesystem paths. Timeline shots carry their resolution shot order, avoiding edits to a different shot after condensation.

## D. Graphic Fallback Preview

Scene-specific explanatory PNG, Unicode font, generated from the stored graphic specification. Preview and render use the same PNG. This is an explanatory card, not a claim of recovered source footage or a sophisticated motion graphic. Missing scene description/font/storage fails visibly. Provider outage is not silently replaced with graphics.

## E. Candidate Retrieval Results

Live Pexels queries using locally configured credentials, strict rights and the actual scorer, without creating a run:

| Query | Raw | Eligible | Selected | Resolver score |
|---|---:|---:|---|---:|
| organizing desk workspace | 5 | 1 | pex_33194181 | .485 |
| clean office desk | 5 | 3 | pex_6177018 | .608 |
| writing notebook | 5 | 5 | pex_6929080 | .704 |

Eligible candidates retained APPROVED_STOCK rights. Scores are labeled LEXICAL_RESOLVER, not a visual-model confidence. These results do not verify Render's Pexels configuration or the live Scene Library. Diagnostics now expose query, counts, provider availability, rejection reasons and NOT_RECORDED for unrecorded Gemini mode.

## F. Replacement Persistence

Swap saves the selected candidate, affected timeline shot and REAL_OPERATOR intervention; clears obsolete render/QC; cancels queued stale work. Existing remote jobs persist review snapshots in PostgreSQL. Only a candidate returned for that shot can be chosen. Local Chrome verified swap and reload through real HTTP, without response interception.

## G. Lock Persistence

Lock/unlock updates both candidate and timeline in the same review transaction. Active worker jobs reject editing. Shorter voice timing preserves selected assets/locks. Ambiguous legacy condensed shot mapping is rejected instead of modifying the wrong shot. Browser verified lock surviving reload and real voice change.

## H. Voice Change Persistence

Real Edge voice list, explicit selection, actual synthesis, ffprobe duration and downstream timeline-only rebuild. Real local Chrome selected vi-VN-HoaiMyNeural; the backend saved it and reload retained it. Provider failure now fails rather than substituting synthetic WAV. TTS output identity includes text, voice and rate. Test-only synthesis requires explicit test flags.

## I. Render State Changes

No video element before artifact eligibility. Actual run state is shown. Review edits require an explicit `Render timeline đã lưu` action; `/runs/{id}/render` enqueues the saved final timeline without upstream regeneration. Review revision separates new render attempts from obsolete idempotency records. Duplicate submissions reuse queued work.

## J. Playback URL Implementation

Authenticated `/production/runs/{id}/playback` verifies artifact presence, state, positive duration and object metadata, then returns a 900-second signed download URL. Browser video uses this URL, not a bearer-protected API endpoint. Error/retry states request a fresh URL.

## K. Browser Playback Test

Installed Chrome + actual local HTTP backend + isolated PostgreSQL + real CanonicalRenderer + local scoped object-store test adapter. Verified preview HTTP 200/decode, generated PNG, swap/reload, lock/reload, live Edge voice/reload, no empty pre-render player, MP4 metadata > 0, successful video.play(), advancing currentTime and Range 206. No MSW or page.route interception. This is component integration, not full Vercel production UX acceptance.

Read-only R2 diagnostic examined five existing completed job references: run_c15be13f88eb, run_2023ea9d0492, run_733981ba83d5, run_830138b65c01 and run_c6bede20d1b4. Each HEAD returned 404 using local storage configuration. No new artifact was uploaded to manufacture proof. No usable artifact was available for the real R2/Vercel-origin browser check. This does not establish that local and Render bucket settings are identical, nor that those historical rows are human-created runs.

## L. Production Mock Removal

No production Pexels search or operator swap path uses the thematic catalog. Graphic default scores/static resources and automatic synthetic TTS fallback were removed from repaired paths. Automated fixtures remain clearly test-only. A whole-product claim that every AI stage is fully live is NOT made; upstream local/estimated modes require their own audit.

## M. Automated Tests

Latest focused regression: **132 passed**, 6 existing framework/OpenAPI warnings, 32.55 seconds. Separate opt-in Chrome + live Edge TTS run passed. TypeScript no-emit, Python compileall, repository security scan, targeted new-file secret-pattern scan and git diff checks passed. Test harness redirects run/source/embedding/asset caches into fresh temporary directories and blocks external network; live TTS is a separate opt-in restricted to the installed Edge endpoint. Known framework deprecation/OpenAPI warnings remain.

## N. Remaining Blockers

1. Repair is not committed, pushed or deployed. The previous permission covered worker reliability only.
2. Actual failed operator run still has no final artifact. Existing-object R2 test was blocked by 404s; bucket/key consistency and real R2 CORS/Range remain unverified.
3. Live Render Scene Library/stock/provider configuration is not verified by local diagnostics.
4. Pre-enqueue runs still rely on the existing local run repository; PostgreSQL review persistence requires an existing remote job. Replacing that persistence model would need a separately reviewed scope, not an unannounced architecture redesign.
5. Regenerated TTS files are local until portable handoff. Survival of a backend redeploy between voice edit and render is not verified.
6. Human Vercel Generate -> local worker -> playable MP4 acceptance has NOT been repeated. No readiness claim is justified yet.

## O. Manual Operator Test Instructions

Do not repeat production Generate against this un-deployed repair. After authorized deployment and storage/provider checks: open Vercel, enter a topic and Generate; inspect real previews and honest scores; swap a candidate, reload, lock and reload; select voice and save; explicitly render the saved timeline if edited; confirm worker claims the job and upload completes; play the MP4 and verify nonzero duration. Stop on any missing media/provider error. Do not approve or publish during this pilot.

## P. Final Status

REAL_UI_STILL_BROKEN
