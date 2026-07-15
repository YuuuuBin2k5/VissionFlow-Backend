from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

from app.domain.local_auth import LocalAuthUser, canonical_email, validate_password


class PasswordHasher(Protocol):
    def hash(self, password: str) -> str: ...

    def verify(self, password_hash: str, password: str) -> bool: ...


class LocalAuthRepository(Protocol):
    def find_by_email(self, email: str) -> LocalAuthUser | None: ...

    def create_user(self, *, email: str, password_hash: str, display_name: str | None) -> LocalAuthUser: ...

    def record_audit(
        self, *, auth_user_id: uuid.UUID | None, event_type: str, outcome: str, metadata: dict | None = None
    ) -> None: ...


@dataclass(frozen=True)
class RegisterLocalUserCommand:
    email: str
    password: str
    display_name: str | None = None


class LocalEmailAlreadyRegistered(Exception):
    pass


class RegisterLocalUser:
    def __init__(self, repository: LocalAuthRepository, password_hasher: PasswordHasher) -> None:
        self._repository = repository
        self._password_hasher = password_hasher

    def execute(self, command: RegisterLocalUserCommand) -> LocalAuthUser:
        email = canonical_email(command.email)
        validate_password(command.password)
        if command.display_name is not None and not 1 <= len(command.display_name.strip()) <= 160:
            raise ValueError("display_name must be 1-160 characters when supplied")
        if self._repository.find_by_email(email) is not None:
            self._repository.record_audit(auth_user_id=None, event_type="registration", outcome="rejected")
            raise LocalEmailAlreadyRegistered("email already registered")
        user = self._repository.create_user(
            email=email,
            password_hash=self._password_hasher.hash(command.password),
            display_name=command.display_name.strip() if command.display_name else None,
        )
        self._repository.record_audit(auth_user_id=user.id, event_type="registration", outcome="succeeded")
        return user


class InvalidCredentials(Exception):
    """Deliberately generic to prevent account enumeration."""


@dataclass(frozen=True)
class AuthenticateLocalUserCommand:
    email: str
    password: str


class AuthenticateLocalUser:
    def __init__(self, repository: LocalAuthRepository, password_hasher: PasswordHasher) -> None:
        self._repository = repository
        self._password_hasher = password_hasher

    def execute(self, command: AuthenticateLocalUserCommand) -> LocalAuthUser:
        email = canonical_email(command.email)
        user = self._repository.find_by_email(email)
        if user is None or not user.is_active or not self._password_hasher.verify(user.password_hash, command.password):
            self._repository.record_audit(
                auth_user_id=user.id if user is not None else None,
                event_type="password_login",
                outcome="failed",
            )
            raise InvalidCredentials("invalid credentials")
        self._repository.record_audit(auth_user_id=user.id, event_type="password_login", outcome="succeeded")
        return user
