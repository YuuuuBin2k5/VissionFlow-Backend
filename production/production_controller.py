"""
FastAPI Router for VisionFlow Auto Production System
Endpoints for launching autonomous video generation, checking stage progress, and retrieving plans.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pathlib import Path
import uuid
import json
import subprocess
from fastapi import APIRouter, HTTPException, Query, status, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from production.contracts import (
    AssetResolutionResult,
    AutoVideoRequest,
    ChannelProfileRecommendation,
    EditorPlan,
    ManualInterventionRecord,
    InterventionSource,
    ProductionRun,
    QualityReport,
    RightsState,
    RunEnvironment,
    ReviewSource,
    SceneAssetResolution,
    SceneFeedbackItem,
    SceneSearchFilter,
    SceneSearchResult,
    ScriptDiffGroundTruth,
    ScriptPlan,
    SourceAssetRecord,
    SourceInput,
    SourceKind,
    SourceSceneRecord,
    VisualPlan,
)
from production.config_loader import config_loader
from production.input_normalizer import InputNormalizer
from production.orchestrator import orchestrator
from production.pilot_learning import pilot_learning_service
from production.repositories.run_repository import run_repository


router = APIRouter(prefix="/production", tags=["Auto Production"])
auto_production_router = APIRouter(prefix="/auto-production", tags=["Auto Production Spec v1"])


class CreateRunPayload(BaseModel):
    input_mode: str = "AUTO"
    instruction: Optional[str] = None
    raw_script: Optional[str] = None
    structured_payload: Optional[Dict[str, Any]] = None
    format: str = "auto"
    language: str = "vi"
    channel_profile_id: Optional[str] = None
    target_duration_sec: Optional[float] = None
    review_mode: str = "final_only"
    run_environment: str = "DEV"
    sources: Optional[List[Dict[str, Any]]] = None
    overrides: Optional[Dict[str, Any]] = None


class RetryStagePayload(BaseModel):
    stage_name: str


class InvalidatePayload(BaseModel):
    reason: str  # e.g. "visuals_changed", "voice_changed"


async def _handle_create_run(payload: CreateRunPayload) -> ProductionRun:
    if not payload.instruction and not payload.sources and not payload.raw_script and not payload.structured_payload:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Either instruction, sources, raw_script, or structured_payload must be provided.",
        )
    try:
        normalized_request = InputNormalizer.normalize(
            raw_instruction=payload.instruction,
            raw_sources=payload.sources,
            requested_format=payload.format,
            language=payload.language,
            channel_profile_id=payload.channel_profile_id,
            target_duration_sec=payload.target_duration_sec,
            review_mode=payload.review_mode,
            overrides=payload.overrides,
            input_mode=payload.input_mode,
            raw_script=payload.raw_script,
            structured_payload=payload.structured_payload,
            run_environment=payload.run_environment,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid request input: {e}")

    run = orchestrator.create_run(normalized_request)
    await orchestrator.start_run(run.id)
    return run


def _handle_get_run(run_id: str) -> ProductionRun:
    run = run_repository.get(run_id)
    from production.remote_render import remote_render_enabled, load_remote_run
    if remote_render_enabled():
        remote = load_remote_run(run_id)
        if remote:
            # Preserve later operator decisions in the existing review repository.
            if not run or not run.human_review:
                run = remote
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Run {run_id} not found")
    return run


def _handle_get_pilot_run_summary(run_id: str) -> Dict[str, Any]:
    """Operator-facing, non-secret evidence for one real pilot run."""
    run = _handle_get_run(run_id)
    source_mix = {"user_source_clips": 0, "scene_library_clips": 0, "stock_clips": 0, "graphic_fallback_shots": 0, "static_images": 0}
    selected = []
    if run.resolved_assets:
        selected = [item.selected_candidate for item in run.resolved_assets.resolutions if item.selected_candidate]
    for item in selected:
        provider = item.provider.lower()
        if provider == "user_source": source_mix["user_source_clips"] += 1
        elif "scene_library" in provider: source_mix["scene_library_clips"] += 1
        elif "stock" in provider or "pexels" in provider: source_mix["stock_clips"] += 1
        elif provider == "graphic_fallback": source_mix["graphic_fallback_shots"] += 1
        if "image" in str(item.provenance.get("origin", "")).lower(): source_mix["static_images"] += 1
    total_shots = len(selected)
    source_mix["graphic_fallback_ratio"] = round(source_mix["graphic_fallback_shots"] / max(1, total_shots), 3)

    encoding: Dict[str, Any] = {}
    artifact = run.render_artifact
    media_path = Path(artifact.internal_file_path) if artifact and artifact.internal_file_path else None
    if media_path and media_path.is_file():
        try:
            result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration,size,bit_rate:stream=codec_type,codec_name,profile,pix_fmt,width,height,r_frame_rate,bit_rate", "-of", "json", str(media_path)], capture_output=True, text=True, check=True)
            encoding = json.loads(result.stdout)
        except Exception as exc:
            encoding = {"probe_error": str(exc)}

    provider_execution = dict(run.provider_execution)
    provider_execution.setdefault("research", getattr(run.fact_pack, "research_mode", "NOT_RECORDED"))
    provider_execution.setdefault("story_script", "LOCAL" if run.script_plan else "NOT_RECORDED")
    provider_execution.setdefault("visual_planner", getattr(run.visual_plan, "planner_mode", "NOT_RECORDED"))
    provider_execution.setdefault("asset_retrieval", "NOT_RECORDED" if not selected else ",".join(sorted({item.provider for item in selected})))
    provider_execution.setdefault("tts", "NOT_RECORDED")
    provider_execution.setdefault("render", "LOCAL_DIRECT" if artifact else "NOT_RECORDED")
    provider_execution.setdefault("semantic_qc", "METADATA_ONLY" if run.quality_report else "NOT_RECORDED")
    return {
        "run_id": run.id, "run_environment": run.run_environment, "topic": run.request.instruction,
        "status": run.status, "duration_seconds": artifact.duration_seconds if artifact else None,
        "provider_execution": provider_execution, "full_live_e2e": run.full_live_e2e,
        "quality": run.quality_report.model_dump(mode="json") if run.quality_report else None,
        "cost": run.cost_telemetry.model_dump(mode="json") if run.cost_telemetry else None,
        "latency": run.latency_telemetry.model_dump(mode="json") if run.latency_telemetry else None,
        "auto_fixes": run.auto_fix_history, "human_review": run.human_review.model_dump(mode="json") if run.human_review else None,
        "real_operator_interventions": [item.model_dump(mode="json") for item in run.manual_interventions if item.intervention_source == InterventionSource.REAL_OPERATOR],
        "real_user_source_count": run.real_user_source_count, "fixture_source_count": run.fixture_source_count,
        "source_mix": source_mix, "encoding": encoding,
    }


def _handle_get_stages(run_id: str):
    run = _handle_get_run(run_id)
    return run.stages


def _handle_get_editor_plan(run_id: str) -> EditorPlan:
    run = _handle_get_run(run_id)
    if not run.editor_plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"EditorPlan not available for run {run_id}")
    return run.editor_plan


def _handle_get_quality_report(run_id: str) -> QualityReport:
    run = _handle_get_run(run_id)
    if not run.quality_report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"QualityReport not available for run {run_id}")
    return run.quality_report


def _handle_get_visual_plan(run_id: str) -> VisualPlan:
    run = _handle_get_run(run_id)
    if not run.visual_plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"VisualPlan not available for run {run_id}")
    return run.visual_plan


def _handle_get_resolved_assets(run_id: str) -> AssetResolutionResult:
    run = _handle_get_run(run_id)
    if not run.resolved_assets:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Resolved assets not available for run {run_id}")
    return run.resolved_assets


class SwapAssetPayload(BaseModel):
    scene_id: str
    shot_order: int = 1
    new_asset_id: str
    reason: Optional[str] = "Operator swapped asset"
    operator_id: Optional[str] = "operator"


def _handle_swap_asset(run_id: str, payload: SwapAssetPayload) -> SceneAssetResolution:
    from production.asset_resolver import asset_resolver
    run = _handle_get_run(run_id)
    if not run.resolved_assets:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"No resolved assets available for run {run_id}")

    prev_res = next((r for r in run.resolved_assets.resolutions if r.scene_id == payload.scene_id and r.shot_order == payload.shot_order), None)
    rejected_id = prev_res.selected_candidate.asset_id if (prev_res and prev_res.selected_candidate) else "unknown"

    try:
        updated_res = asset_resolver.swap_asset(
            resolution_result=run.resolved_assets,
            scene_id=payload.scene_id,
            shot_order=payload.shot_order,
            new_asset_id=payload.new_asset_id,
        )
        try:
            sc_idx = int(''.join(filter(str.isdigit, payload.scene_id)) or 1)
            pilot_learning_service.record_visual_swap_ground_truth(
                run_id=run_id,
                scene_index=sc_idx,
                rejected_asset_id=rejected_id,
                selected_replacement_id=payload.new_asset_id,
                reason=payload.reason or "Operator swapped asset",
                operator_id=payload.operator_id or "operator",
            )
        except Exception as gt_err:
            logger.warning("Failed to record visual swap ground truth: %s", gt_err)

        run_repository.update(run)
        return updated_res
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))


async def _handle_retry_stage(run_id: str, payload: RetryStagePayload):
    run = _handle_get_run(run_id)
    stage_names = [s.stage_name for s in run.stages]
    if payload.stage_name not in stage_names:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Stage '{payload.stage_name}' does not exist in run stages: {stage_names}",
        )
    await orchestrator.retry_stage(run_id, payload.stage_name)
    updated = run_repository.get(run_id)
    return updated


def _handle_invalidate(run_id: str, payload: InvalidatePayload):
    run = _handle_get_run(run_id)
    valid_reasons = {"visuals_changed", "voice_changed"}
    if payload.reason not in valid_reasons:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid reason '{payload.reason}'. Must be one of: {list(valid_reasons)}",
        )
    invalidated_stages = orchestrator.invalidate_for_change(run_id, payload.reason)
    updated = run_repository.get(run_id)
    return {
        "run_id": run_id,
        "reason": payload.reason,
        "invalidated_stages": invalidated_stages,
        "status": updated.status,
    }


class IngestSourcePayload(BaseModel):
    uri: Optional[str] = None
    file_ref: Optional[str] = None
    source_type: str = "video"
    rights_state: str = "UNKNOWN"


UPLOADS_DIR = Path("d:/VisionFlow/.uploaded_sources")


async def _handle_upload_source(file: UploadFile = File(...)) -> Dict[str, Any]:
    """Store a browser-selected source and return a USER-provenance descriptor."""
    filename = Path(file.filename or "source").name
    suffix = Path(filename).suffix.lower()
    if suffix not in {".mp4", ".mov", ".webm", ".mp3", ".wav", ".m4a", ".jpg", ".jpeg", ".png"}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported source file type")
    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Uploaded source is empty")
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    target = UPLOADS_DIR / f"usr_{uuid.uuid4().hex}{suffix}"
    target.write_bytes(payload)
    return {"source_id": f"src_{uuid.uuid4().hex[:12]}", "kind": "video", "file_ref": str(target), "rights_state": "UNKNOWN", "provenance": "USER", "filename": filename}


class SearchScenesPayload(BaseModel):
    query: str
    filters: Optional[SceneSearchFilter] = None
    top_k: int = 5


def _sanitize_source_for_client(src: SourceAssetRecord) -> SourceAssetRecord:
    """Masks internal server filesystem paths before sending to client."""
    clone = src.model_copy()
    if clone.storage_ref and not clone.storage_ref.startswith("http"):
        clone.storage_ref = f"/api/v1/auto-production/sources/{clone.id}/media"
    return clone


def _sanitize_scene_for_client(scn: SourceSceneRecord) -> SourceSceneRecord:
    """Masks internal server filesystem paths in keyframes."""
    clone = scn.model_copy()
    clone.keyframes = [f"/api/v1/auto-production/scenes/{clone.id}/keyframes/{i}" for i in range(len(clone.keyframes))]
    return clone


async def _handle_ingest_source(payload: IngestSourcePayload) -> SourceAssetRecord:
    from production.contracts import SourceInput, SourceKind, RightsState
    from production.source_ingest import source_ingest_service, SecurityValidationError

    try:
        r_state = RightsState(payload.rights_state)
    except Exception:
        r_state = RightsState.UNKNOWN

    src_input = SourceInput(
        source_id=f"src_{uuid.uuid4().hex[:8]}",
        kind=SourceKind(payload.source_type) if payload.source_type in [e.value for e in SourceKind] else SourceKind.VIDEO,
        uri=payload.uri,
        file_ref=payload.file_ref,
        rights_state=r_state,
        provenance="USER",
    )

    try:
        record = source_ingest_service.ingest_source(src_input)
        return _sanitize_source_for_client(record)
    except SecurityValidationError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Security rejection: {e}")
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


def _handle_get_source(source_id: str) -> SourceAssetRecord:
    from production.repositories.source_repository import get_source_repository
    repo = get_source_repository()
    src = repo.get(source_id)
    if not src:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Source {source_id} not found")
    return _sanitize_source_for_client(src)


def _handle_list_source_scenes(source_id: str) -> List[SourceSceneRecord]:
    from production.repositories.source_repository import get_scene_repository, get_source_repository
    src = get_source_repository().get(source_id)
    if not src:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Source {source_id} not found")
    scenes = get_scene_repository().list_by_source(source_id)
    return [_sanitize_scene_for_client(s) for s in scenes]


def _handle_get_scene(scene_id: str) -> SourceSceneRecord:
    from production.repositories.source_repository import get_scene_repository
    scn = get_scene_repository().get(scene_id)
    if not scn:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Scene {scene_id} not found")
    return _sanitize_scene_for_client(scn)


def _handle_search_scenes(payload: SearchScenesPayload) -> List[SceneSearchResult]:
    from production.embedding_service import embedding_service
    results = embedding_service.search_scenes(
        query=payload.query,
        filters=payload.filters,
        top_k=payload.top_k,
    )
    for r in results:
        if r.scene:
            r.scene = _sanitize_scene_for_client(r.scene)
    return results


def _handle_export_run(run_id: str) -> Dict[str, Any]:
    """
    Exports a clean, sanitized JSON representation of the current ScriptPlan / EditorPlan
    suitable for copy/pasting into developer JSON mode without leaking server secrets or internal paths.
    """
    run = _handle_get_run(run_id)
    export_data: Dict[str, Any] = {
        "export_version": "1.0",
        "input_mode": run.request.input_mode.value if hasattr(run.request, "input_mode") else "AUTO",
        "format": run.request.format.value if hasattr(run.request, "format") else "short",
        "language": run.request.language,
        "target_duration_sec": run.request.target_duration_sec,
    }
    if run.script_plan:
        export_data["script_plan"] = {
            "title": run.script_plan.title,
            "full_script": run.script_plan.full_script,
            "total_word_count": run.script_plan.total_word_count,
            "estimated_total_duration_sec": run.script_plan.estimated_total_duration_sec,
            "scenes": [
                {
                    "scene_index": s.scene_index,
                    "narration": s.narration,
                    "beat_ref": s.beat_ref,
                    "estimated_speech_duration_sec": s.estimated_speech_duration_sec,
                    "visual_cue": s.visual_cue,
                    "fact_refs": s.fact_refs,
                }
                for s in run.script_plan.scenes
            ],
        }
    if run.editor_plan:
        export_data["editor_plan"] = {
            "plan_id": run.editor_plan.plan_id,
            "script_version": run.editor_plan.script_version,
            "scenes": [
                {
                    "scene_id": scn.scene_id,
                    "narration": scn.narration,
                    "actual_duration_sec": scn.actual_duration_sec,
                    "shots": [
                        {
                            "shot_id": sh.shot_id,
                            "asset_id": sh.asset_id,
                            "duration_sec": sh.duration_sec,
                            "visual_role": sh.visual_role,
                            "match_score": sh.match_score,
                        }
                        for sh in scn.shots
                    ],
                }
                for scn in run.editor_plan.scenes
            ],
        }
    return export_data


class PartialRegenPayload(BaseModel):
    scene_id: Optional[str] = None


class LockShotPayload(BaseModel):
    scene_id: str
    shot_id: str
    is_locked: bool = True


def _handle_get_timeline(run_id: str) -> Dict[str, Any]:
    from production.editor_planner import editor_planner
    run = _handle_get_run(run_id)
    if not run.editor_plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"EditorPlan not available for run {run_id}")
    project_name = run.script_plan.title if run.script_plan else "VisionFlow Master Project"
    return editor_planner.export_opencut_timeline(run.editor_plan, project_name=project_name)


async def _handle_regenerate_visual(run_id: str, payload: PartialRegenPayload):
    try:
        updated_plan = await orchestrator.regenerate_visual(run_id, scene_id=payload.scene_id)
        return {"success": True, "message": "Visual plan regenerated successfully", "plan": updated_plan}
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


async def _handle_regenerate_voice(run_id: str, payload: PartialRegenPayload):
    try:
        updated_plan = await orchestrator.regenerate_voice(run_id, scene_id=payload.scene_id)
        return {"success": True, "message": "Voice audio regenerated and timeline reconciled successfully", "plan": updated_plan}
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


def _handle_lock_shot(run_id: str, payload: LockShotPayload):
    try:
        success = orchestrator.lock_shot(run_id, scene_id=payload.scene_id, shot_id=payload.shot_id, is_locked=payload.is_locked)
        return {"success": success, "message": "Shot lock status updated"}
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


def _handle_get_video(run_id: str):
    import os
    run = _handle_get_run(run_id)
    if not run.render_artifact:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Render artifact not available for run {run_id}")

    if run.render_artifact.storage_ref:
        from fastapi.responses import RedirectResponse
        from production.artifact_storage import get_artifact_storage
        return RedirectResponse(get_artifact_storage().presigned_download(run.render_artifact.storage_ref), status_code=307)
    file_path = getattr(run.render_artifact, "internal_file_path", None)
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rendered video file not found on disk")

    return FileResponse(file_path, media_type="video/mp4", filename=f"{run_id}_final.mp4")


def _handle_trigger_auto_fix(run_id: str):
    from production.quality_orchestrator import quality_orchestrator
    run = _handle_get_run(run_id)
    if not run.render_artifact:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot auto-fix before video is rendered")

    report = quality_orchestrator.run_post_render_qc(run, run.render_artifact)
    run_repository.update(run)
    return {"success": True, "status": run.status, "quality_report": report}


# Register routes on both routers (/production and /auto-production)
for r in [router, auto_production_router]:
    r.add_api_route("/runs", _handle_create_run, methods=["POST"], response_model=ProductionRun, status_code=status.HTTP_201_CREATED)
    r.add_api_route("/runs", lambda limit=20: run_repository.list_all(limit=limit), methods=["GET"], response_model=List[ProductionRun])
    r.add_api_route("/runs/{run_id}", _handle_get_run, methods=["GET"], response_model=ProductionRun)
    r.add_api_route("/runs/{run_id}/stages", _handle_get_stages, methods=["GET"])
    r.add_api_route("/runs/{run_id}/export", _handle_export_run, methods=["GET"])
    r.add_api_route("/runs/{run_id}/editor-plan", _handle_get_editor_plan, methods=["GET"], response_model=EditorPlan)
    r.add_api_route("/runs/{run_id}/timeline", _handle_get_timeline, methods=["GET"])
    r.add_api_route("/runs/{run_id}/video", _handle_get_video, methods=["GET"])
    r.add_api_route("/runs/{run_id}/auto-fix", _handle_trigger_auto_fix, methods=["POST"])
    r.add_api_route("/runs/{run_id}/regenerate/visual", _handle_regenerate_visual, methods=["POST"])
    r.add_api_route("/runs/{run_id}/regenerate/voice", _handle_regenerate_voice, methods=["POST"])
    r.add_api_route("/runs/{run_id}/shots/lock", _handle_lock_shot, methods=["POST"])
    r.add_api_route("/runs/{run_id}/quality-report", _handle_get_quality_report, methods=["GET"], response_model=QualityReport)
    r.add_api_route("/runs/{run_id}/visual-plan", _handle_get_visual_plan, methods=["GET"], response_model=VisualPlan)
    r.add_api_route("/runs/{run_id}/resolved-assets", _handle_get_resolved_assets, methods=["GET"], response_model=AssetResolutionResult)
    r.add_api_route("/runs/{run_id}/assets/swap", _handle_swap_asset, methods=["POST"], response_model=SceneAssetResolution)
    r.add_api_route("/runs/{run_id}/retry", _handle_retry_stage, methods=["POST"], response_model=ProductionRun)
    r.add_api_route("/runs/{run_id}/invalidate", _handle_invalidate, methods=["POST"])

    # Phase 2 Source Intelligence & Scene Library API
    r.add_api_route("/sources/ingest", _handle_ingest_source, methods=["POST"], response_model=SourceAssetRecord, status_code=status.HTTP_201_CREATED)
    r.add_api_route("/sources/{source_id}", _handle_get_source, methods=["GET"], response_model=SourceAssetRecord)
    r.add_api_route("/sources/{source_id}/scenes", _handle_list_source_scenes, methods=["GET"], response_model=List[SourceSceneRecord])
    r.add_api_route("/scenes/{scene_id}", _handle_get_scene, methods=["GET"], response_model=SourceSceneRecord)
    r.add_api_route("/scenes/search", _handle_search_scenes, methods=["POST"], response_model=List[SceneSearchResult])


@router.post("/runs/{run_id}/cancel")
@auto_production_router.post("/runs/{run_id}/cancel")
async def cancel_production_run(run_id: str):
    """Cancel an active production run."""
    run = run_repository.get(run_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Run {run_id} not found")
    await orchestrator.cancel_run(run_id)
    return {"success": True, "message": f"Run {run_id} cancelled"}


@router.get("/config")
@auto_production_router.get("/config")
async def get_production_config():
    """Retrieve runtime defaults and thresholds for the UI."""
    return {
        "production_defaults": config_loader.production_defaults,
        "quality_thresholds": config_loader.quality_thresholds,
    }


# Handler implementations for Phase 7
from production.contracts import HumanReviewRatings, HumanReviewRecord
from production.human_review import human_review_service, HumanReviewError
from production.publishing_bridge import publishing_bridge, PublicationRequest, PublishingSafetyError
from production.storage_lifecycle import storage_lifecycle
from production.render_queue import render_queue
from worker.config.render_profile import resolve_ffmpeg_exe, resolve_ffprobe_exe


class ReviewSubmissionPayload(BaseModel):
    reviewer: str
    ratings: Optional[HumanReviewRatings] = None
    decision: str = "APPROVED"  # APPROVED or CHANGES_REQUESTED
    notes: Optional[str] = None
    changed_scenes: List[int] = Field(default_factory=list)
    scene_feedback: Optional[Dict[int, SceneFeedbackItem]] = None


class PublishSubmissionPayload(BaseModel):
    platform: str = "youtube"
    channel_id: str = "default_channel"
    title: Optional[str] = None
    description: Optional[str] = None
    override_auto_publish: bool = False


class InterventionPayload(BaseModel):
    intervention_type: str
    scene_index: Optional[int] = None
    description: str = ""
    before_value: Optional[Any] = None
    after_value: Optional[Any] = None
    operator_id: str = "operator"


class ScriptEditPayload(BaseModel):
    script_plan: Dict[str, Any]
    operator_id: str = "operator"
    categories: Optional[List[str]] = None


def _handle_submit_review(run_id: str, payload: ReviewSubmissionPayload) -> HumanReviewRecord:
    try:
        return human_review_service.submit_review(
            run_id=run_id,
            reviewer=payload.reviewer,
            ratings=payload.ratings,
            decision=payload.decision,
            notes=payload.notes,
            changed_scenes=payload.changed_scenes,
            scene_feedback=payload.scene_feedback,
            review_source=ReviewSource.REAL_OPERATOR,
            client_source="production_ui",
        )
    except HumanReviewError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


def _handle_get_review(run_id: str) -> HumanReviewRecord:
    rec = human_review_service.get_review(run_id)
    if not rec:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No review found for run {run_id}")
    return rec


def _handle_get_review_dataset() -> List[Dict[str, Any]]:
    return human_review_service.export_dataset()


def _handle_record_intervention(run_id: str, payload: InterventionPayload) -> ManualInterventionRecord:
    try:
        return pilot_learning_service.record_manual_intervention(
            run_id=run_id,
            intervention_type=payload.intervention_type,
            scene_index=payload.scene_index,
            description=payload.description,
            before_value=payload.before_value,
            after_value=payload.after_value,
            operator_id=payload.operator_id,
            intervention_source=InterventionSource.REAL_OPERATOR,
        )
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


def _handle_script_edit(run_id: str, payload: ScriptEditPayload) -> ScriptDiffGroundTruth:
    try:
        script_plan = ScriptPlan.model_validate(payload.script_plan)
        return pilot_learning_service.record_script_edit(
            run_id=run_id,
            edited_script_plan=script_plan,
            operator_id=payload.operator_id,
            categories=payload.categories,
        )
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


def _handle_get_pilot_report(channel_id: Optional[str] = None) -> Dict[str, Any]:
    return pilot_learning_service.compile_pilot_report(channel_id=channel_id)


def _handle_get_recommendations(channel_id: str) -> List[ChannelProfileRecommendation]:
    return pilot_learning_service.generate_channel_recommendations(channel_id)


def _handle_approve_recommendation(channel_id: str, rec_id: str) -> Dict[str, Any]:
    try:
        ok = pilot_learning_service.apply_recommendation(channel_id, rec_id)
        return {"success": ok, "recommendation_id": rec_id, "status": "APPROVED"}
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


def _handle_reject_recommendation(channel_id: str, rec_id: str) -> Dict[str, Any]:
    try:
        ok = pilot_learning_service.reject_recommendation(rec_id)
        return {"success": ok, "recommendation_id": rec_id, "status": "REJECTED"}
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


def _handle_list_pilot_runs(limit: int = 50) -> List[ProductionRun]:
    runs = run_repository.list_all(limit=limit)
    return [r for r in runs if r.run_environment == RunEnvironment.PILOT]


def _handle_publish_run(run_id: str, payload: PublishSubmissionPayload):
    run = run_repository.get(run_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Run {run_id} not found")
    title = payload.title or (run.script_plan.title if run.script_plan else "VisionFlow Short")
    desc = payload.description or (run.script_plan.full_script[:200] if run.script_plan else "")
    req = PublicationRequest(
        run_id=run_id,
        platform=payload.platform,
        channel_id=payload.channel_id,
        title=title,
        description=desc,
        override_auto_publish=payload.override_auto_publish,
    )
    try:
        return publishing_bridge.request_publication(req, run=run)
    except PublishingSafetyError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


def _handle_health_check() -> Dict[str, Any]:
    ffmpeg_p = resolve_ffmpeg_exe()
    ffprobe_p = resolve_ffprobe_exe()
    ffmpeg_ok = os.path.exists(ffmpeg_p.replace('"', ''))
    ffprobe_ok = os.path.exists(ffprobe_p.replace('"', ''))

    storage_stats = storage_lifecycle.get_storage_stats()
    queue_status = render_queue.concurrency.get_status()

    return {
        "status": "HEALTHY" if (ffmpeg_ok and ffprobe_ok) else "DEGRADED",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "components": {
            "ffmpeg": {"available": ffmpeg_ok, "path": ffmpeg_p},
            "ffprobe": {"available": ffprobe_ok, "path": ffprobe_p},
            "database": {"connected": True, "type": "local_resilient_json"},
            "storage": {"tiers": list(storage_stats.keys())},
            "render_queue": {"concurrency": queue_status},
        },
    }


def _handle_observability_metrics() -> Dict[str, Any]:
    runs = run_repository.list_all(limit=200)
    total_runs = len(runs)
    status_counts: Dict[str, int] = {}
    for r in runs:
        st = r.status.value if hasattr(r.status, "value") else str(r.status)
        status_counts[st] = status_counts.get(st, 0) + 1

    ready_count = status_counts.get("READY", 0) + status_counts.get("APPROVED", 0)
    ready_rate = round(ready_count / max(1, total_runs) * 100.0, 1)

    return {
        "total_runs_recorded": total_runs,
        "ready_rate_pct": ready_rate,
        "status_distribution": status_counts,
        "active_queue_jobs": len(render_queue.list_active_jobs()),
        "storage": storage_lifecycle.get_storage_stats(),
    }


# Register Phase 7 Human Review, Publishing, Health & Observability + Pilot Learning API
for r in [router, auto_production_router]:
    r.add_api_route("/sources/upload", _handle_upload_source, methods=["POST"])
    r.add_api_route("/runs/{run_id}/pilot-summary", _handle_get_pilot_run_summary, methods=["GET"])
    r.add_api_route("/runs/{run_id}/review", _handle_submit_review, methods=["POST"], response_model=HumanReviewRecord)
    r.add_api_route("/runs/{run_id}/review", _handle_get_review, methods=["GET"], response_model=HumanReviewRecord)
    r.add_api_route("/reviews/dataset", _handle_get_review_dataset, methods=["GET"])
    r.add_api_route("/runs/{run_id}/interventions", _handle_record_intervention, methods=["POST"], response_model=ManualInterventionRecord)
    r.add_api_route("/runs/{run_id}/script-edit", _handle_script_edit, methods=["POST"], response_model=ScriptDiffGroundTruth)
    r.add_api_route("/pilot/report", _handle_get_pilot_report, methods=["GET"])
    r.add_api_route("/pilot/runs", _handle_list_pilot_runs, methods=["GET"], response_model=List[ProductionRun])
    r.add_api_route("/channels/{channel_id}/recommendations", _handle_get_recommendations, methods=["GET"], response_model=List[ChannelProfileRecommendation])
    r.add_api_route("/channels/{channel_id}/recommendations/{rec_id}/approve", _handle_approve_recommendation, methods=["POST"])
    r.add_api_route("/channels/{channel_id}/recommendations/{rec_id}/reject", _handle_reject_recommendation, methods=["POST"])
    r.add_api_route("/runs/{run_id}/publish", _handle_publish_run, methods=["POST"])
    r.add_api_route("/health", _handle_health_check, methods=["GET"])
    r.add_api_route("/observability", _handle_observability_metrics, methods=["GET"])
