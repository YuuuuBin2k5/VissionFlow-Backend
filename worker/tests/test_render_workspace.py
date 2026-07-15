import tempfile
import unittest
from pathlib import Path
from worker.domain.render_workspace import RenderWorkspace

class RenderWorkspaceTests(unittest.TestCase):
    def test_isolated_paths_are_created(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = RenderWorkspace(Path(directory), "run-1").create()
            self.assertTrue(workspace.assets_path.is_dir())
            self.assertEqual(Path(directory) / "visionflow" / "run-1" / "export.mp4", workspace.output_path)
