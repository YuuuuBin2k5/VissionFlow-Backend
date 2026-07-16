import tempfile
import unittest
from pathlib import Path

from visionflow_publisher.youtube_resumable import YouTubeResumableUploader, YouTubeUploadMetadata


class Response:
    def __init__(self, code, headers=None, payload=None): self.status_code, self.headers, self._payload = code, headers or {}, payload or {}
    def json(self): return self._payload


class Http:
    def __init__(self): self.calls = []
    def post(self, *args, **kwargs): self.calls.append(("post", args, kwargs)); return Response(200, {"Location": "https://upload.example/session"})
    def put(self, *args, **kwargs): self.calls.append(("put", args, kwargs)); return Response(200, payload={"id": "youtube-video-1"})


class YouTubeResumableTests(unittest.TestCase):
    def test_uploads_final_export_via_resumable_session(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "final.mp4"; path.write_bytes(b"video")
            http = Http()
            result = YouTubeResumableUploader(http).upload(access_token="short-lived", video_path=path, metadata=YouTubeUploadMetadata("A title", "description", ("shorts",)))
        self.assertEqual("youtube-video-1", result.video_id)
        self.assertEqual(["post", "put"], [call[0] for call in http.calls])

