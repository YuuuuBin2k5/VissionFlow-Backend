"""AssetPreparer adapter: stock provider -> temporary file -> object storage."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from worker.application.visionflow_render_workflow import PreparedAssets
from worker.domain.visionflow_render_contract import VisionFlowRenderContract


class StockAssetDownloader(Protocol):
    def search_and_download_video(self, keywords: str, scene_id: int) -> str: ...


class ObjectStorage(Protocol):
    def upload_asset(self, workflow_run_id: str, scene_id: int, source_path: str) -> dict[str, object]: ...


class VisionFlowAssetPreparer:
    def __init__(self, downloader: StockAssetDownloader, storage: ObjectStorage) -> None:
        self._downloader = downloader
        self._storage = storage

    def prepare(self, contract: VisionFlowRenderContract) -> PreparedAssets:
        keys: list[str] = []
        for ordinal, scene in enumerate(contract.scenes, start=1):
            keywords = str(scene.get("visual_search_keywords", "")).strip()
            if not keywords:
                raise ValueError(f"scene {ordinal} has no visual_search_keywords")
            temporary_path = self._downloader.search_and_download_video(keywords, ordinal)
            try:
                uploaded = self._storage.upload_asset(contract.workflow_run_id, ordinal, temporary_path)
                object_key = uploaded.get("object_key")
                if not isinstance(object_key, str) or not object_key:
                    raise RuntimeError("object storage did not return an object_key")
                keys.append(object_key)
            finally:
                _remove_temporary_asset(temporary_path)
        return PreparedAssets(asset_keys=tuple(keys))


def _remove_temporary_asset(path_value: str) -> None:
    path = Path(path_value)
    try:
        path.unlink(missing_ok=True)
        path.with_suffix(path.suffix + ".metadata.json").unlink(missing_ok=True)
    except OSError:
        # Cleanup must not hide an already successful storage upload. The worker
        # image uses ephemeral disk and a periodic workspace cleanup is allowed.
        pass
