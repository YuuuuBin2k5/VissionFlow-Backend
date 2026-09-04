import socket
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.source_media import UnsafeSourceUrl, validate_external_video_url


class SourceMediaPolicyTests(unittest.TestCase):
    def test_rejects_private_resolution(self):
        def resolver(*args, **kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))]
        with self.assertRaises(UnsafeSourceUrl):
            validate_external_video_url("http://example.test/video.mp4", resolver=resolver)

    def test_accepts_public_resolution(self):
        def resolver(*args, **kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
        self.assertEqual("https://example.com/video.mp4", validate_external_video_url("https://example.com/video.mp4", resolver=resolver))

    def test_rejects_non_http_and_embedded_credentials(self):
        with self.assertRaises(UnsafeSourceUrl):
            validate_external_video_url("file:///etc/passwd")
        with self.assertRaises(UnsafeSourceUrl):
            validate_external_video_url("https://user:secret@example.com/video.mp4")
