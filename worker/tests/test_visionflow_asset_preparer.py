import tempfile
import unittest
from pathlib import Path

from worker.domain.visionflow_render_contract import build_visionflow_render_contract
from worker.services.visionflow_asset_preparer import VisionFlowAssetPreparer


class Downloader:
    def __init__(self, path): self.path = path; self.calls = []
    def search_and_download_video(self, keywords, scene_id): self.calls.append((keywords, scene_id)); return str(self.path)


class Storage:
    def __init__(self): self.calls = []
    def upload_asset(self, workflow_run_id, scene_id, source_path):
        self.calls.append((workflow_run_id, scene_id, source_path))
        return {"object_key": f"visionflow/{workflow_run_id}/assets/scene-{scene_id:02d}.mp4"}


class AssetPreparerTests(unittest.TestCase):
    def test_uploads_each_storyboard_scene_and_removes_temp_file(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory) / "asset.mp4"
            temporary.write_bytes(b"video")
            contract = build_visionflow_render_contract(
                "run-1", "a" * 32, {"input_payload": {}}, "a renderable script",
                [{"visual_search_keywords": "rain portrait"}],
                {"state": "locked", "tracks": []},
            )
            storage = Storage()
            prepared = VisionFlowAssetPreparer(Downloader(temporary), storage).prepare(contract)
            self.assertEqual(("visionflow/run-1/assets/scene-01.mp4",), prepared.asset_keys)
            self.assertFalse(temporary.exists())
