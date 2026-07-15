import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.infrastructure.redis_stream_publisher import RedisStreamSettings  # noqa: E402


class RedisStreamSettingsTests(unittest.TestCase):
    def test_rejects_plaintext_remote_redis(self) -> None:
        with patch.dict(os.environ, {"REDIS_URL": "redis://redis.example.com:6379/0"}, clear=True):
            with self.assertRaisesRegex(ValueError, "TLS"):
                RedisStreamSettings.from_env()

    def test_accepts_tls_redis_and_explicit_stream(self) -> None:
        values = {
            "REDIS_URL": "rediss://default:secret@redis.example.com:6379/0",
            "VISIONFLOW_EVENTS_STREAM": "visionflow.staging.v1",
        }
        with patch.dict(os.environ, values, clear=True):
            settings = RedisStreamSettings.from_env()
        self.assertEqual("visionflow.staging.v1", settings.stream)
