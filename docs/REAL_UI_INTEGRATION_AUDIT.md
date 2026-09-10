# Internal audit before implementation

Actual production snapshot: `run_41aaca8218a3`; read-only PostgreSQL inspection. Exact graphic IDs match the operator report. Job WAITING_FOR_WORKER, run WAITING_FOR_RENDER_WORKER, no render artifact. No synthetic production run created.

Flow: AutoVideoComposer -> productionApi -> production_controller -> orchestrator -> ProductionRun.visual_plan -> asset_resolver -> resolved_assets -> editor_planner -> ProductionRunPanel / VisualReviewSection / EditorReviewSection -> remote_render -> RenderJob snapshot -> RenderArtifact -> video endpoint.

| Value/control | Classification | Finding |
|---|---|---|
| fallback composite/semantic .75 | DEFAULT VALUE | asset_resolver hardcodes scores without reranker evidence |
| global coverage 0 | COMPUTED FALLBACK | eligible footage duration weights only; not renderable shot coverage |
| global average 0 | DEFAULT VALUE | no evaluated footage; unknown presented as zero |
| graphic thumbnail/media | PLACEHOLDER | assumed /static files, no materialization |
| alternate count 0 | REAL BACKEND DATA | candidate rejection reasons include zero semantic/entity-action evidence |
| thematic catalog | FIXTURE-like runtime fallback | used on missing key, provider errors and empty search; must not disguise provider outage |
| Visual Review lock | frontend-only state | no persistence request |
| swap | incomplete backend integration | persists resolution but not affected EditorPlan/render invalidation |
| visual regeneration scene_id | ignored scope | re-resolves whole visual plan |
| voice button | incomplete integration | regenerates default voice without a selector |
| final player | COMPUTED FALLBACK | rendered when editor is ready, without artifact; protected API URL assigned directly |
| real run final artifact | REAL BACKEND DATA | absent, so there is no final MP4 to play |

CanonicalRenderer remains the rendering engine. Provider configuration, live eligible results and browser playback still require verification. Network reliability is not UX readiness. Human production acceptance remains outstanding.
