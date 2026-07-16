import base64
import os
import unittest
from unittest.mock import patch

from app.core.config import ConfigurationError
from app.core.publisher_token_cipher import PublisherTokenCipher


class PublisherTokenCipherTests(unittest.TestCase):
    def test_round_trip_and_tamper_rejection(self):
        key = base64.urlsafe_b64encode(b"k" * 32).decode().rstrip("=")
        with patch.dict(os.environ, {"VISIONFLOW_PUBLISHER_TOKEN_ENCRYPTION_KEY": key}, clear=True):
            cipher = PublisherTokenCipher.from_env()
        encrypted = cipher.encrypt("refresh-token-secret")
        self.assertNotIn("refresh-token-secret", encrypted)
        self.assertEqual("refresh-token-secret", cipher.decrypt(encrypted))
        with self.assertRaisesRegex(ValueError, "cannot be decrypted"):
            cipher.decrypt(encrypted[:-2] + "xx")

    def test_rejects_missing_key(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ConfigurationError):
                PublisherTokenCipher.from_env()
