from __future__ import annotations

import sys
import unittest
from pathlib import Path


SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.core.youtube_resumable_uploader import (  # noqa: E402
    YouTubeResumableUploader,
    YouTubeUploadMetadata,
)


class YouTubeNonPublicPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.uploader = YouTubeResumableUploader(session=object())

    def metadata(self, **overrides: object) -> YouTubeUploadMetadata:
        values = {
            "title": "VisionFlow Short",
            "description": "Description",
            "tags": ("shorts",),
            "privacy_status": "unlisted",
        }
        values.update(overrides)
        return YouTubeUploadMetadata(**values)

    def test_manual_upload_is_unlisted_without_publish_at(self) -> None:
        resource = self.uploader._build_resource(self.metadata())

        self.assertEqual("unlisted", resource["status"]["privacyStatus"])
        self.assertNotIn("publishAt", resource["status"])

    def test_scheduled_upload_is_private_with_publish_at(self) -> None:
        scheduled_at = "2026-10-01T12:00:00Z"
        resource = self.uploader._build_resource(
            self.metadata(privacy_status="private", publish_at_iso=scheduled_at)
        )

        self.assertEqual("private", resource["status"]["privacyStatus"])
        self.assertEqual(scheduled_at, resource["status"]["publishAt"])

    def test_public_upload_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "must use unlisted or private"):
            self.uploader._build_resource(self.metadata(privacy_status="public"))


if __name__ == "__main__":
    unittest.main()
