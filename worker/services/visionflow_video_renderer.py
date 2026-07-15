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
    """Translate the locked editor snapshot into supported render directives.

    The raw snapshot stays attached for audit/next renderer extensions; known
    presets are translated only where the MediaService has a real behavior.
    Unsupported presets are retained for audit, but never presented to the
    renderer as if they had already been implemented.
    """
    effects = _composition_effects(contract.composition)
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

    deferred_effects = [
        effect for effect in effects
        if effect in {"soft_glow", "motion_blur"}
    ]
    plan = {
        "visual_preset": contract.visual_preset,
        "scene_motion": scene_motion,
        "composition_snapshot": contract.composition,
        "composition_applied_effects": applied_effects,
        "composition_deferred_effects": deferred_effects,
    }
    if caption_style:
        plan["caption_style"] = caption_style
    return plan


def _composition_effects(composition: object) -> list[str]:
    """Return ordered, known effect keys from a persisted composition safely."""
    if not isinstance(composition, dict):
        return []
    tracks = composition.get("tracks")
    if not isinstance(tracks, list):
        return []

    effects: list[str] = []
    for track in tracks:
        if not isinstance(track, dict) or not isinstance(track.get("clips"), list):
            continue
        for clip in track["clips"]:
            if not isinstance(clip, dict) or not isinstance(clip.get("effects"), list):
                continue
            for effect in clip["effects"]:
                effect_key = effect.get("effect_key") if isinstance(effect, dict) else None
                if isinstance(effect_key, str):
                    effects.append(effect_key)
    return effects
