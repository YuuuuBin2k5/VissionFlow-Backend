import unittest
from pathlib import Path

from worker.domain.composition_render_plan import compile_composition_render_plan
from worker.services.composition_caption_compositor import build_ass_script, build_ffmpeg_command, caption_cues


def _plan():
    return compile_composition_render_plan("run-1", {
        "state": "locked", "version_id": "composition-version-1", "aspect_ratio": "9:16",
        "tracks": [{
            "track_type": "caption", "name": "Captions", "muted": False,
            "clips": [{
                "source_type": "text", "source_ref": "Dòng một\nDòng hai", "timeline_start_ms": 1250,
                "duration_ms": 2500, "trim_in_ms": 0, "transform": {},
                "effects": [{"effect_key": "caption_pop"}], "keyframes": [],
            }],
        }],
    })


class CompositionCaptionCompositorTests(unittest.TestCase):
    def test_compiles_timed_text_cues_from_locked_caption_track(self):
        cues = caption_cues(_plan())
        self.assertEqual(1, len(cues))
        self.assertEqual((1250, 3750), (cues[0].start_ms, cues[0].end_ms))
        self.assertTrue(cues[0].pop)

    def test_ass_escapes_operator_text_and_encodes_pop_fade(self):
        script = build_ass_script(caption_cues(_plan()))
        self.assertIn("0:00:01.25", script)
        self.assertIn(r"{\fad(80,120)}Dòng một\NDòng hai", script)

    def test_ffmpeg_command_is_argv_safe_and_uses_ass_filter(self):
        command = build_ffmpeg_command("ffmpeg", Path("input.mp4"), Path("captions.ass"), Path("output.mp4"))
        self.assertEqual("ffmpeg", command[0])
        self.assertIn("ass=filename=", command[command.index("-vf") + 1])
        self.assertNotIn("shell", " ".join(command).lower())


if __name__ == "__main__":
    unittest.main()
