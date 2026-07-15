import unittest
from types import SimpleNamespace

from worker.services.visionflow_video_renderer import _style_plan


def contract_with_effects(*effect_keys):
    return SimpleNamespace(
        visual_preset="clean_explainer",
        composition={
            "state": "locked",
            "tracks": [{
                "track_type": "video",
                "clips": [{"timeline_start_ms": 0, "effects": [{"effect_key": key} for key in effect_keys], "keyframes": [{"property_key": "scale", "time_ms": 100, "value": {"value": 1.15}, "easing": "ease_out"}]}, {}],
            }],
        },
    )


class VisionFlowVideoRendererStylePlanTests(unittest.TestCase):
    def test_maps_only_effects_with_a_real_media_service_directive(self):
        plan = _style_plan(contract_with_effects(
            "cinematic_push", "impact_shake", "caption_pop", "soft_glow", "motion_blur",
        ))

        self.assertEqual("beat_push", plan["scene_motion"])
        self.assertEqual("sticker_pop", plan["caption_style"])
        self.assertEqual(["impact_shake", "caption_pop", "soft_glow", "motion_blur"], plan["composition_applied_effects"])
        self.assertEqual(["soft_glow", "motion_blur"], plan["composition_frame_effects"])
        self.assertEqual([], plan["composition_deferred_effects"])
        self.assertEqual([{"time_ms": 100, "value": 1.15, "easing": "ease_out"}], plan["composition_keyframes"])

    def test_maps_cinematic_push_when_no_stronger_motion_preset_exists(self):
        plan = _style_plan(contract_with_effects("cinematic_push"))

        self.assertEqual("slow_zoom", plan["scene_motion"])
        self.assertEqual(["cinematic_push"], plan["composition_applied_effects"])
        self.assertNotIn("caption_style", plan)

    def test_ignores_malformed_persisted_tracks_without_failing_render_setup(self):
        contract = SimpleNamespace(
            visual_preset="clean_explainer",
            composition={"state": "locked", "tracks": [None, {"clips": "not-a-list"}]},
        )

        plan = _style_plan(contract)

        self.assertEqual("static", plan["scene_motion"])
        self.assertEqual([], plan["composition_applied_effects"])
        self.assertEqual([], plan["composition_deferred_effects"])


if __name__ == "__main__":
    unittest.main()
