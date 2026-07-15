import unittest

from worker.application.visionflow_short_form_intelligence import VisionFlowShortFormIntelligence


class Gateway:
    def __init__(self): self.calls = []
    def advance_workflow(self, *args, **kwargs): self.calls.append((args, kwargs)); return {"changed": True}


class Generator:
    def generate(self, intake):
        return {"full_voice_script": "A validated script with enough content for the quality contract.", "scenes_layout_json": [{"visual_search_keywords": "rain portrait"}] * 3}


class IntelligenceTests(unittest.TestCase):
    def test_commits_script_and_storyboard_in_order(self):
        gateway = Gateway()
        result = VisionFlowShortFormIntelligence(gateway, Generator()).execute("run-1", {"title": "Title", "brief": "Brief", "input_payload": {}}, event_id="event-1", trace_id="a" * 32)
        self.assertEqual(3, result.scene_count)
        self.assertEqual(["QUEUED", "PLANNING", "SCRIPTED"], [call[0][1] for call in gateway.calls])
