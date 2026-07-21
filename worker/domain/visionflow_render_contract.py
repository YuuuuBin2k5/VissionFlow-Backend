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
    voice_rate: float
    enable_sfx: bool
    logo_url: str
    logo_handle: str
    logo_position: str
    logo_opacity: float
    show_title_banner: bool
    title_banner_style: str
    caption_preset: str
    caption_position: str
    caption_color: str
    enable_karaoke: bool
    enable_auto_emoji: bool
    visual_preset: str
    color_grading: str
    enable_vignette: bool
    enable_progress_bar: bool
    enable_follow_cta: bool
    enable_outro_card: bool
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
        voice_code=str(payload.get("voice") or payload.get("voice_code") or "edge-nam-minh"),
        voice_rate=float(payload.get("voice_rate") or 1.12),
        enable_sfx=bool(payload.get("enable_sfx", True)),
        logo_url=str(payload.get("logo_url") or ""),
        logo_handle=str(payload.get("logo_handle") or "@VisionFlowAI"),
        logo_position=str(payload.get("logo_position") or "top_left"),
        logo_opacity=float(payload.get("logo_opacity") or 0.85),
        show_title_banner=bool(payload.get("show_title_banner", True)),
        title_banner_style=str(payload.get("title_banner_style") or "neon"),
        caption_preset=str(payload.get("caption_preset") or "hormozi"),
        caption_position=str(payload.get("caption_position") or "bottom"),
        caption_color=str(payload.get("caption_color") or "#FFFF00"),
        enable_karaoke=bool(payload.get("enable_karaoke", True)),
        enable_auto_emoji=bool(payload.get("enable_auto_emoji", True)),
        visual_preset=str(payload.get("visual_preset") or "clean_explainer"),
        color_grading=str(payload.get("color_grading") or "cyber_teal"),
        enable_vignette=bool(payload.get("enable_vignette", True)),
        enable_progress_bar=bool(payload.get("enable_progress_bar", True)),
        enable_follow_cta=bool(payload.get("enable_follow_cta", True)),
        enable_outro_card=bool(payload.get("enable_outro_card", True)),
        render_plan=render_plan,
        render_plan_hash=authoritative_render_plan_fingerprint,
        workspace_key=f"visionflow/{workflow_run_id}/render",
    )
