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
        return {"state": "locked", "version_id": "composition-version-1", "aspect_ratio": "9:16", "tracks": [{"track_type": "video", "name": "Visuals", "clips": [{"source_type": "scene", "source_ref": "scene-01", "timeline_start_ms": 0, "duration_ms": 5000}]}]}
    def get_composition_render_plan(self, workflow_run_id, *, trace_id=None):
        return {"workflow_run_id": workflow_run_id, "composition_version_id": "composition-version-1", "fingerprint": "c" * 64}

    def open_manual_approval(self, workflow_run_id, *, trace_id=None):
        self.calls.append(("approval", workflow_run_id, trace_id))
        return {"workflow_run_id": workflow_run_id, "state": "APPROVAL_PENDING", "changed": True}


class RenderWorkflow:
    def __init__(self):
        self.contracts = []

    def execute(self, contract):
        self.contracts.append(contract)
        return RenderedArtifact("visionflow/run-1/exports/final.mp4", "video/mp4", 10, "a" * 64)


class QualityAssurance:
    def __init__(self): self.calls = []
    def execute(self, workflow_run_id, artifact, *, trace_id=None): self.calls.append((workflow_run_id, artifact, trace_id))


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
        self.assertEqual("composition-version-1", workflow.contracts[0].render_plan.composition_version_id)
        self.assertEqual("c" * 64, workflow.contracts[0].render_plan_hash)

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

    def test_runs_technical_qa_only_after_render_artifact_exists(self):
        gateway, workflow, qa = ControlPlane(context()), RenderWorkflow(), QualityAssurance()
        VisionFlowRenderDispatcher(gateway, workflow, qa).dispatch("run-1", trace_id="b" * 32)
        self.assertEqual("visionflow/run-1/exports/final.mp4", qa.calls[0][1].object_key)
        self.assertEqual("b" * 32, qa.calls[0][2])
        self.assertEqual(("approval", "run-1", "b" * 32), gateway.calls[-1])


if __name__ == "__main__":
    unittest.main()
