from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.local_auth import LocalAuthUser, RefreshTokenRecord
from app.infrastructure.models import AuthAuditEvent, AuthRefreshToken, AuthSession, AuthUser, User


class SqlAlchemyLocalAuthRepository:
    """Credential persistence adapter. Application code only depends on its port."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def find_by_email(self, email: str) -> LocalAuthUser | None:
        record = self._session.scalar(select(AuthUser).where(AuthUser.email == email))
        return _to_domain(record) if record is not None else None

    def create_user(self, *, email: str, password_hash: str, display_name: str | None) -> LocalAuthUser:
        # The stable local subject is derived from the generated domain-user UUID.
        # It must match the ``sub`` claim later issued for membership/RBAC lookups.
        user_id = uuid.uuid4()
        user = User(id=user_id, identity_subject=f"local|{user_id}", email=email, display_name=display_name)
        self._session.add(user)
        self._session.flush()
        auth_user = AuthUser(user_id=user.id, email=email, password_hash=password_hash)
        self._session.add(auth_user)
        self._session.flush()
        return _to_domain(auth_user)

    def record_audit(
        self, *, auth_user_id: uuid.UUID | None, event_type: str, outcome: str, metadata: dict | None = None
    ) -> None:
        self._session.add(
            AuthAuditEvent(
                auth_user_id=auth_user_id,
                event_type=event_type,
                outcome=outcome,
                metadata_json=metadata or {},
            )
        )

    def create_session(
        self, *, auth_user_id: uuid.UUID, expires_at: datetime, ip_address: str | None, user_agent: str | None
    ) -> uuid.UUID:
        record = AuthSession(
            auth_user_id=auth_user_id,
            expires_at=expires_at,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self._session.add(record)
        self._session.flush()
        return record.id

    def create_refresh_token(self, *, session_id: uuid.UUID, token_digest: str, expires_at: datetime) -> RefreshTokenRecord:
        record = AuthRefreshToken(session_id=session_id, token_digest=token_digest, expires_at=expires_at)
        self._session.add(record)
        self._session.flush()
        return _to_refresh_record(record)

    def find_refresh_token_for_update(
        self, token_digest: str
    ) -> tuple[RefreshTokenRecord, LocalAuthUser, bool] | None:
        row = self._session.execute(
            select(AuthRefreshToken, AuthSession, AuthUser)
            .join(AuthSession, AuthSession.id == AuthRefreshToken.session_id)
            .join(AuthUser, AuthUser.id == AuthSession.auth_user_id)
            .where(AuthRefreshToken.token_digest == token_digest)
            .with_for_update()
        ).one_or_none()
        if row is None:
            return None
        token, session, user = row
        now = datetime.now(UTC)
        session_is_active = session.revoked_at is None and session.expires_at > now
        return _to_refresh_record(token), _to_domain(user), session_is_active

    def rotate_refresh_token(
        self, *, previous_token_id: uuid.UUID, session_id: uuid.UUID, token_digest: str, expires_at: datetime
    ) -> RefreshTokenRecord:
        previous = self._session.get(AuthRefreshToken, previous_token_id, with_for_update=True)
        if previous is None or previous.session_id != session_id:
            raise LookupError("refresh token not found")
        replacement = AuthRefreshToken(session_id=session_id, token_digest=token_digest, expires_at=expires_at)
        self._session.add(replacement)
        self._session.flush()
        previous.consumed_at = datetime.now(UTC)
        previous.replaced_by_id = replacement.id
        return _to_refresh_record(replacement)

    def revoke_session(self, *, session_id: uuid.UUID, reason: str) -> None:
        session = self._session.get(AuthSession, session_id, with_for_update=True)
        if session is None:
            return
        if session.revoked_at is None:
            session.revoked_at = datetime.now(UTC)
            session.revoke_reason = reason[:96]
        for token in self._session.scalars(
            select(AuthRefreshToken).where(AuthRefreshToken.session_id == session_id).with_for_update()
        ):
            if token.revoked_at is None:
                token.revoked_at = datetime.now(UTC)

    def session_belongs_to_user(self, *, session_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        return self._session.scalar(
            select(AuthSession.id)
            .join(AuthUser, AuthUser.id == AuthSession.auth_user_id)
            .where(AuthSession.id == session_id, AuthUser.user_id == user_id)
        ) is not None


def _to_domain(record: AuthUser) -> LocalAuthUser:
    return LocalAuthUser(
        id=record.id,
        user_id=record.user_id,
        email=record.email,
        password_hash=record.password_hash,
        is_active=record.is_active,
    )


def _to_refresh_record(record: AuthRefreshToken) -> RefreshTokenRecord:
    return RefreshTokenRecord(
        id=record.id,
        session_id=record.session_id,
        token_digest=record.token_digest,
        expires_at=record.expires_at,
        consumed_at=record.consumed_at,
        revoked_at=record.revoked_at,
    )
