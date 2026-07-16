"""Real FFmpeg integration test for the VisionFlow post-render compositor chain."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from worker.domain.composition_render_plan import compile_composition_render_plan
from worker.services.composition_caption_compositor import FfmpegCaptionCompositor
from worker.services.composition_overlay_compositor import FfmpegOverlayCompositor, ResolvedOverlayLayer


@unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg is required for compositor integration")
class CompositionCompositorIntegrationTests(unittest.TestCase):
    def test_composites_real_overlay_then_caption_into_mp4(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            base = workspace / "base.mp4"
            image = workspace / "overlay.png"
            subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=1080x1920:d=1", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(base)], capture_output=True, check=True)
            subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=red:s=120x120", "-frames:v", "1", "-update", "1", str(image)], capture_output=True, check=True)
            overlaid = FfmpegOverlayCompositor().apply(str(base), (ResolvedOverlayLayer(image, 0, 900, {"x": 0, "y": 0, "scale": 0.4, "opacity": 1}),), workspace)
            plan = compile_composition_render_plan("run-1", {
                "state": "locked", "version_id": "composition-version-1", "aspect_ratio": "9:16",
                "tracks": [{"track_type": "caption", "name": "Caption", "muted": False, "clips": [{
                    "source_type": "text", "source_ref": "VisionFlow", "timeline_start_ms": 0, "duration_ms": 800,
                    "trim_in_ms": 0, "transform": {}, "effects": [{"effect_key": "caption_pop"}], "keyframes": [],
                }]}],
            })
            final_path = Path(FfmpegCaptionCompositor().apply(overlaid, plan, workspace))
            self.assertTrue(final_path.is_file())
            self.assertGreater(final_path.stat().st_size, 1024)


if __name__ == "__main__":
    unittest.main()
