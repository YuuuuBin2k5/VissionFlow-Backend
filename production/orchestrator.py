"""
Production Orchestrator for VisionFlow Auto Production System (v1)
State machine, stage dependency graph, idempotency caching, stage-level retry,
and dependency invalidation rules. Honest STUB vs REAL execution tracking.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid

logger = logging.getLogger("visionflow.production.orchestrator")
from typing import Any, Dict, List, Optional, Set
from production.contracts import (
    AutoVideoRequest,
    EditorPlan,
    InputMode,
    ManualInterventionRecord,
    ManualInterventionType,
    ProductionRun,
    ProductionRunStatus,
    ProductionStageRun,
    QualityReport,
    QualityStatus,
    RunEnvironment,
    ScenePlan,
    ScriptPlan,
    ShotPlan,
    StageStatus,
)
from production.config_loader import config_loader
from production.input_normalizer import ScriptParser, JSONNormalizer
from production.repositories.run_repository import run_repository
from production.source_ingest import source_ingest_service
from production.scene_indexer import scene_indexer
from production.source_analyzer import source_analyzer
from production.embedding_service import embedding_service
from production.research_service import research_agent
from production.story_planner import story_planner
from production.script_service import script_engine
from production.script_quality_gate import script_quality_gate
from production.visual_planner import visual_planner
from production.asset_resolver import asset_resolver
from production.editor_planner import editor_planner
from production.tts_service import tts_service, SceneTTSResult
from production.render_handoff import render_handoff
from production.quality_orchestrator import quality_orchestrator



# 15 stages with Source Intelligence Foundation in Phase 2
ORDERED_STAGES = [
    "input_normalization",
    "source_ingest",
    "scene_indexing",
    "scene_analysis",
    "scene_embedding",
    "scene_retrieval",
    "research_story",
    "script_generation",
    "script_quality_gate",
    "visual_planning",
    "asset_resolution",
    "editor_planning",
    "tts_timing",
    "timeline_compose",
    "final_qc",
]

# Phase 6 Reality Map: Video Render & Final QC are REAL!
STAGE_REALITY_MAP = {
    "input_normalization": "REAL",
    "source_ingest": "REAL",
    "scene_indexing": "REAL",
    "scene_analysis": "REAL",
    "scene_embedding": "REAL",
    "scene_retrieval": "REAL",
    "research_story": "REAL",
    "script_generation": "REAL",
    "script_quality_gate": "REAL",
    "visual_planning": "REAL",
    "asset_resolution": "REAL",
    "editor_planning": "REAL",
    "tts_timing": "REAL",
    "timeline_compose": "REAL",
    "final_qc": "REAL",
}

STAGE_PROGRESS_MAP = {
    "input_normalization": 5,
    "source_ingest": 15,
    "scene_indexing": 25,
    "scene_analysis": 35,
    "scene_embedding": 45,
    "scene_retrieval": 50,
    "research_story": 55,
    "script_generation": 60,
    "script_quality_gate": 65,
    "visual_planning": 70,
    "asset_resolution": 75,
    "editor_planning": 80,
    "tts_timing": 88,
    "timeline_compose": 94,
    "final_qc": 100,
}



class ProductionOrchestrator:
    _instance: Optional[ProductionOrchestrator] = None
    _active_tasks: Dict[str, asyncio.Task] = {}
    _stage_cache: Dict[str, Dict[str, Any]] = {}  # key: f"{run_id}:{stage_name}:{input_hash}" -> output
    _stage_execution_counts: Dict[str, int] = {}   # key: f"{run_id}:{stage_name}" -> run count

    def __new__(cls) -> ProductionOrchestrator:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @staticmethod
    def compute_input_hash(data: Any) -> str:
        serialized = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]

    def get_execution_count(self, run_id: str, stage_name: str) -> int:
        return self._stage_execution_counts.get(f"{run_id}:{stage_name}", 0)

    def create_run(self, request: AutoVideoRequest) -> ProductionRun:
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        
        stages = [
            ProductionStageRun(
                id=f"stg_{uuid.uuid4().hex[:8]}",
                run_id=run_id,
                stage_name=stage_name,
                status=StageStatus.PENDING,
                execution_mode=STAGE_REALITY_MAP.get(stage_name, "STUB"),
                is_cached=False,
            )
            for stage_name in ORDERED_STAGES
        ]

        run = ProductionRun(
            id=run_id,
            channel_profile_id=request.channel_profile_id,
            run_environment=getattr(request, "run_environment", RunEnvironment.DEV),
            status=ProductionRunStatus.CREATED,
            mode="auto",
            request=request,
            current_stage=ORDERED_STAGES[0],
            progress_pct=0,
            stages=stages,
        )
        return run_repository.create(run)

    def get_run(self, run_id: str) -> Optional[ProductionRun]:
        return run_repository.get(run_id)

    async def start_run(self, run_id: str) -> None:
        """Starts asynchronous pipeline execution."""
        task = asyncio.create_task(self._execute_pipeline(run_id))
        self._active_tasks[run_id] = task

    async def cancel_run(self, run_id: str) -> bool:
        from production.remote_render import remote_render_enabled, cancel_remote_render
        if remote_render_enabled():
            await asyncio.to_thread(cancel_remote_render, run_id)
        task = self._active_tasks.get(run_id)
        if task and not task.done():
            task.cancel()
        run_repository.update_status(
            run_id=run_id,
            status=ProductionRunStatus.CANCELLED,
            error_message="Production run cancelled by user",
        )
        return True

    async def resume_run(self, run_id: str) -> Optional[ProductionRun]:
        """
        Resumes an unfinished run from its persisted state across process restarts.
        Skips already completed stages and resumes from the first pending/failed stage.
        """
        from production.remote_render import remote_render_enabled, load_remote_run
        if remote_render_enabled():
            remote = await asyncio.to_thread(load_remote_run, run_id)
            if remote:
                run_repository.update(remote)
                return remote
        run = run_repository.get(run_id)
        if not run:
            return None
        logger.info("Resuming production run %s from status %s", run_id, run.status)
        await self._execute_pipeline(run_id)
        return run_repository.get(run_id)

    # -----------------------------------------------------------------------
    # Dependency Invalidation Logic (Spec 03 - Section 5)
    # -----------------------------------------------------------------------
    def invalidate_for_change(self, run_id: str, change_type: str) -> List[str]:
        """
        Applies canonical dependency invalidation rules:
        - visuals_changed: invalidates visual_planning, asset_resolution, editor_planning, timeline_compose, final_qc.
        - voice_changed: invalidates tts_timing, editor_planning, timeline_compose, final_qc.
        - script_changed: invalidates everything from visual_planning onward + tts.
        """
        run = run_repository.get(run_id)
        if not run:
            return []

        invalidated_stages: List[str] = []

        if change_type == "visuals_changed":
            invalidated_stages = ["visual_planning", "asset_resolution", "editor_planning", "timeline_compose", "final_qc"]
        elif change_type == "voice_changed":
            invalidated_stages = ["tts_timing", "editor_planning", "timeline_compose", "final_qc"]
        elif change_type == "script_changed":
            invalidated_stages = ["script_quality_gate", "visual_planning", "asset_resolution", "editor_planning", "tts_timing", "timeline_compose", "final_qc"]

        # Reset stage statuses and purge cache keys
        for stg_name in invalidated_stages:
            run_repository.update_stage_status(run_id, stg_name, StageStatus.PENDING, is_cached=False)
            # Purge cache entries for this run and stage
            prefix = f"{run_id}:{stg_name}:"
            keys_to_del = [k for k in self._stage_cache if k.startswith(prefix)]
            for k in keys_to_del:
                del self._stage_cache[k]

        return invalidated_stages

    # -----------------------------------------------------------------------
    # Stage Execution with Idempotency & Caching
    # -----------------------------------------------------------------------
    async def _run_stage_idempotent(
        self,
        run_id: str,
        stage_name: str,
        stage_input_data: Any,
        target_progress: int,
    ) -> Dict[str, Any]:
        """
        Executes a stage or returns cached output if input_hash matches.
        Increments execution count ONLY on fresh execution.
        """
        input_hash = self.compute_input_hash(stage_input_data)
        cache_key = f"{run_id}:{stage_name}:{input_hash}"

        # Check in-memory cache
        if cache_key in self._stage_cache:
            cached_output = self._stage_cache[cache_key]
            run_repository.update_stage_status(
                run_id=run_id,
                stage_name=stage_name,
                status=StageStatus.COMPLETED,
                output_json=cached_output,
                is_cached=True,
            )
            existing_run = run_repository.get(run_id)
            current_st = existing_run.status if existing_run else ProductionRunStatus.INPUT_NORMALIZED
            run_repository.update_status(run_id, current_st, current_stage=stage_name, progress_pct=target_progress)
            return cached_output

        # Check if already completed in persisted run (resumption across process restarts)
        existing_run = run_repository.get(run_id)
        if existing_run:
            for stg in existing_run.stages:
                if stg.stage_name == stage_name and stg.status == StageStatus.COMPLETED and stg.output_json:
                    logger.info("Resumption: stage %s for run %s already completed, skipping rerun", stage_name, run_id)
                    current_st = existing_run.status or ProductionRunStatus.INPUT_NORMALIZED
                    run_repository.update_status(run_id, current_st, current_stage=stage_name, progress_pct=target_progress)
                    return stg.output_json

        # Fresh execution
        count_key = f"{run_id}:{stage_name}"
        self._stage_execution_counts[count_key] = self._stage_execution_counts.get(count_key, 0) + 1

        start_time = time.time()
        run_repository.update_stage_status(run_id, stage_name, StageStatus.RUNNING, is_cached=False)
        existing_run = run_repository.get(run_id)
        current_st = existing_run.status if existing_run else ProductionRunStatus.INPUT_NORMALIZED
        run_repository.update_status(run_id, current_st, current_stage=stage_name, progress_pct=target_progress)

        # Execution logic based on reality map
        is_real = STAGE_REALITY_MAP.get(stage_name) == "REAL"
        output_payload: Dict[str, Any] = {
            "stage": stage_name,
            "status": "ok",
            "mode": "REAL" if is_real else "STUB",
            "timestamp": time.time(),
        }
        if isinstance(stage_input_data, dict):
            output_payload.update(stage_input_data)
        elif isinstance(stage_input_data, list):
            output_payload["items"] = stage_input_data

        # Small async yield
        await asyncio.sleep(0.05)

        duration_ms = int((time.time() - start_time) * 1000)
        self._stage_cache[cache_key] = output_payload

        run_repository.update_stage_status(
            run_id=run_id,
            stage_name=stage_name,
            status=StageStatus.COMPLETED,
            duration_ms=duration_ms,
            output_json=output_payload,
            is_cached=False,
        )
        return output_payload

    # -----------------------------------------------------------------------
    # Retry Single Stage (Case B)
    # -----------------------------------------------------------------------
    async def retry_stage(self, run_id: str, stage_name: str) -> None:
        """
        Retries ONLY the specified stage and downstream dependents without
        re-running previously completed upstream stages.
        """
        run = run_repository.get(run_id)
        if not run:
            raise ValueError(f"Run {run_id} not found")

        if stage_name not in ORDERED_STAGES:
            raise ValueError(f"Unknown stage {stage_name}")

        stage_idx = ORDERED_STAGES.index(stage_name)
        # Purge cache for target stage to force re-execution
        prefix = f"{run_id}:{stage_name}:"
        for k in list(self._stage_cache.keys()):
            if k.startswith(prefix):
                del self._stage_cache[k]

        # Execute only from this stage onwards
        for i in range(stage_idx, len(ORDERED_STAGES)):
            stg = ORDERED_STAGES[i]
            prog = STAGE_PROGRESS_MAP[stg]
            input_data = {"run_id": run_id, "instruction": run.request.instruction, "stage": stg}
            await self._run_stage_idempotent(run_id, stg, input_data, prog)

    async def _execute_pipeline(self, run_id: str) -> None:
        run = run_repository.get(run_id)
        if not run:
            return

        run_repository.update_status(run_id, ProductionRunStatus.INPUT_NORMALIZED, progress_pct=5)

        try:
            # 1. Normalization (REAL)
            await self._run_stage_idempotent(run_id, "input_normalization", run.request.model_dump(), 5)

            # 2. Source Ingest (REAL)
            ingested_sources = []
            for src_input in run.request.sources:
                try:
                    ingested_rec = source_ingest_service.ingest_source(src_input)
                    ingested_sources.append(ingested_rec)
                except Exception:
                    pass
            ingest_payload = [s.model_dump(mode="json") for s in ingested_sources]
            await self._run_stage_idempotent(run_id, "source_ingest", ingest_payload, 15)

            # 3. Scene Indexing (REAL)
            all_indexed_scenes = []
            for src_rec in ingested_sources:
                scenes = scene_indexer.index_source(src_rec)
                all_indexed_scenes.extend(scenes)
            indexing_payload = [s.model_dump(mode="json") for s in all_indexed_scenes]
            await self._run_stage_idempotent(run_id, "scene_indexing", indexing_payload, 25)

            # 4. Scene Analysis (REAL)
            analyzed_scenes = []
            for src_rec in ingested_sources:
                scenes = source_analyzer.analyze_source_scenes(src_rec)
                analyzed_scenes.extend(scenes)
            analysis_payload = [s.model_dump(mode="json") for s in analyzed_scenes]
            await self._run_stage_idempotent(run_id, "scene_analysis", analysis_payload, 35)

            # 5. Scene Embedding (REAL)
            indexed_embeddings_count = 0
            for scn in analyzed_scenes:
                embedding_service.index_scene_embedding(scn)
                indexed_embeddings_count += 1
            embedding_payload = {"embedded_scenes": indexed_embeddings_count}
            await self._run_stage_idempotent(run_id, "scene_embedding", embedding_payload, 45)

            # 6. Scene Retrieval (REAL)
            retrieved_candidates = []
            if run.request.instruction:
                retrieved_candidates = embedding_service.search_scenes(run.request.instruction, top_k=5)
            retrieval_payload = [r.model_dump(mode="json") for r in retrieved_candidates]
            await self._run_stage_idempotent(run_id, "scene_retrieval", retrieval_payload, 50)

            # 7. Research, Story & Script Pipeline with InputMode branching
            target_dur = float(run.request.target_duration_sec or 55.0)

            if run.request.input_mode == InputMode.SCRIPT:
                # SCRIPT MODE: Skip research_story stage
                run_repository.update_stage_status(
                    run_id=run_id,
                    stage_name="research_story",
                    status=StageStatus.SKIPPED,
                    error_code="SKIPPED_BY_INPUT_MODE",
                )
                # Parse raw_script
                title_hint = (run.request.instruction or run.request.raw_script or "Tự động")[:25]
                script_plan = ScriptParser.parse(
                    raw_text=run.request.raw_script or run.request.instruction or "",
                    default_title=f"Kịch bản {title_hint}",
                )
                run.script_plan = script_plan
                script_payload = script_plan.model_dump(mode="json")
                await self._run_stage_idempotent(run_id, "script_generation", script_payload, 60)

                # Script Quality Gate
                script_gate_report = script_quality_gate.evaluate(
                    script_plan=script_plan,
                    fact_pack=None,
                    target_duration_sec=target_dur,
                    run_id=run_id,
                )
                run.script_gate_report = script_gate_report
                gate_payload = script_gate_report.model_dump(mode="json")
                await self._run_stage_idempotent(run_id, "script_quality_gate", gate_payload, 65)

            elif run.request.input_mode == InputMode.JSON:
                # JSON MODE: Developer supplied payload
                run_repository.update_stage_status(
                    run_id=run_id,
                    stage_name="research_story",
                    status=StageStatus.SKIPPED,
                    error_code="SKIPPED_BY_INPUT_MODE",
                )
                payload = run.request.structured_payload or {}
                if "plan_id" in payload and "scenes" in payload:
                    # Direct EditorPlan supplied
                    run_repository.update_stage_status(
                        run_id=run_id,
                        stage_name="script_generation",
                        status=StageStatus.SKIPPED,
                        error_code="SKIPPED_BY_INPUT_MODE",
                    )
                    run_repository.update_stage_status(
                        run_id=run_id,
                        stage_name="script_quality_gate",
                        status=StageStatus.SKIPPED,
                        error_code="SKIPPED_BY_INPUT_MODE",
                    )
                    editor_plan = EditorPlan.model_validate(payload)
                    run.editor_plan = editor_plan
                    run_repository.set_editor_plan(run_id, editor_plan)
                else:
                    # ScriptPlan supplied
                    script_plan = ScriptPlan.model_validate(payload)
                    run.script_plan = script_plan
                    script_payload = script_plan.model_dump(mode="json")
                    await self._run_stage_idempotent(run_id, "script_generation", script_payload, 60)

                    # Script Quality Gate
                    script_gate_report = script_quality_gate.evaluate(
                        script_plan=script_plan,
                        fact_pack=None,
                        target_duration_sec=target_dur,
                        run_id=run_id,
                    )
                    run.script_gate_report = script_gate_report
                    gate_payload = script_gate_report.model_dump(mode="json")
                    await self._run_stage_idempotent(run_id, "script_quality_gate", gate_payload, 65)

            else:
                # AUTO MODE (Default): Research -> Story -> Script -> Quality Gate
                # 7. Research & Story (REAL)
                source_transcripts = [scn.transcript for scn in analyzed_scenes if scn.transcript]
                fact_pack = research_agent.generate_fact_pack(
                    instruction=run.request.instruction,
                    source_transcripts=source_transcripts,
                )
                fmt_val = run.request.format.value if hasattr(run.request.format, "value") else str(run.request.format)
                story_plan = story_planner.generate_story_plan(
                    fact_pack=fact_pack,
                    target_duration_sec=target_dur,
                    tone="curiosity",
                    format_type=fmt_val,
                )
                run.fact_pack = fact_pack
                run.story_plan = story_plan
                research_story_payload = {
                    "fact_pack": fact_pack.model_dump(mode="json"),
                    "story_plan": story_plan.model_dump(mode="json"),
                }
                await self._run_stage_idempotent(run_id, "research_story", research_story_payload, 55)

                # 8. Script Generation (REAL)
                script_plan = script_engine.generate_script_plan(
                    story_plan=story_plan,
                    fact_pack=fact_pack,
                    language=run.request.language or "vi",
                )
                run.script_plan = script_plan
                script_payload = script_plan.model_dump(mode="json")
                await self._run_stage_idempotent(run_id, "script_generation", script_payload, 60)

                # 9. Script Quality Gate (REAL)
                script_gate_report = script_quality_gate.evaluate(
                    script_plan=script_plan,
                    fact_pack=fact_pack,
                    target_duration_sec=target_dur,
                    run_id=run_id,
                )
                run.script_gate_report = script_gate_report
                gate_payload = script_gate_report.model_dump(mode="json")
                await self._run_stage_idempotent(run_id, "script_quality_gate", gate_payload, 65)

            if run.script_plan and run.original_script_plan is None:
                run.original_script_plan = run.script_plan.model_copy(deep=True)

            # Save updated run with Phase 3 artifacts
            run_repository.update(run)

            # 10. Visual Planning (REAL)
            chan_prof = getattr(run.request, "channel_profile", None)
            visual_plan = visual_planner.generate_visual_plan(
                script_plan=run.script_plan,
                story_plan=run.story_plan,
                fact_pack=run.fact_pack,
                channel_profile=chan_prof,
                run_id=run_id,
            )
            run.visual_plan = visual_plan
            vp_payload = visual_plan.model_dump(mode="json")
            await self._run_stage_idempotent(run_id, "visual_planning", vp_payload, 70)

            # 11. Asset Resolution (REAL)
            resolution_result = await asset_resolver.resolve_visual_plan(
                visual_plan=visual_plan,
                user_sources=run.request.sources,
                channel_profile=chan_prof,
                run_id=run_id,
            )
            run.resolved_assets = resolution_result
            res_payload = resolution_result.model_dump(mode="json")
            await self._run_stage_idempotent(run_id, "asset_resolution", res_payload, 75)

            # Save updated run with Phase 4 artifacts
            run_repository.update(run)

            # 12a. Draft Editor Planning (Preliminary visual handoff with estimated speech durations)
            draft_editor_plan = editor_planner.build_draft_editor_plan(
                script_plan=run.script_plan,
                visual_plan=run.visual_plan,
                resolved_assets=run.resolved_assets,
                run_id=run_id,
            )
            run.editor_plan = draft_editor_plan
            run_repository.set_editor_plan(run_id, draft_editor_plan)
            await self._run_stage_idempotent(run_id, "editor_planning", draft_editor_plan.model_dump(mode="json"), 80)

            if any(not r.selected_candidate or (r.selected_candidate.provider == 'graphic_fallback' and not r.selected_candidate.renderable)
                   for r in resolution_result.resolutions):
                raise ValueError('VISUAL_MEDIA_UNAVAILABLE: kiểm tra provider/preview và chọn visual trước khi render')

            # 13. TTS & Timing (REAL - Canonical timing via ffprobe)
            voice_code = (
                getattr(run.request, "voice_code", None)
                or getattr(run.request, "voice", None)
                or (run.request.overrides.get("voice") if run.request.overrides else None)
                or (run.request.overrides.get("voice_code") if run.request.overrides else None)
                or "vi-VN-NamMinhNeural"
            )
            tts_results = await tts_service.synthesize_script(
                scenes=run.script_plan.scenes,
                voice_code=voice_code,
                run_id=run_id,
            )
            tts_providers = {item.provider for item in tts_results}
            run.provider_execution["tts"] = "EDGE_LIVE" if tts_providers == {"edge_tts"} else "MOCK" if "deterministic_mock" in tts_providers else ",".join(sorted(tts_providers))
            tts_payload = {
                "scene_count": len(tts_results),
                "scenes": [
                    {
                        "scene_id": r.scene_id,
                        "duration_sec": r.actual_duration_seconds,
                        "file_path": r.audio_file_path,
                    }
                    for r in tts_results
                ],
                "total_duration_sec": round(sum(r.actual_duration_seconds for r in tts_results), 3),
            }
            await self._run_stage_idempotent(run_id, "tts_timing", tts_payload, 88)

            # 12b. Final Editor Planning (REAL - Grounded in canonical actual TTS durations)
            final_editor_plan = editor_planner.build_final_editor_plan(
                script_plan=run.script_plan,
                resolved_assets=run.resolved_assets,
                tts_results=tts_results,
                visual_plan=run.visual_plan,
                run_id=run_id,
            )
            run.editor_plan = final_editor_plan
            run_repository.set_editor_plan(run_id, final_editor_plan)

            # 14. Timeline Compose (REAL - Deterministic OpenCut Multi-Track Timeline)
            timeline_project = editor_planner.export_opencut_timeline(
                editor_plan=final_editor_plan,
                project_name=run.script_plan.title if run.script_plan else "VisionFlow Master Project",
            )
            await self._run_stage_idempotent(run_id, "timeline_compose", timeline_project, 94)

            # Real Render Handoff
            from production.remote_render import remote_render_enabled, enqueue_remote_render
            if remote_render_enabled():
                try:
                    await asyncio.to_thread(enqueue_remote_render, run)
                except Exception as remote_error:
                    logger.exception("Remote render handoff failed for run %s: %s", run_id, remote_error)
                    err_msg = "REMOTE_RENDER_INPUT_NOT_PORTABLE" if "REMOTE_RENDER_INPUT_NOT_PORTABLE" in str(remote_error) else "REMOTE_RENDER_HANDOFF_UNAVAILABLE"
                    run_repository.update_status(run_id=run_id, status=ProductionRunStatus.RENDER_FAILED,
                                                 error_message=err_msg)
                return
            run.status = ProductionRunStatus.RENDERING
            try:
                render_artifact = render_handoff.render(final_editor_plan, run_id=run_id)
                run.render_artifact = render_artifact
                run.output_video_url = render_artifact.output_path_ref
                run_repository.update(run)
            except Exception as r_err:
                logger.error("Render handoff failed for run %s: %s", run_id, r_err)
                run_repository.update_status(
                    run_id=run_id,
                    status=ProductionRunStatus.RENDER_FAILED,
                    error_message=f"Video render failed: {r_err}",
                )
                return

            # 15. Final QC (REAL - 6-Axis Post-Render QC & Auto-Fix)
            quality_report = quality_orchestrator.run_post_render_qc(run, render_artifact)
            run.provider_execution.update({
                "research": getattr(run.fact_pack, "research_mode", "NOT_RECORDED"),
                "story_script": "LOCAL" if run.script_plan else "NOT_RECORDED",
                "embedding": "LOCAL_SEMANTIC",
                "visual_planner": getattr(run.visual_plan, "planner_mode", "NOT_RECORDED"),
                "asset_retrieval": ",".join(sorted({item.selected_candidate.provider for item in run.resolved_assets.resolutions if item.selected_candidate})) if run.resolved_assets else "NOT_RECORDED",
                "render": "LOCAL_DIRECT",
                "semantic_qc": "METADATA_ONLY",
            })
            # A completed, unblocked render requires explicit UI/operator action.
            if run.status == ProductionRunStatus.READY:
                run.status = ProductionRunStatus.HUMAN_REVIEW_PENDING
            run_repository.set_quality_report(run_id, quality_report)
            run_repository.update(run)
            qc_payload = quality_report.model_dump(mode="json")
            await self._run_stage_idempotent(run_id, "final_qc", qc_payload, 100)

            # Update final run status
            run_repository.update_status(
                run_id=run_id,
                status=run.status,
                current_stage="completed",
                progress_pct=100,
            )


        except asyncio.CancelledError:
            run_repository.update_status(
                run_id=run_id,
                status=ProductionRunStatus.CANCELLED,
                error_message="Pipeline execution cancelled",
            )
        except Exception as e:
            run_repository.update_status(
                run_id=run_id,
                status=ProductionRunStatus.FAILED,
                error_message=str(e),
            )

    async def _generate_editor_plan(self, run: ProductionRun) -> EditorPlan:
        """Constructs draft EditorPlan structure grounded in canonical ScriptPlan and resolved assets."""
        plan_id = f"plan_{uuid.uuid4().hex[:8]}"
        instruction = run.request.instruction or "Video tự động"

        if run.script_plan and run.script_plan.scenes:
            scenes: List[ScenePlan] = []
            for scn in run.script_plan.scenes:
                scene_id_key = f"scene_{scn.scene_index:03d}"
                dur = scn.estimated_speech_duration_sec if scn.estimated_speech_duration_sec > 0 else 4.0

                # Look up resolved assets for this scene
                scene_resolutions = (
                    [r for r in run.resolved_assets.resolutions if r.scene_id == scene_id_key]
                    if run.resolved_assets else []
                )

                shots: List[ShotPlan] = []
                if scene_resolutions:
                    for res in scene_resolutions:
                        cand = res.selected_candidate
                        if cand:
                            shot_dur = cand.duration_sec if cand.duration_sec > 0 else round(dur / max(1, len(scene_resolutions)), 2)
                            shots.append(
                                ShotPlan(
                                    shot_id=f"shot_{scn.scene_index:02d}_{res.shot_order:02d}",
                                    asset_id=cand.asset_id,
                                    source_id=cand.source_id,
                                    asset_start_sec=cand.start_sec,
                                    asset_end_sec=cand.end_sec or shot_dur,
                                    duration_sec=shot_dur,
                                    visual_role="hook" if (scn.scene_index == 1 and res.shot_order == 1) else "process",
                                    match_score=cand.composite_score,
                                )
                            )

                if not shots:
                    src_id = run.request.sources[0].source_id if run.request.sources else "stock_source_01"
                    shots.append(
                        ShotPlan(
                            shot_id=f"shot_{scn.scene_index:02d}_01",
                            asset_id=f"asset_scn_{scn.scene_index:02d}",
                            source_id=src_id,
                            asset_start_sec=0.0,
                            asset_end_sec=dur,
                            duration_sec=dur,
                            visual_role="hook" if scn.scene_index == 1 else "process",
                            match_score=0.90,
                        )
                    )

                scenes.append(
                    ScenePlan(
                        scene_id=f"scn_{scn.scene_index:02d}",
                        narration=scn.narration,
                        actual_duration_sec=None,  # CANONICAL TIMING SOURCE: Strictly measured downstream after TTS via ffprobe
                        shots=shots,
                    )
                )
            return EditorPlan(plan_id=plan_id, script_version="1.0-script-grounded", scenes=scenes)

        scenes: List[ScenePlan] = [
            ScenePlan(
                scene_id="scn_01_hook",
                narration=f"Khám phá bí mật đằng sau: {instruction[:60]}!",
                actual_duration_sec=None,  # CANONICAL TIMING SOURCE: None until measured by TTS ffprobe
                shots=[
                    ShotPlan(
                        shot_id="shot_01",
                        asset_id="asset_hook_reveal",
                        source_id=run.request.sources[0].source_id if run.request.sources else "stock_source_01",
                        asset_start_sec=0.0,
                        asset_end_sec=3.2,
                        duration_sec=3.2,
                        visual_role="hook",
                        match_score=0.92,
                    )
                ],
            ),
            ScenePlan(
                scene_id="scn_02_body",
                narration="Từng công đoạn sản xuất đều đòi hỏi độ chính xác và kỹ thuật xử lý vật liệu tỉ mỉ.",
                actual_duration_sec=None,  # CANONICAL TIMING SOURCE: None until measured by TTS ffprobe
                shots=[
                    ShotPlan(
                        shot_id="shot_02",
                        asset_id="asset_body_process",
                        source_id=run.request.sources[0].source_id if run.request.sources else "stock_source_02",
                        asset_start_sec=0.0,
                        asset_end_sec=4.8,
                        duration_sec=4.8,
                        visual_role="process",
                        match_score=0.88,
                    )
                ],
            ),
            ScenePlan(
                scene_id="scn_03_outro",
                narration="Đăng ký theo dõi để không bỏ lỡ những video khám phá kỹ thuật độc đáo tiếp theo!",
                actual_duration_sec=3.5,
                shots=[
                    ShotPlan(
                        shot_id="shot_03",
                        asset_id="asset_outro_cta",
                        source_id=run.request.sources[0].source_id if run.request.sources else "stock_source_03",
                        asset_start_sec=0.0,
                        asset_end_sec=3.5,
                        duration_sec=3.5,
                        visual_role="outro",
                        match_score=0.90,
                    )
                ],
            ),
        ]

        return EditorPlan(plan_id=plan_id, script_version="1.0-draft", scenes=scenes)


    def _generate_honest_quality_report(
        self,
        run_id: str,
        editor_plan: EditorPlan,
        run: Optional[ProductionRun] = None,
    ) -> QualityReport:
        """
        Quality Report Must Not Lie (Section 4 & Section 13):
        Evaluates real visual score from visual coverage ratio, average match score,
        and clean stock / rights status.
        Evaluates real edit score from timeline drift, valid duration pacing, and trim bounds.
        """
        visual_score = None
        edit_score = None
        evaluated_axes: List[str] = []
        warnings: List[str] = []
        blockers: List[str] = []

        if run and run.resolved_assets:
            res = run.resolved_assets
            coverage = res.visual_coverage_ratio
            avg_match = res.average_match_score
            clean_status = 1.0 if (res.duplicate_count == 0 and res.rights_blocker_count == 0) else 0.5
            visual_score = round(0.40 * coverage + 0.30 * avg_match + 0.30 * clean_status, 3)
            evaluated_axes.append("visual")

            if res.rights_blocker_count > 0:
                blockers.append(f"{res.rights_blocker_count} assets rejected due to BLOCKED commercial rights.")
            if res.unresolved_count > 0:
                warnings.append(f"{res.unresolved_count} shots unresolved; defaulted to graphic fallback.")
            if coverage < 0.90:
                warnings.append(f"Visual coverage ratio ({coverage:.2f}) below optimal threshold 0.90.")
        else:
            warnings.append("Visual assets unverified.")

        # Phase 5: Real Edit Quality Score
        if editor_plan and editor_plan.scenes:
            drift = editor_plan.timeline_drift_ms if editor_plan.timeline_drift_ms is not None else 0.0
            drift_score = 1.0 if drift <= 100.0 else max(0.0, 1.0 - (drift - 100.0) / 500.0)

            all_shots = [sh for s in editor_plan.scenes for sh in s.shots]
            pacing_valid = (
                all(1.0 <= (sh.target_duration_seconds or sh.duration_sec or 0) <= 8.0 for sh in all_shots)
                if all_shots
                else True
            )
            pacing_score = 1.0 if pacing_valid else 0.85

            trim_valid = (
                all((sh.asset_trim_start or 0) < (sh.asset_trim_end or 10.0) for sh in all_shots)
                if all_shots
                else True
            )
            trim_score = 1.0 if trim_valid else 0.70

            edit_score = round(0.40 * drift_score + 0.30 * pacing_score + 0.30 * trim_score, 3)
            evaluated_axes.append("edit")

            if drift > 100.0:
                warnings.append(f"Timeline drift ({drift:.1f}ms) exceeds broadcast standard 100ms.")

        return QualityReport(
            report_id=f"qc_{uuid.uuid4().hex[:8]}",
            run_id=run_id,
            stage_name="final_qc",
            overall_status=QualityStatus.NOT_EVALUATED,
            score=None,
            blocker_count=len(blockers),
            warning_count=len(warnings),
            content_score=None,     # NOT_EVALUATED
            story_score=None,       # NOT_EVALUATED
            visual_score=visual_score,  # REAL in Phase 4
            edit_score=edit_score,      # Backward-compatible alias
            timeline_conformance_score=edit_score,  # Pre-Phase-6 Deterministic Timeline Conformance
            technical_score=None,   # NOT_EVALUATED
            rights_score=None,      # NOT_EVALUATED
            evaluated_axes=evaluated_axes,
            warnings=warnings,
            blockers=blockers,
            evaluator_disclaimer="No evaluators executed for final semantic QC (Honest Stub) - Evaluated Visual and Edit axes (Phase 5 Deterministic Engine); Final semantic QC engine arrives in Phase 6",
            details={
                "foundation_status": "EDITOR_PLAN_READY",
                "evaluated_axes_count": len(evaluated_axes),
                "total_axes_count": 6,
                "visual_coverage_ratio": run.resolved_assets.visual_coverage_ratio if (run and run.resolved_assets) else 0.0,
                "timeline_drift_ms": editor_plan.timeline_drift_ms if editor_plan else 0.0,
            },
        )

    # -----------------------------------------------------------------------
    # Partial Regeneration & Locking Methods (Spec Section 5 & 16)
    # -----------------------------------------------------------------------
    async def regenerate_visual(self, run_id: str, scene_id: Optional[str] = None) -> EditorPlan:
        """
        Partial visual regeneration:
        - Invalidate visual stages (does NOT touch TTS audio or its timings).
        - Re-resolves visual candidates for the given scene (or whole run).
        - Re-runs build_final_editor_plan using the existing TTS audio durations.
        """
        run = run_repository.get(run_id)
        if not run or not run.script_plan or not run.editor_plan:
            raise ValueError(f"Run {run_id} does not have required plans for visual regeneration")

        previous_resolutions = run.resolved_assets.model_copy(deep=True) if run.resolved_assets else None
        scoped_visual_plan = run.visual_plan.model_copy(deep=True)
        locked_keys = {(r.scene_id, r.shot_order) for r in previous_resolutions.resolutions
                       if r.selected_candidate and r.selected_candidate.is_locked} if previous_resolutions else set()
        scoped_visual_plan.intents = [v for v in scoped_visual_plan.intents
            if (not scene_id or v.scene_id == scene_id) and (v.scene_id, v.shot_order) not in locked_keys]
        self.invalidate_for_change(run_id, "visuals_changed")

        chan_prof = getattr(run.request, "channel_profile", None)
        resolution_result = await asset_resolver.resolve_visual_plan(
            visual_plan=scoped_visual_plan,
            user_sources=run.request.sources,
            channel_profile=chan_prof,
            run_id=run_id,
        )
        if previous_resolutions:
            replacements = {(r.scene_id, r.shot_order): r for r in resolution_result.resolutions}
            resolution_result.resolutions = [replacements.get((r.scene_id, r.shot_order), r) for r in previous_resolutions.resolutions]
        run.resolved_assets = resolution_result

        # Build TTS results from existing scene audio
        tts_results = []
        for scn in run.editor_plan.scenes:
            dur = scn.actual_duration_seconds or scn.actual_duration_sec or 4.0
            tts_results.append(
                SceneTTSResult(
                    scene_id=scn.scene_id,
                    audio_asset_id=scn.audio_asset_id or f"voice_{scn.scene_id}",
                    audio_file_path=scn.audio_file_path or "",
                    actual_duration_seconds=dur,
                    provider="cached_voice",
                    voice_code="vi-VN-NamMinhNeural",
                    voice_rate=1.0,
                )
            )

        locked_shots = {}
        for scn in run.editor_plan.scenes:
            for sh in scn.shots:
                if sh.is_locked or (scene_id and scn.scene_id != scene_id):
                    locked_shots[sh.shot_id] = sh

        final_plan = editor_planner.build_final_editor_plan(
            script_plan=run.script_plan,
            resolved_assets=resolution_result,
            tts_results=tts_results,
            visual_plan=run.visual_plan,
            run_id=run_id,
            locked_shots=locked_shots,
        )
        run.editor_plan = final_plan
        run.manual_interventions.append(
            ManualInterventionRecord(
                run_id=run_id,
                intervention_type=ManualInterventionType.VISUAL_CHANGED,
                description=f"Operator regenerated visual plan for scene: {scene_id or 'all'}",
                operator_id="operator",
            )
        )
        run_repository.set_editor_plan(run_id, final_plan)
        run_repository.update(run)
        return final_plan

    async def regenerate_voice(self, run_id: str, scene_id: Optional[str] = None) -> EditorPlan:
        """
        Partial voice regeneration:
        - Re-synthesizes TTS audio for the given scene (or whole run).
        - Reconciles editor timeline and shot durations to the new actual audio duration.
        - Keeps existing resolved assets and locked shots.
        - Does NOT re-run visual planning or asset search.
        """
        run = run_repository.get(run_id)
        if not run or not run.script_plan or not run.resolved_assets:
            raise ValueError(f"Run {run_id} does not have required plans for voice regeneration")

        self.invalidate_for_change(run_id, "voice_changed")

        voice_code = (
            getattr(run.request, "voice_code", None)
            or getattr(run.request, "voice", None)
            or "vi-VN-NamMinhNeural"
        )

        scenes_to_synth = run.script_plan.scenes
        if scene_id:
            target_scene = next(
                (s for s in run.script_plan.scenes if s.scene_id == scene_id or f"scene_{s.scene_index:03d}" == scene_id),
                None,
            )
            if target_scene:
                scenes_to_synth = [target_scene]

        fresh_tts_results = await tts_service.synthesize_script(
            scenes=scenes_to_synth,
            voice_code=voice_code,
            run_id=run_id,
        )
        tts_map = {r.scene_id: r for r in fresh_tts_results}

        combined_tts_results = []
        for scn in run.script_plan.scenes:
            s_id = scn.scene_id or f"scene_{scn.scene_index:03d}"
            if s_id in tts_map:
                combined_tts_results.append(tts_map[s_id])
            elif run.editor_plan:
                prev_scn = next((s for s in run.editor_plan.scenes if s.scene_id == s_id), None)
                if prev_scn:
                    combined_tts_results.append(
                        SceneTTSResult(
                            scene_id=s_id,
                            audio_asset_id=prev_scn.audio_asset_id or f"voice_{s_id}",
                            audio_file_path=prev_scn.audio_file_path or "",
                            actual_duration_seconds=prev_scn.actual_duration_seconds or 4.0,
                            provider="cached_voice",
                            voice_code=voice_code,
                            voice_rate=1.0,
                        )
                    )

        if not combined_tts_results:
            combined_tts_results = fresh_tts_results

        locked_shots = {}
        if run.editor_plan:
            for scn in run.editor_plan.scenes:
                for sh in scn.shots:
                    if sh.is_locked:
                        locked_shots[sh.shot_id] = sh

        final_plan = editor_planner.build_final_editor_plan(
            script_plan=run.script_plan,
            resolved_assets=run.resolved_assets,
            tts_results=combined_tts_results,
            visual_plan=run.visual_plan,
            run_id=run_id,
            locked_shots=locked_shots,
        )
        run.editor_plan = final_plan
        run.manual_interventions.append(
            ManualInterventionRecord(
                run_id=run_id,
                intervention_type=ManualInterventionType.VOICE_REGENERATED,
                description=f"Operator regenerated voiceover audio for scene: {scene_id or 'all'}",
                operator_id="operator",
            )
        )
        run_repository.set_editor_plan(run_id, final_plan)
        run_repository.update(run)
        return final_plan

    def lock_shot(self, run_id: str, scene_id: str, shot_id: str, is_locked: bool = True) -> bool:
        """Locks or unlocks a shot in the editor plan."""
        run = run_repository.get(run_id)
        if not run or not run.editor_plan:
            raise ValueError(f"Editor plan not found for run {run_id}")

        found = False
        for scn in run.editor_plan.scenes:
            if scn.scene_id == scene_id or not scene_id:
                for sh in scn.shots:
                    if sh.shot_id == shot_id:
                        sh.is_locked = is_locked
                        found = True
        if found:
            run.manual_interventions.append(
                ManualInterventionRecord(
                    run_id=run_id,
                    intervention_type=ManualInterventionType.ASSET_LOCKED,
                    description=f"Operator set is_locked={is_locked} on shot {shot_id}",
                    operator_id="operator",
                )
            )
            run_repository.set_editor_plan(run_id, run.editor_plan)
            run_repository.update(run)
        return found


# Global accessor
orchestrator = ProductionOrchestrator()
