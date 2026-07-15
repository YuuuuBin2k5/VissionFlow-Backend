import unittest
from unittest.mock import patch
from worker.services.final_exporter import FinalExporter

class Clip:
    def __init__(self): self.kwargs = None
    def write_videofile(self, path, **kwargs): self.kwargs = (path, kwargs)

class VisionFlowExporterTests(unittest.TestCase):
    def test_exports_without_legacy_job_id_or_progress_bridge(self):
        clip = Clip()
        with patch("worker.services.final_exporter.Path.mkdir"):
            result = FinalExporter().export_visionflow_video(clip, "C:/workspace/export.mp4", "C:/workspace/audio.m4a")
        self.assertEqual("C:/workspace/export.mp4", result)
        self.assertIsNone(clip.kwargs[1]["logger"])
