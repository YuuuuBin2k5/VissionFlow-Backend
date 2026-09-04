from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime

_EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def canonical_email(value: str) -> str:
    email = value.strip().casefold()
    if not _EMAIL_PATTERN.fullmatch(email) or len(email) > 320:
        raise ValueError("email must be a valid address of at most 320 characters")
    return email


def validate_password(value: str) -> None:
    # Length is intentionally the only composition rule; Argon2id supplies the resistance.
    if not 12 <= len(value) <= 1024:
        raise ValueError("password must be 12-1024 characters")


@dataclass(frozen=True)
class LocalAuthUser:
    id: uuid.UUID
    user_id: uuid.UUID
    email: str
    password_hash: str
    is_active: bool


@dataclass(frozen=True)
class RefreshTokenRecord:
    id: uuid.UUID
    session_id: uuid.UUID
    token_digest: str
    expires_at: datetime
    consumed_at: datetime | None
    revoked_at: datetime | None
