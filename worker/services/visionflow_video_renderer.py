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
            visual_style_plan={"visual_preset": contract.visual_preset},
            full_voice_script=contract.script,
        )
        uploaded = self._storage.upload_export(contract.workflow_run_id, output_path)
        return RenderedArtifact(**uploaded)
