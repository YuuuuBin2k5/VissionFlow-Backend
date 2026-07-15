"""Session lifecycle use cases for VisionFlow local authentication.

Refresh credentials are opaque, random values.  Only a SHA-256 digest reaches
PostgreSQL, and every successful refresh consumes and replaces its token in the
same transaction.  The repository port keeps this policy independent of SQLAlchemy.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Callable, Protocol

from app.domain.local_auth import LocalAuthUser, RefreshTokenRecord


class SessionRepository(Protocol):
    def create_session(
        self, *, auth_user_id: uuid.UUID, expires_at: datetime, ip_address: str | None, user_agent: str | None
    ) -> uuid.UUID: ...

    def create_refresh_token(self, *, session_id: uuid.UUID, token_digest: str, expires_at: datetime) -> RefreshTokenRecord: ...

    def find_refresh_token_for_update(self, token_digest: str) -> tuple[RefreshTokenRecord, LocalAuthUser, bool] | None: ...

    def rotate_refresh_token(
        self, *, previous_token_id: uuid.UUID, session_id: uuid.UUID, token_digest: str, expires_at: datetime
    ) -> RefreshTokenRecord: ...

    def revoke_session(self, *, session_id: uuid.UUID, reason: str) -> None: ...

    def session_belongs_to_user(self, *, session_id: uuid.UUID, user_id: uuid.UUID) -> bool: ...

    def record_audit(
        self, *, auth_user_id: uuid.UUID | None, event_type: str, outcome: str, metadata: dict | None = None
    ) -> None: ...


class AccessTokenIssuer(Protocol):
    def issue(self, *, subject: str, session_id: str, extra_claims: dict | None = None) -> str: ...


class InvalidRefreshToken(Exception):
    """Publicly mapped to a generic unauthenticated response."""


@dataclass(frozen=True)
class SessionTokens:
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int
    session_id: uuid.UUID


class SessionTokenService:
    def __init__(
        self,
        repository: SessionRepository,
        access_token_issuer: AccessTokenIssuer,
        *,
        refresh_ttl: timedelta = timedelta(days=30),
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        token_factory: Callable[[], str] = lambda: secrets.token_urlsafe(48),
        access_token_ttl_seconds: int = 900,
    ) -> None:
        if refresh_ttl < timedelta(hours=1) or refresh_ttl > timedelta(days=90):
            raise ValueError("refresh_ttl must be between 1 hour and 90 days")
        self._repository = repository
        self._issuer = access_token_issuer
        self._refresh_ttl = refresh_ttl
        self._now = now
        self._token_factory = token_factory
        self._access_token_ttl_seconds = access_token_ttl_seconds

    def create(self, *, user: LocalAuthUser, ip_address: str | None, user_agent: str | None) -> SessionTokens:
        now = self._now()
        session_id = self._repository.create_session(
            auth_user_id=user.id, expires_at=now + self._refresh_ttl, ip_address=ip_address, user_agent=user_agent
        )
        raw_refresh_token = self._new_raw_token()
        self._repository.create_refresh_token(
            session_id=session_id, token_digest=_digest(raw_refresh_token), expires_at=now + self._refresh_ttl
        )
        self._repository.record_audit(auth_user_id=user.id, event_type="session_created", outcome="succeeded")
        return self._tokens(user=user, session_id=session_id, raw_refresh_token=raw_refresh_token)

    def rotate(self, *, refresh_token: str) -> SessionTokens:
        raw_refresh_token = _validated_raw_token(refresh_token)
        resolved = self._repository.find_refresh_token_for_update(_digest(raw_refresh_token))
        if resolved is None:
            raise InvalidRefreshToken("invalid refresh token")
        token, user, session_is_active = resolved
        now = self._now()
        invalid = token.consumed_at is not None or token.revoked_at is not None or token.expires_at <= now
        if invalid or not session_is_active or not user.is_active:
            # Reuse of a consumed credential revokes the complete session family.
            self._repository.revoke_session(session_id=token.session_id, reason="refresh_token_reuse" if token.consumed_at else "invalid_refresh")
            self._repository.record_audit(
                auth_user_id=user.id,
                event_type="refresh_token",
                outcome="rejected",
                metadata={"reason": "reused_or_expired"},
            )
            raise InvalidRefreshToken("invalid refresh token")
        replacement = self._new_raw_token()
        self._repository.rotate_refresh_token(
            previous_token_id=token.id,
            session_id=token.session_id,
            token_digest=_digest(replacement),
            expires_at=now + self._refresh_ttl,
        )
        self._repository.record_audit(auth_user_id=user.id, event_type="refresh_token", outcome="succeeded")
        return self._tokens(user=user, session_id=token.session_id, raw_refresh_token=replacement)

    def logout(self, *, user_id: uuid.UUID, session_id: uuid.UUID) -> None:
        if not self._repository.session_belongs_to_user(session_id=session_id, user_id=user_id):
            raise InvalidRefreshToken("session not found")
        self._repository.revoke_session(session_id=session_id, reason="logout")
        self._repository.record_audit(auth_user_id=None, event_type="logout", outcome="succeeded")

    def _tokens(self, *, user: LocalAuthUser, session_id: uuid.UUID, raw_refresh_token: str) -> SessionTokens:
        return SessionTokens(
            access_token=self._issuer.issue(
                subject=f"local|{user.user_id}", session_id=str(session_id), extra_claims={"email": user.email}
            ),
            refresh_token=raw_refresh_token,
            token_type="Bearer",
            expires_in=self._access_token_ttl_seconds,
            session_id=session_id,
        )

    def _new_raw_token(self) -> str:
        return _validated_raw_token(self._token_factory())


def _digest(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _validated_raw_token(value: str) -> str:
    if not isinstance(value, str) or len(value) < 43 or len(value) > 512:
        raise InvalidRefreshToken("invalid refresh token")
    return value
