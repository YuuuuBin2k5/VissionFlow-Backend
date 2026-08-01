"""MySQL-free VideoRenderer adapter for the VisionFlow render workflow."""
from __future__ import annotations
from pathlib import Path
from typing import Any

from worker.application.visionflow_render_workflow import PreparedAssets, RenderedArtifact
from worker.domain.composition_render_plan import CompositionRenderPlan
from worker.domain.render_workspace import RenderWorkspace
from worker.services.composition_caption_compositor import FfmpegCaptionCompositor
from worker.services.composition_overlay_compositor import FfmpegOverlayCompositor, OverlayAssetMaterializer

class VisionFlowVideoRenderer:
    def __init__(self, storage, materializer, tts, media_service, workspace_root, caption_compositor=None, overlay_materializer=None, overlay_compositor=None) -> None:
        self._storage, self._materializer, self._tts = storage, materializer, tts
        self._media_service, self._workspace_root = media_service, Path(workspace_root)
        self._caption_compositor = caption_compositor or FfmpegCaptionCompositor()
        self._overlay_materializer = overlay_materializer or OverlayAssetMaterializer(storage)
        self._overlay_compositor = overlay_compositor or FfmpegOverlayCompositor()

    def render(self, contract, assets: PreparedAssets) -> RenderedArtifact:
        workspace = RenderWorkspace(self._workspace_root, contract.workflow_run_id).create()
        background_paths = self._materializer.download(assets, workspace)
        try:
            speech = self._tts.synthesize(contract.script, contract.voice_code, workspace, voice_rate=getattr(contract, "voice_rate", 1.12))
        except TypeError:
            speech = self._tts.synthesize(contract.script, contract.voice_code, workspace)
        scene_layout = build_renderable_scene_layout(contract.scenes, contract.render_plan)
        output_path = self._media_service.render_final_video(
            scene_layout, speech.word_timestamps, speech.audio_path, background_paths,
            workspace_path=str(workspace.path),
            visual_style_plan=_style_plan(contract),
            full_voice_script=contract.script,
        )
        overlays = self._overlay_materializer.download(contract.render_plan, workspace.path)
        output_path = self._overlay_compositor.apply(output_path, overlays, workspace.path)
        try:
            output_path = self._caption_compositor.apply(output_path, contract.render_plan, workspace.path, caption_preset=getattr(contract, "caption_preset", "hormozi"))
        except TypeError:
            output_path = self._caption_compositor.apply(output_path, contract.render_plan, workspace.path)
        uploaded = self._storage.upload_export(contract.workflow_run_id, output_path)
        return RenderedArtifact(
            object_key=str(uploaded["object_key"]),
            content_type=str(uploaded["content_type"]),
            byte_size=int(uploaded["byte_size"]),
            checksum_sha256=str(uploaded["checksum_sha256"]),
        )


def build_renderable_scene_layout(
    scenes: tuple[dict[str, Any], ...],
    render_plan: CompositionRenderPlan,
) -> list[dict[str, Any]]:
    """Attach immutable V1 timeline directives to their matching storyboard scene.

    MediaService already applies ``composition_effects`` and
    ``composition_transform`` as real MoviePy frame transforms.  The mapping is
    deliberately by stable scene ID, never by a best-effort positional guess:
    applying an operator effect to a different scene would be worse than
    applying none.  Non-video tracks are consumed by their dedicated render
    stages and must not silently alter the background-video layer here.
    """
    video_clips_by_scene: dict[str, list[Any]] = {}
    for track in render_plan.tracks:
        if track.track_type != "video" or track.muted:
            continue
        for clip in track.clips:
            if clip.source_type == "scene":
                video_clips_by_scene.setdefault(clip.source_ref, []).append(clip)

    rendered_scenes: list[dict[str, Any]] = []
    for scene in scenes:
        output = dict(scene)
        scene_id = str(scene.get("scene_id") or scene.get("id") or "").strip()
        clips = video_clips_by_scene.get(scene_id, [])
        if clips:
            # V1 permits one rendered visual treatment per storyboard scene.
            # If an editor stores more than one clip for a scene, earliest
            # timeline position wins deterministically until multilayer video
            # compositing lands in a later renderer slice.
            clip = min(clips, key=lambda item: (item.timeline_start_ms, item.duration_ms, item.source_ref))
            output["composition_effects"] = [{"effect_key": effect.key} for effect in clip.effects]
            output["composition_transform"] = dict(clip.transform)
            output["composition_keyframes"] = [
                {"time_ms": keyframe.time_ms, "value": keyframe.value, "easing": keyframe.easing}
                for keyframe in clip.keyframes
            ]
        rendered_scenes.append(output)
    return rendered_scenes


