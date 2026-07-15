import unittest

from worker.application.visionflow_render_dispatcher import VisionFlowRenderDispatcher, _apply_locked_timeline
from worker.application.visionflow_render_workflow import RenderedArtifact


class ControlPlane:
    def __init__(self, context):
        self.context = context
        self.calls = []

    def get_execution_context(self, workflow_run_id, *, trace_id=None):
        self.calls.append((workflow_run_id, trace_id))
        return self.context
    def get_composition(self, workflow_run_id, *, trace_id=None):
        return {"state": "locked", "tracks": [{"track_type": "video", "clips": [{"source_type": "scene", "source_ref": "scene-01", "timeline_start_ms": 0, "duration_ms": 5000}]}]}


class RenderWorkflow:
    def __init__(self):
        self.contracts = []

    def execute(self, contract):
        self.contracts.append(contract)
        return RenderedArtifact("visionflow/run-1/exports/final.mp4", "video/mp4", 10, "a" * 64)


def context(*, state="STORYBOARDED"):
    return {
        "workflow_run_id": "run-1",
        "state": state,
        "intake": {"title": "Title", "brief": "Brief", "input_payload": {"duration_seconds": 45, "aspect_ratio": "9:16"}},
        "steps": {
            "script": {"script": "A valid script that contains enough content to be rendered."},
            "storyboard": {"scenes": [{"scene_id": "scene-01", "visual_search_keywords": "city lights"}]},
        },
    }


class VisionFlowRenderDispatcherTests(unittest.TestCase):
    def test_reads_context_then_builds_and_dispatches_mysql_free_contract(self):
        gateway = ControlPlane(context())
        workflow = RenderWorkflow()

        result = VisionFlowRenderDispatcher(gateway, workflow).dispatch("run-1", trace_id="b" * 32)

        self.assertEqual("visionflow/run-1/exports/final.mp4", result.object_key)
        self.assertEqual([("run-1", "b" * 32)], gateway.calls)
        self.assertEqual("run-1", workflow.contracts[0].workflow_run_id)
        self.assertEqual("b" * 32, workflow.contracts[0].trace_id)
        self.assertFalse(hasattr(workflow.contracts[0], "job_id"))
        self.assertEqual("locked", workflow.contracts[0].composition["state"])

    def test_rejects_not_storyboarded_without_invoking_renderer(self):
        gateway = ControlPlane(context(state="SCRIPTED"))
        workflow = RenderWorkflow()

        with self.assertRaisesRegex(ValueError, "STORYBOARDED"):
            VisionFlowRenderDispatcher(gateway, workflow).dispatch("run-1", trace_id="b" * 32)

        self.assertEqual([], workflow.contracts)

    def test_rejects_missing_script_or_storyboard_before_render(self):
        bad_context = context()
        bad_context["steps"]["script"] = None
        workflow = RenderWorkflow()

        with self.assertRaisesRegex(ValueError, "scripted output"):
            VisionFlowRenderDispatcher(ControlPlane(bad_context), workflow).dispatch("run-1", trace_id="b" * 32)

        self.assertEqual([], workflow.contracts)

    def test_materializes_video_track_order_and_clip_duration(self):
        scenes = [
            {"scene_id": "a", "visual_search_keywords": "first"},
            {"scene_id": "b", "visual_search_keywords": "second"},
        ]
        composition = {"tracks": [{"track_type": "video", "clips": [
            {"source_type": "scene", "source_ref": "b", "timeline_start_ms": 0, "duration_ms": 9000},
            {"source_type": "scene", "source_ref": "a", "timeline_start_ms": 9000, "duration_ms": 6000},
        ]}]}
        result = _apply_locked_timeline(scenes, composition)
        self.assertEqual(["b", "a"], [scene["scene_id"] for scene in result])
        self.assertEqual([9.0, 6.0], [scene["duration"] for scene in result])


if __name__ == "__main__":
    unittest.main()
