import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.core.config import ConfigurationError  # noqa: E402
from app.routers.integrations import _console_callback_url  # noqa: E402


class PublisherOauthCallbackTests(unittest.TestCase):
    def test_returns_only_the_first_configured_https_console_origin(self) -> None:
        with patch.dict(os.environ, {"VISIONFLOW_WEB_ORIGINS": "https://vision-flow-console.vercel.app, https://staging.example"}, clear=True):
            self.assertEqual(
                "https://vision-flow-console.vercel.app/?youtube_oauth=connected",
                _console_callback_url(),
            )

    def test_rejects_missing_or_non_https_console_origin(self) -> None:
        for origins in ("", "http://localhost:5173"):
            with self.subTest(origins=origins), patch.dict(os.environ, {"VISIONFLOW_WEB_ORIGINS": origins}, clear=True):
                with self.assertRaises(ConfigurationError):
                    _console_callback_url()


if __name__ == "__main__":
    unittest.main()
