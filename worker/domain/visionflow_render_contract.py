"""MySQL-free render contract for VisionFlow short-form workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from worker.domain.composition_render_plan import CompositionRenderPlan, compile_composition_render_plan


@dataclass(frozen=True)
class VisionFlowRenderContract:
    workflow_run_id: str
    trace_id: str
    title: str
    script: str
    scenes: tuple[dict[str, Any], ...]
    duration_seconds: int
    aspect_ratio: str
    voice_code: str
    visual_preset: str
    render_plan: CompositionRenderPlan
    render_plan_hash: str
    workspace_key: str


def build_visionflow_render_contract(
    workflow_run_id: str,
    trace_id: str,
    intake: dict[str, Any],
    script: str,
    scenes: list[dict[str, Any]],
    composition: dict[str, Any],
    *,
    authoritative_render_plan_fingerprint: str,
) -> VisionFlowRenderContract:
    payload = intake.get("input_payload", {})
    if not isinstance(payload, dict):
        raise ValueError("intake input_payload must be an object")
    if not workflow_run_id.strip() or len(trace_id) != 32:
        raise ValueError("workflow_run_id and a 32-character trace_id are required")
    duration = int(payload.get("duration_seconds", 45))
    if not 15 <= duration <= 90:
        raise ValueError("VisionFlow V1 duration must be between 15 and 90 seconds")
    if str(payload.get("aspect_ratio", "9:16")) != "9:16":
        raise ValueError("VisionFlow V1 only supports 9:16 rendering")
    if not script.strip() or not scenes:
        raise ValueError("render requires a script and storyboard scenes")
    if len(authoritative_render_plan_fingerprint) != 64:
        raise ValueError("authoritative render plan fingerprint must be a SHA-256 hex digest")
    render_plan = compile_composition_render_plan(workflow_run_id, composition)
    return VisionFlowRenderContract(
        workflow_run_id=workflow_run_id,
        trace_id=trace_id,
        title=str(intake.get("title", "")).strip(),
        script=script.strip(),
        scenes=tuple(scenes),
        duration_seconds=duration,
        aspect_ratio="9:16",
        voice_code=str(payload.get("voice_code", "edge-nam-minh")),
        visual_preset=str(payload.get("visual_preset", "clean_explainer")),
        render_plan=render_plan,
        render_plan_hash=authoritative_render_plan_fingerprint,
        workspace_key=f"visionflow/{workflow_run_id}/render",
    )
