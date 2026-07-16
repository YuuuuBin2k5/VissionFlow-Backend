import unittest
import tempfile
from types import SimpleNamespace

from worker.domain.composition_render_plan import compile_composition_render_plan
from worker.domain.visionflow_render_contract import build_visionflow_render_contract
from worker.services.visionflow_video_renderer import _style_plan, build_renderable_scene_layout
from worker.services.visionflow_video_renderer import VisionFlowVideoRenderer


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
        self.assertEqual(["cinematic_push"], plan["composition_deferred_effects"])
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

    def test_attaches_effects_transform_and_keyframes_to_matching_scene_only(self):
        contract = contract_with_effects("cinematic_push", "soft_glow")
        plan = contract.render_plan
        # The renderer must use a stable scene identity, not array position.
        layout = build_renderable_scene_layout((
            {"scene_id": "scene-01", "duration": 5},
            {"scene_id": "scene-02", "duration": 5},
        ), plan)

        self.assertEqual([{"effect_key": "cinematic_push"}, {"effect_key": "soft_glow"}], layout[0]["composition_effects"])
        self.assertEqual({}, layout[0]["composition_transform"])
        self.assertEqual(1.15, layout[0]["composition_keyframes"][0]["value"])
        self.assertNotIn("composition_effects", layout[1])

    def test_does_not_claim_overlay_effects_as_rendered_background_effects(self):
        contract = SimpleNamespace(
            visual_preset="clean_explainer",
            render_plan=compile_composition_render_plan("run-1", {
                "state": "locked", "version_id": "composition-version-1", "aspect_ratio": "9:16",
                "tracks": [{
                    "track_type": "overlay", "name": "Overlay", "clips": [{
                        "source_type": "asset", "source_ref": "overlay.png", "timeline_start_ms": 0,
                        "duration_ms": 5000, "trim_in_ms": 0, "transform": {},
                        "effects": [{"effect_key": "soft_glow"}], "keyframes": [],
                    }],
                }],
            }),
            render_plan_hash="c" * 64,
        )

        plan = _style_plan(contract)

        self.assertEqual([], plan["composition_applied_effects"])
        self.assertEqual(["soft_glow"], plan["composition_deferred_effects"])

    def test_post_processes_mp4_with_caption_compositor_before_upload(self):
        class Materializer:
            def download(self, assets, workspace): return ["scene.mp4"]
        class Tts:
            def synthesize(self, script, voice, workspace): return SimpleNamespace(word_timestamps=[], audio_path="voice.mp3")
        class Media:
            def render_final_video(self, *args, **kwargs): return "base.mp4"
        class Captions:
            def __init__(self): self.calls = []
            def apply(self, source_path, render_plan, workspace):
                self.calls.append((source_path, render_plan, workspace)); return "captioned.mp4"
        class Storage:
            def __init__(self): self.paths = []
            def upload_export(self, run_id, path):
                self.paths.append((run_id, path))
                return {"object_key": "export.mp4", "content_type": "video/mp4", "byte_size": 1, "checksum_sha256": "a" * 64}

        contract = build_visionflow_render_contract(
            "run-1", "a" * 32, {"input_payload": {"duration_seconds": 15, "aspect_ratio": "9:16"}},
            "A script suitable for a caption compositor integration test.",
            [{"scene_id": "scene-01", "duration": 5, "visual_search_keywords": "city"}],
            {"state": "locked", "version_id": "composition-version-1", "aspect_ratio": "9:16", "tracks": []},
        )
        storage, captions = Storage(), Captions()
        with tempfile.TemporaryDirectory() as workspace_root:
            renderer = VisionFlowVideoRenderer(storage, Materializer(), Tts(), Media(), workspace_root, caption_compositor=captions)
            renderer.render(contract, SimpleNamespace(asset_keys=("scene.mp4",)))

        self.assertEqual([("run-1", "captioned.mp4")], storage.paths)
        self.assertEqual("base.mp4", captions.calls[0][0])


if __name__ == "__main__":
    unittest.main()
