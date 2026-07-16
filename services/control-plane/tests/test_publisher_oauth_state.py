import base64
import os
import unittest
import uuid
from unittest.mock import patch

from app.core.publisher_oauth_state import issue_state, verify_state


class PublisherOAuthStateTests(unittest.TestCase):
    def setUp(self):
        key = base64.urlsafe_b64encode(b"z" * 32).decode().rstrip("=")
        self.env = {"VISIONFLOW_YOUTUBE_CLIENT_ID":"id", "VISIONFLOW_YOUTUBE_CLIENT_SECRET":"secret", "VISIONFLOW_YOUTUBE_REDIRECT_URI":"https://example.com/callback", "VISIONFLOW_YOUTUBE_OAUTH_STATE_KEY":key}

    def test_signed_state_round_trip_and_tamper_rejection(self):
        with patch.dict(os.environ, self.env, clear=True):
            state, _, _ = issue_state(uuid.UUID("00000000-0000-0000-0000-000000000001"), "local|operator", now=100)
            self.assertEqual("local|operator", verify_state(state, now=101)["s"])
            with self.assertRaises(ValueError): verify_state(state[:-1] + "0", now=101)

    def test_expired_state_is_rejected(self):
        with patch.dict(os.environ, self.env, clear=True):
            state, _, _ = issue_state(uuid.uuid4(), "local|operator", now=100)
            with self.assertRaises(ValueError): verify_state(state, now=701)
