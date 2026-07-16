import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.application.youtube_access_token import YouTubeAccessTokenRefresher


class YouTubeAccessTokenTests(unittest.TestCase):
    def test_refreshes_with_decrypted_token_and_returns_short_lived_token(self):
        http, cipher, settings = MagicMock(), MagicMock(), MagicMock(client_id="id", client_secret="secret")
        cipher.decrypt.return_value = "stored-refresh-token"
        response = MagicMock(status_code=200); response.json.return_value = {"access_token": "short-lived", "expires_in": 3600}; http.post.return_value = response
        token = YouTubeAccessTokenRefresher(http, cipher, settings).refresh("encrypted")
        self.assertEqual("short-lived", token.value)
        self.assertEqual(3600, token.expires_in_seconds)
        self.assertEqual("stored-refresh-token", http.post.call_args.kwargs["data"]["refresh_token"])

