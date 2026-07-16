from __future__ import annotations

from datetime import UTC, datetime
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.models import PublisherOAuthAttempt


class PublisherOAuthAttemptRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, *, organization_id: uuid.UUID, provider: str, state_digest: str, requested_by_subject: str, expires_at: datetime) -> None:
        self._session.add(PublisherOAuthAttempt(organization_id=organization_id, provider=provider, state_digest=state_digest, requested_by_subject=requested_by_subject, expires_at=expires_at))
        self._session.commit()

    def consume(self, *, organization_id: uuid.UUID, provider: str, state_digest: str, requested_by_subject: str) -> PublisherOAuthAttempt:
        attempt = self._session.scalar(select(PublisherOAuthAttempt).where(
            PublisherOAuthAttempt.organization_id == organization_id,
            PublisherOAuthAttempt.provider == provider,
            PublisherOAuthAttempt.state_digest == state_digest,
            PublisherOAuthAttempt.requested_by_subject == requested_by_subject,
        ).with_for_update())
        now = datetime.now(UTC)
        if attempt is None or attempt.consumed_at is not None or attempt.expires_at <= now:
            self._session.rollback()
            raise ValueError("OAuth authorization attempt is invalid, expired, or already consumed")
        attempt.consumed_at = now
        self._session.commit()
        return attempt
