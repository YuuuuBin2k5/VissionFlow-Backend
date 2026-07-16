from __future__ import annotations

import sys
import unittest
from pathlib import Path


SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.domain.render_plan import RenderPlanCompilationError, compile_render_plan


def _snapshot() -> dict[str, object]:
    return {
        "workflow_run_id": "a4b9e02b-2a8a-4d34-a337-a286b7190001",
        "version_id": "f8bbbd6e-a4d3-4bfd-a755-8ea901b90001",
        "revision": 3,
        "state": "locked",
        "aspect_ratio": "9:16",
        "canvas_config": {"width": 1080, "height": 1920, "background": "#000000"},
        "tracks": [
            {
                "track_type": "video",
                "name": "Main",
                "clips": [
                    {
                        "source_type": "asset",
                        "source_ref": "asset://hero.mp4",
                        "timeline_start_ms": 0,
                        "duration_ms": 5_000,
                        "effects": [{"effect_key": "cinematic_push", "config": {}}],
                        "keyframes": [{"property_key": "scale", "time_ms": 0, "value": {"value": 1.0}}],
                    }
                ],
            },
            {
                "track_type": "audio",
                "name": "Voice",
                "muted": True,
                "clips": [
                    {
                        "source_type": "asset",
                        "source_ref": "asset://voice.mp3",
                        "timeline_start_ms": 1_000,
                        "duration_ms": 6_000,
                        "effects": [],
                        "keyframes": [],
                    }
                ],
            },
        ],
    }


class RenderPlanTests(unittest.TestCase):
    def test_compiles_a_locked_snapshot_deterministically(self) -> None:
        first = compile_render_plan(_snapshot())
        second = compile_render_plan(_snapshot())

        self.assertEqual(7_000, first.duration_ms)
        self.assertEqual(1080, first.canvas["width"])
        self.assertEqual("asset://hero.mp4", first.tracks[0].clips[0].source_ref)
        self.assertTrue(first.tracks[1].muted)
        self.assertEqual(first.fingerprint, second.fingerprint)

    def test_rejects_an_unlocked_snapshot(self) -> None:
        snapshot = _snapshot()
        snapshot["state"] = "draft"

        with self.assertRaisesRegex(RenderPlanCompilationError, "locked"):
            compile_render_plan(snapshot)

    def test_rejects_a_non_v1_canvas(self) -> None:
        snapshot = _snapshot()
        snapshot["canvas_config"] = {"width": 1920, "height": 1080}

        with self.assertRaisesRegex(RenderPlanCompilationError, "1080x1920"):
            compile_render_plan(snapshot)


if __name__ == "__main__":
    unittest.main()
