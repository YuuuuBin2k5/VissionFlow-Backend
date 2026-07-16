import copy
import unittest

from worker.domain.composition_render_plan import (
    RenderPlanValidationError,
    compile_composition_render_plan,
)


def locked_composition():
    return {
        "state": "locked",
        "version_id": "composition-version-1",
        "aspect_ratio": "9:16",
        "tracks": [{
            "track_type": "video",
            "name": "Visuals",
            "muted": False,
            "clips": [{
                "source_type": "scene",
                "source_ref": "scene-01",
                "timeline_start_ms": 0,
                "duration_ms": 5000,
                "trim_in_ms": 0,
                "transform": {"scale": 1.0, "x": 0},
                "effects": [{"effect_key": "cinematic_push", "config": {}}],
                "keyframes": [{"property_key": "scale", "time_ms": 0, "value": {"value": 1.0}, "easing": "ease_out"}],
            }],
        }],
    }


class CompositionRenderPlanTests(unittest.TestCase):
    def test_same_locked_snapshot_has_stable_canonical_hash(self):
        first = locked_composition()
        second = copy.deepcopy(first)
        second["tracks"][0]["clips"][0]["transform"] = {"x": 0, "scale": 1.0}

        left = compile_composition_render_plan("run-1", first)
        right = compile_composition_render_plan("run-1", second)

        self.assertEqual(left.plan_hash, right.plan_hash)
        self.assertEqual(left.canonical_payload(), right.canonical_payload())
        self.assertEqual(("cinematic_push",), left.effect_keys)
        self.assertEqual(1.0, left.scale_keyframes[0].value)

    def test_rejects_unknown_effect_before_renderer_receives_it(self):
        composition = locked_composition()
        composition["tracks"][0]["clips"][0]["effects"] = [{"effect_key": "neon_mist", "config": {}}]

        with self.assertRaisesRegex(RenderPlanValidationError, "not supported"):
            compile_composition_render_plan("run-1", composition)

    def test_rejects_draft_or_invalid_keyframe(self):
        draft = locked_composition()
        draft["state"] = "draft"
        with self.assertRaisesRegex(RenderPlanValidationError, "locked"):
            compile_composition_render_plan("run-1", draft)

        invalid = locked_composition()
        invalid["tracks"][0]["clips"][0]["keyframes"][0]["value"] = {"value": 4.0}
        with self.assertRaisesRegex(RenderPlanValidationError, "between 0.5 and 2.0"):
            compile_composition_render_plan("run-1", invalid)


if __name__ == "__main__":
    unittest.main()
