import sys
import unittest
from pathlib import Path


SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.domain.composition import CompositionValidationError, validate_composition_for_v1


def _tracks() -> list[dict[str, object]]:
    return [{
        "track_type": "video",
        "name": "Main",
        "clips": [{
            "source_type": "asset",
            "source_ref": "asset.mp4",
            "timeline_start_ms": 0,
            "duration_ms": 5_000,
            "effects": [{"effect_key": "cinematic_push", "config": {}}],
            "keyframes": [{"property_key": "scale", "time_ms": 0, "value": {"value": 1.0}}],
        }],
    }]


class CompositionValidationTests(unittest.TestCase):
    def test_accepts_renderable_short_form_composition(self) -> None:
        validate_composition_for_v1(aspect_ratio="9:16", tracks=_tracks())

    def test_rejects_non_renderable_effect_configuration(self) -> None:
        tracks = _tracks()
        tracks[0]["clips"][0]["effects"] = [{"effect_key": "cinematic_push", "config": {"speed": 2}}]
        with self.assertRaisesRegex(CompositionValidationError, "does not accept config"):
            validate_composition_for_v1(aspect_ratio="9:16", tracks=tracks)

    def test_rejects_keyframe_outside_clip_bounds(self) -> None:
        tracks = _tracks()
        tracks[0]["clips"][0]["keyframes"][0]["time_ms"] = 5_001
        with self.assertRaisesRegex(CompositionValidationError, "inside its clip"):
            validate_composition_for_v1(aspect_ratio="9:16", tracks=tracks)


if __name__ == "__main__":
    unittest.main()
