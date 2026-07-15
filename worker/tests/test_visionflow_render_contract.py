import unittest

from worker.domain.visionflow_render_contract import build_visionflow_render_contract


class VisionFlowRenderContractTests(unittest.TestCase):
    def test_builds_mysql_free_short_form_contract(self):
        contract = build_visionflow_render_contract(
            "run-1", "a" * 32,
            {"title": "Short", "input_payload": {"duration_seconds": 45, "aspect_ratio": "9:16", "voice_code": "edge-nam-minh"}},
            "A script long enough to become a render input.",
            [{"visual_search_keywords": "rain portrait"}],
        )
        self.assertEqual("visionflow/run-1/render", contract.workspace_key)
        self.assertEqual(45, contract.duration_seconds)

    def test_rejects_non_vertical_format(self):
        with self.assertRaisesRegex(ValueError, "9:16"):
            build_visionflow_render_contract(
                "run-1", "a" * 32, {"input_payload": {"aspect_ratio": "16:9"}}, "script", [{"visual_search_keywords": "rain"}],
            )
