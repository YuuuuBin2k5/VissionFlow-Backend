import unittest
from types import SimpleNamespace

from worker.domain.composition_render_plan import compile_composition_render_plan
from worker.services.visionflow_video_renderer import _style_plan


def contract_with_effects(*effect_keys):
    return SimpleNamespace(
        visual_preset="clean_explainer",
        render_plan=compile_composition_render_plan("run-1", {
            "state": "locked",
            "version_id": "composition-version-1",
            "aspect_ratio": "9:16",
            "tracks": [{
                "track_type": "video",
                "name": "Visuals",
                "clips": [{
                    "source_type": "scene", "source_ref": "scene-01", "timeline_start_ms": 0,
                    "duration_ms": 5000, "trim_in_ms": 0, "transform": {},
                    "effects": [{"effect_key": key} for key in effect_keys],
                    "keyframes": [{"property_key": "scale", "time_ms": 100, "value": {"value": 1.15}, "easing": "ease_out"}],
                }],
            }],
        }),
        render_plan_hash="a" * 64,
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

    def test_uses_an_empty_typed_plan_without_raw_snapshot_fallback(self):
        contract = SimpleNamespace(
            visual_preset="clean_explainer",
            render_plan=compile_composition_render_plan("run-1", {"state": "locked", "version_id": "composition-version-1", "aspect_ratio": "9:16", "tracks": []}),
            render_plan_hash="b" * 64,
        )

        plan = _style_plan(contract)

        self.assertEqual("static", plan["scene_motion"])
        self.assertEqual([], plan["composition_applied_effects"])
        self.assertEqual([], plan["composition_deferred_effects"])


if __name__ == "__main__":
    unittest.main()
