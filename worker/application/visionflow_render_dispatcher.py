"""Dispatch a completed storyboard to the isolated VisionFlow render workflow.

The dispatcher is an anti-corruption boundary: it reads the immutable execution
context through the Control Plane API, never from a database or legacy job.
"""

from __future__ import annotations

from typing import Any, Protocol

from worker.application.visionflow_render_workflow import (
    RenderedArtifact,
    VisionFlowRenderWorkflow,
)
from worker.application.visionflow_quality_assurance import VisionFlowQualityAssurance
from worker.domain.visionflow_qa_contract import RenderArtifactForQa
from worker.domain.visionflow_render_contract import build_visionflow_render_contract


class ExecutionContextGateway(Protocol):
    def get_execution_context(
        self, workflow_run_id: str, *, trace_id: str | None = None
    ) -> dict[str, Any]: ...
    def get_composition(self, workflow_run_id: str, *, trace_id: str | None = None) -> dict[str, Any]: ...
    def get_composition_render_plan(self, workflow_run_id: str, *, trace_id: str | None = None) -> dict[str, Any]: ...
    def open_manual_approval(self, workflow_run_id: str, *, trace_id: str | None = None) -> dict[str, Any]: ...


class VisionFlowRenderDispatcher:
    """Build and execute a render contract only for a STORYBOARDED workflow."""

    def __init__(
        self,
        control_plane: ExecutionContextGateway,
        render_workflow: VisionFlowRenderWorkflow,
        quality_assurance: VisionFlowQualityAssurance | None = None,
    ) -> None:
        self._control_plane = control_plane
        self._render_workflow = render_workflow
        self._quality_assurance = quality_assurance

    def dispatch(self, workflow_run_id: str, *, trace_id: str) -> RenderedArtifact:
        if not workflow_run_id.strip() or len(trace_id) != 32:
            raise ValueError("workflow_run_id and a 32-character trace_id are required")

        context = self._control_plane.get_execution_context(workflow_run_id, trace_id=trace_id)
        if context.get("state") != "STORYBOARDED":
            raise ValueError("render dispatch requires a STORYBOARDED workflow")
        intake = context.get("intake")
        steps = context.get("steps")
        if not isinstance(intake, dict) or not isinstance(steps, dict):
            raise ValueError("execution context must include intake and steps objects")

        script = _required_script(steps.get("script"))
        scenes = _required_scenes(steps.get("storyboard"))
        composition = self._control_plane.get_composition(workflow_run_id, trace_id=trace_id)
        authoritative_plan = self._control_plane.get_composition_render_plan(workflow_run_id, trace_id=trace_id)
        authoritative_fingerprint = _validate_authoritative_render_plan(workflow_run_id, composition, authoritative_plan)
        scenes = _apply_locked_timeline(scenes, composition)
        contract = build_visionflow_render_contract(
            workflow_run_id,
            trace_id,
            intake,
            script,
            scenes,
            composition,
            authoritative_render_plan_fingerprint=authoritative_fingerprint,
        )
        artifact = self._render_workflow.execute(contract)
        if self._quality_assurance is not None:
            self._quality_assurance.execute(
                workflow_run_id,
                RenderArtifactForQa(artifact.object_key, artifact.content_type, artifact.byte_size, artifact.checksum_sha256),
                trace_id=trace_id,
            )
            # QA may only promote a technically valid artifact to RENDERED.
            # This explicit API handoff then opens the separate human-review
            # boundary; the worker never approves or publishes a video.
            self._control_plane.open_manual_approval(workflow_run_id, trace_id=trace_id)
        return artifact


def _required_script(payload: object) -> str:
    if not isinstance(payload, dict) or not isinstance(payload.get("script"), str):
        raise ValueError("execution context is missing scripted output")
    return payload["script"]


def _required_scenes(payload: object) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("scenes"), list):
        raise ValueError("execution context is missing storyboard output")
    scenes = payload["scenes"]
    if not all(isinstance(scene, dict) for scene in scenes):
        raise ValueError("storyboard scenes must be objects")
    return scenes


def _apply_locked_timeline(scenes: list[dict[str, Any]], composition: dict[str, Any]) -> list[dict[str, Any]]:
    """Materialize video-track order and trims from a locked composition.

    The legacy renderer consumes one sequential list of scenes.  This adapter
    keeps that boundary while making track ordering and clip duration an
    actual render input instead of only editor metadata.
    """
    by_id: dict[str, dict[str, Any]] = {}
    for idx, scene in enumerate(scenes):
        sid = str(scene.get("scene_id") or scene.get("id") or "").strip()
        if sid:
            by_id[sid] = scene

        by_id[str(idx + 1)] = scene
        by_id[f"scene_{idx + 1}"] = scene
        by_id[f"scene-{idx + 1}"] = scene
        if isinstance(scene.get("index"), (int, str)):
            by_id[str(scene["index"])] = scene
            by_id[f"scene_{scene['index']}"] = scene

        for key in ("prompt", "visual_prompt", "description", "title", "text"):
            val = str(scene.get(key) or "").strip()
            if val:
                by_id[val] = scene

    video_clips = [
        clip for track in composition.get("tracks", []) if isinstance(track, dict) and track.get("track_type") == "video"
        for clip in track.get("clips", []) if isinstance(clip, dict) and clip.get("source_type") == "scene"
    ]
    if not video_clips:
        raise ValueError("locked composition has no video scene clips")
    materialized: list[dict[str, Any]] = []
    sorted_clips = sorted(video_clips, key=lambda item: int(item.get("timeline_start_ms", 0)))
    for clip_idx, clip in enumerate(sorted_clips):
        source_ref = str(clip.get("source_ref", "")).strip()
        scene = by_id.get(source_ref)
        if scene is None:
            for s in scenes:
                for key in ("visual_prompt", "prompt", "description", "title"):
                    p = str(s.get(key) or "").strip()
                    if p and (source_ref.startswith(p[:30]) or p.startswith(source_ref[:30])):
                        scene = s
                        break
                if scene is not None:
                    break

        if scene is None and clip_idx < len(scenes):
            scene = scenes[clip_idx]

        if scene is None:
            raise ValueError(f"composition references unavailable scene '{source_ref}'")

        duration_ms = clip.get("duration_ms")
        if not isinstance(duration_ms, int) or not 1_000 <= duration_ms <= 90_000:
            raise ValueError("composition video clip duration must be between 1 and 90 seconds")
        materialized.append({
            **scene,
            "duration": duration_ms / 1000.0,
            "composition_transform": clip.get("transform", {}),
            "composition_effects": clip.get("effects", []),
            "composition_keyframes": clip.get("keyframes", []),
        })
    return materialized


def _validate_authoritative_render_plan(workflow_run_id: str, composition: dict[str, Any], plan: dict[str, Any]) -> str:
    fingerprint = plan.get("fingerprint")
    if not isinstance(fingerprint, str) or len(fingerprint) != 64:
        raise ValueError("Control Plane render plan fingerprint is invalid")
    if plan.get("workflow_run_id") != workflow_run_id:
        raise ValueError("Control Plane render plan workflow does not match dispatch")
    if plan.get("composition_version_id") != composition.get("version_id"):
        raise ValueError("Control Plane render plan version does not match locked composition")
    return fingerprint
