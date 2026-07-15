import os
import unittest
from unittest.mock import patch

from worker.services.visionflow_object_storage import VisionFlowObjectStorageSettings


class ObjectStorageSettingsTests(unittest.TestCase):
    def test_rejects_non_https_endpoint(self):
        values = {
            "VISIONFLOW_OBJECT_STORE_ENDPOINT": "http://storage.example.com",
            "VISIONFLOW_OBJECT_STORE_BUCKET": "visionflow-assets",
            "VISIONFLOW_OBJECT_STORE_ACCESS_KEY_ID": "key",
            "VISIONFLOW_OBJECT_STORE_SECRET_ACCESS_KEY": "secret",
        }
        with patch.dict(os.environ, values, clear=True):
            with self.assertRaisesRegex(ValueError, "HTTPS"):
                VisionFlowObjectStorageSettings.from_env()

    def test_accepts_r2_compatible_settings(self):
        values = {
            "VISIONFLOW_OBJECT_STORE_ENDPOINT": "https://example.r2.cloudflarestorage.com",
            "VISIONFLOW_OBJECT_STORE_BUCKET": "visionflow-assets",
            "VISIONFLOW_OBJECT_STORE_ACCESS_KEY_ID": "key",
            "VISIONFLOW_OBJECT_STORE_SECRET_ACCESS_KEY": "secret",
        }
        with patch.dict(os.environ, values, clear=True):
            self.assertEqual("auto", VisionFlowObjectStorageSettings.from_env().region)
