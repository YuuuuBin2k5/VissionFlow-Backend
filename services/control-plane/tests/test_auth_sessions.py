from __future__ import annotations

import sys
import unittest
import uuid
from datetime import UTC, datetime
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.application.auth_sessions import InvalidRefreshToken, SessionTokenService  # noqa: E402
from app.domain.local_auth import LocalAuthUser, RefreshTokenRecord  # noqa: E402


class FakeIssuer:
    def issue(self, *, subject, session_id, extra_claims=None):
        return f"access:{subject}:{session_id}"


class FakeRepository:
    def __init__(self, user):
        self.user = user
        self.session_id = uuid.uuid4()
        self.tokens = {}
        self.revoked = []
        self.audits = []

    def create_session(self, **kwargs):
        return self.session_id

    def create_refresh_token(self, *, session_id, token_digest, expires_at):
        record = RefreshTokenRecord(uuid.uuid4(), session_id, token_digest, expires_at, None, None)
        self.tokens[token_digest] = record
        return record

    def find_refresh_token_for_update(self, digest):
        token = self.tokens.get(digest)
        return (token, self.user, True) if token else None

    def rotate_refresh_token(self, *, previous_token_id, session_id, token_digest, expires_at):
        previous = next(token for token in self.tokens.values() if token.id == previous_token_id)
        self.tokens[previous.token_digest] = RefreshTokenRecord(
            previous.id, previous.session_id, previous.token_digest, previous.expires_at, NOW, previous.revoked_at
        )
        return self.create_refresh_token(session_id=session_id, token_digest=token_digest, expires_at=expires_at)

    def revoke_session(self, *, session_id, reason):
        self.revoked.append((session_id, reason))

    def session_belongs_to_user(self, *, session_id, user_id):
        return session_id == self.session_id and user_id == self.user.id

    def record_audit(self, **kwargs):
        self.audits.append(kwargs)


NOW = datetime(2026, 7, 15, tzinfo=UTC)


class SessionTokenServiceTests(unittest.TestCase):
    def setUp(self):
        self.user = LocalAuthUser(uuid.uuid4(), uuid.uuid4(), "operator@visionflow.dev", "hash", True)
        self.repository = FakeRepository(self.user)
        tokens = iter(["a" * 48, "b" * 48])
        self.service = SessionTokenService(
            self.repository, FakeIssuer(), now=lambda: NOW, token_factory=lambda: next(tokens), access_token_ttl_seconds=900
        )

    def test_refresh_rotation_consumes_old_credential_and_issues_new_pair(self):
        created = self.service.create(user=self.user, ip_address=None, user_agent=None)
        rotated = self.service.rotate(refresh_token=created.refresh_token)
        self.assertNotEqual(created.refresh_token, rotated.refresh_token)
        self.assertIn(f"{self.repository.session_id}", rotated.access_token)
        with self.assertRaises(InvalidRefreshToken):
            self.service.rotate(refresh_token=created.refresh_token)
        self.assertEqual((self.repository.session_id, "refresh_token_reuse"), self.repository.revoked[-1])

    def test_logout_only_revokes_the_authenticated_users_session(self):
        self.service.logout(user_id=self.user.id, session_id=self.repository.session_id)
        self.assertEqual((self.repository.session_id, "logout"), self.repository.revoked[-1])
        with self.assertRaises(InvalidRefreshToken):
            self.service.logout(user_id=uuid.uuid4(), session_id=self.repository.session_id)
