import json
import unittest
from pathlib import Path
from unittest.mock import patch

from worker.services.visionflow_media_inspector import MediaInspectionError, inspect_local_mp4


class VisionFlowMediaInspectorTests(unittest.TestCase):
    def test_parses_real_qa_fields_from_ffprobe_json(self):
        completed = type("Result", (), {"returncode": 0, "stdout": json.dumps({"format": {"duration": "45.2"}, "streams": [{"codec_type": "video", "codec_name": "h264", "width": 1080, "height": 1920}, {"codec_type": "audio", "codec_name": "aac"}]})})()
        with patch("worker.services.visionflow_media_inspector.subprocess.run", return_value=completed):
            result = inspect_local_mp4(Path("artifact.mp4"))
        self.assertEqual((45.2, 1080, 1920, "h264", True), (result.duration_seconds, result.width, result.height, result.video_codec, result.has_audio))

    def test_rejects_missing_video_stream(self):
        completed = type("Result", (), {"returncode": 0, "stdout": json.dumps({"format": {"duration": "45"}, "streams": []})})()
        with patch("worker.services.visionflow_media_inspector.subprocess.run", return_value=completed), self.assertRaisesRegex(MediaInspectionError, "no video"):
            inspect_local_mp4(Path("artifact.mp4"))


if __name__ == "__main__":
    unittest.main()
