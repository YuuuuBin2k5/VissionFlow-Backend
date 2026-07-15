"""Materialize immutable object keys into a per-run render workspace."""
from __future__ import annotations
from pathlib import Path
from worker.application.visionflow_render_workflow import PreparedAssets
from worker.domain.render_workspace import RenderWorkspace

class VisionFlowRenderAssetMaterializer:
    def __init__(self, storage) -> None: self._storage = storage
    def download(self, assets: PreparedAssets, workspace: RenderWorkspace) -> list[str]:
        workspace.create()
        paths = []
        for index, key in enumerate(assets.asset_keys, start=1):
            paths.append(self._storage.download_to(key, str(workspace.assets_path / f"scene-{index:02d}.mp4")))
        return paths
