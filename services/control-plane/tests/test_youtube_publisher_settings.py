import base64
import os
import unittest
from unittest.mock import patch

from app.core.config import ConfigurationError
from app.core.youtube_publisher import YouTubePublisherSettings


class YouTubePublisherSettingsTests(unittest.TestCase):
    def test_rejects_missing_or_insecure_configuration(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ConfigurationError): YouTubePublisherSettings.from_env()
        with patch.dict(os.environ, {"VISIONFLOW_YOUTUBE_CLIENT_ID":"id", "VISIONFLOW_YOUTUBE_CLIENT_SECRET":"secret", "VISIONFLOW_YOUTUBE_REDIRECT_URI":"http://bad", "VISIONFLOW_YOUTUBE_OAUTH_STATE_KEY":"x"}, clear=True):
            with self.assertRaisesRegex(ConfigurationError, "HTTPS"): YouTubePublisherSettings.from_env()

    def test_accepts_secure_configuration(self):
        key = base64.urlsafe_b64encode(b"a" * 32).decode().rstrip("=")
        values={"VISIONFLOW_YOUTUBE_CLIENT_ID":"id", "VISIONFLOW_YOUTUBE_CLIENT_SECRET":"secret", "VISIONFLOW_YOUTUBE_REDIRECT_URI":"https://console.example/callback", "VISIONFLOW_YOUTUBE_OAUTH_STATE_KEY":key}
        with patch.dict(os.environ, values, clear=True):
            self.assertEqual(32, len(YouTubePublisherSettings.from_env().oauth_state_key))