def _style_plan(contract) -> dict:
    """Translate the typed render plan into supported media directives."""
    effects = list(contract.render_plan.effect_keys)
    video_effects = [
        effect.key
        for track in contract.render_plan.tracks
        if track.track_type == "video" and not track.muted
        for clip in track.clips
        for effect in clip.effects
    ]
    caption_effects = [
        effect.key
        for track in contract.render_plan.tracks
        if track.track_type in {"caption", "video"} and not track.muted
        for clip in track.clips
        for effect in clip.effects
    ]
    applied_effects: list[str] = []

    # Check if composition contains active operator-created caption clips
    has_composition_caption_clips = any(
        track.track_type == "caption" and not track.muted and any(c.source_type == "text" and c.source_ref.strip() for c in track.clips)
        for track in contract.render_plan.tracks
    )

    if "impact_shake" in video_effects:
        scene_motion = "beat_push"
        applied_effects.append("impact_shake")
    elif "cinematic_push" in video_effects:
        scene_motion = "slow_zoom"
        applied_effects.append("cinematic_push")
    else:
        scene_motion = "static"

    caption_style = "sticker_pop" if "caption_pop" in caption_effects else None
    if caption_style:
        applied_effects.append("caption_pop")

    frame_effects = [effect for effect in video_effects if effect in {"soft_glow", "motion_blur"}]
    applied_effects.extend(frame_effects)
    keyframes = [
        {"time_ms": keyframe.time_ms, "value": keyframe.value, "easing": keyframe.easing}
        for track in contract.render_plan.tracks
        if track.track_type == "video" and not track.muted
        for clip in track.clips
        for keyframe in clip.keyframes
        if keyframe.property_key == "scale"
    ]
    plan = {
        "visual_preset": getattr(contract, "visual_preset", "warm_cinematic"),
        "scene_motion": scene_motion,
        "render_plan_hash": contract.render_plan_hash,
        "composition_applied_effects": applied_effects,
        "composition_frame_effects": frame_effects,
        "composition_keyframes": keyframes,
        "composition_deferred_effects": [effect for effect in effects if effect not in applied_effects],
        # Visual Title Banner & Watermark Logo directives
        "hook_text": getattr(contract, "title", None) if getattr(contract, "show_title_banner", True) else None,
        "show_title_banner": getattr(contract, "show_title_banner", True),
        "title_banner_style": getattr(contract, "title_banner_style", "neon"),
        "logo_handle": getattr(contract, "logo_handle", "@GocChiemNghiemYuuBin"),
        "logo_position": getattr(contract, "logo_position", "top_left"),
        "logo_opacity": getattr(contract, "logo_opacity", 0.85),
        "show_logo": True,
        # Captions & Subtitles
        "caption_preset": getattr(contract, "caption_preset", "hormozi"),
        "caption_style": getattr(contract, "caption_preset", "hormozi"),
        "subtitle_style": getattr(contract, "caption_preset", "hormozi"),
        "caption_position": getattr(contract, "caption_position", "bottom"),
        "caption_color": getattr(contract, "caption_color", "#FFFF00"),
        "enable_karaoke": getattr(contract, "enable_karaoke", True),
        "enable_auto_emoji": getattr(contract, "enable_auto_emoji", True),
        "render_word_subtitles": getattr(contract, "enable_karaoke", True),
        # Visual & FX
        "color_grading": getattr(contract, "color_grading", "cyber_teal"),
        "enable_vignette": getattr(contract, "enable_vignette", True),
        "enable_sfx": getattr(contract, "enable_sfx", True),
        # Overlays & CTA
        "enable_progress_bar": getattr(contract, "enable_progress_bar", True),
        "enable_follow_cta": getattr(contract, "enable_follow_cta", True),
        "enable_outro_card": getattr(contract, "enable_outro_card", True),
        "cta_text": "Đăng ký / Follow ngay 🔔" if getattr(contract, "enable_follow_cta", True) else None,
    }
    if caption_style:
        plan["caption_style"] = caption_style
    return plan
