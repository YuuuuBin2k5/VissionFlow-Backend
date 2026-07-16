"""MySQL-free VideoRenderer adapter for the VisionFlow render workflow."""
from __future__ import annotations
from worker.application.visionflow_render_workflow import PreparedAssets, RenderedArtifact
from worker.domain.render_workspace import RenderWorkspace

class VisionFlowVideoRenderer:
    def __init__(self, storage, materializer, tts, media_service, workspace_root) -> None:
        self._storage, self._materializer, self._tts = storage, materializer, tts
        self._media_service, self._workspace_root = media_service, workspace_root

    def render(self, contract, assets: PreparedAssets) -> RenderedArtifact:
        workspace = RenderWorkspace(self._workspace_root, contract.workflow_run_id).create()
        background_paths = self._materializer.download(assets, workspace)
        speech = self._tts.synthesize(contract.script, contract.voice_code, workspace)
        output_path = self._media_service.render_final_video(
            list(contract.scenes), speech.word_timestamps, speech.audio_path, background_paths,
            workspace_path=str(workspace.path),
            visual_style_plan=_style_plan(contract),
            full_voice_script=contract.script,
        )
        uploaded = self._storage.upload_export(contract.workflow_run_id, output_path)
        return RenderedArtifact(**uploaded)


def _style_plan(contract) -> dict:
    """Translate the typed render plan into supported media directives."""
    effects = list(contract.render_plan.effect_keys)
    applied_effects: list[str] = []

    # MediaService supports these motion names through _apply_scene_motion.
    # A beat push is the closest currently implemented treatment for the
    # editor's impact preset; it is intentionally preferred over slow zoom.
    if "impact_shake" in effects:
        scene_motion = "beat_push"
        applied_effects.append("impact_shake")
    elif "cinematic_push" in effects:
        scene_motion = "slow_zoom"
        applied_effects.append("cinematic_push")
    else:
        scene_motion = "static"

    # SubtitleRenderer contains a real sticker_pop style.  This is a caption
    # treatment, not a generic clip transform, so only map caption_pop here.
    caption_style = "sticker_pop" if "caption_pop" in effects else None
    if caption_style:
        applied_effects.append("caption_pop")

    frame_effects = [effect for effect in effects if effect in {"soft_glow", "motion_blur"}]
    applied_effects.extend(frame_effects)
    keyframes = [
        {"time_ms": keyframe.time_ms, "value": keyframe.value, "easing": keyframe.easing}
        for keyframe in contract.render_plan.scale_keyframes
    ]
    plan = {
        "visual_preset": contract.visual_preset,
        "scene_motion": scene_motion,
        "render_plan_hash": contract.render_plan_hash,
        "composition_applied_effects": applied_effects,
        "composition_frame_effects": frame_effects,
        "composition_keyframes": keyframes,
        "composition_deferred_effects": [],
    }
    if caption_style:
        plan["caption_style"] = caption_style
    return plan
