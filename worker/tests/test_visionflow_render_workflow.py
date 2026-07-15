import unittest
from dataclasses import fields

from worker.application.visionflow_render_workflow import (
    PreparedAssets,
    RenderedArtifact,
    VisionFlowRenderWorkflow,
)
from worker.domain.visionflow_render_contract import build_visionflow_render_contract


class RecordingGateway:
    def __init__(self):
        self.transitions = []

    def advance_workflow(self, workflow_run_id, expected_state, target_state, output_payload, *, trace_id=None):
        self.transitions.append((workflow_run_id, expected_state, target_state, output_payload, trace_id))
        return {"state": target_state}


class RecordingAssetPreparer:
    def __init__(self):
        self.contracts = []

    def prepare(self, contract):
        self.contracts.append(contract)
        return PreparedAssets(asset_keys=("visionflow/run-1/assets/scene-01.mp4",))


class RecordingRenderer:
    def __init__(self):
        self.calls = []

    def render(self, contract, assets):
        self.calls.append((contract, assets))
        return RenderedArtifact(
            object_key="visionflow/run-1/exports/final.mp4",
            content_type="video/mp4",
            byte_size=123,
            checksum_sha256="b" * 64,
        )


def render_contract():
    return build_visionflow_render_contract(
        "run-1",
        "a" * 32,
        {"title": "A vertical short", "input_payload": {"duration_seconds": 45, "aspect_ratio": "9:16"}},
        "A script suitable for rendering.",
        [{"scene_id": "scene-01", "visual_search_keywords": "city lights"}],
    )


class VisionFlowRenderWorkflowTests(unittest.TestCase):
    def test_executes_only_the_valid_state_order_and_returns_uploaded_artifact(self):
        gateway = RecordingGateway()
        assets = RecordingAssetPreparer()
        renderer = RecordingRenderer()

        artifact = VisionFlowRenderWorkflow(gateway, assets, renderer).execute(render_contract())

        self.assertEqual(
            [
                ("STORYBOARDED", "ASSETS_READY"),
                ("ASSETS_READY", "RENDERING"),
                ("RENDERING", "QA_PENDING"),
            ],
            [(item[1], item[2]) for item in gateway.transitions],
        )
        self.assertEqual("visionflow/run-1/exports/final.mp4", artifact.object_key)
        self.assertEqual(["visionflow/run-1/assets/scene-01.mp4"], gateway.transitions[0][3]["asset_keys"])
        self.assertEqual("visionflow/run-1/render", gateway.transitions[1][3]["workspace_key"])
        self.assertEqual("a" * 32, gateway.transitions[2][4])
        self.assertEqual(1, len(assets.contracts))
        self.assertEqual(1, len(renderer.calls))

    def test_contract_and_workflow_do_not_expose_legacy_job_identifier(self):
        contract = render_contract()

        self.assertNotIn("job_id", {field.name for field in fields(type(contract))})
        self.assertFalse(hasattr(contract, "job_id"))
        self.assertNotIn("job_id", VisionFlowRenderWorkflow.execute.__annotations__)

    def test_asset_failure_prevents_state_advancement_and_rendering(self):
        class FailingAssetPreparer:
            def prepare(self, contract):
                raise RuntimeError("asset provider unavailable")

        gateway = RecordingGateway()
        renderer = RecordingRenderer()

        with self.assertRaisesRegex(RuntimeError, "asset provider unavailable"):
            VisionFlowRenderWorkflow(gateway, FailingAssetPreparer(), renderer).execute(render_contract())

        self.assertEqual([], gateway.transitions)
        self.assertEqual([], renderer.calls)


if __name__ == "__main__":
    unittest.main()
