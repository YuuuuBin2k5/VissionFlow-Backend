"""Password hashing adapter boundary for VisionFlow self-managed authentication."""

from __future__ import annotations

from typing import Protocol

from argon2 import PasswordHasher as Argon2LibraryHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from argon2.low_level import Type


class PasswordHasher(Protocol):
    """Port used by authentication use cases; implementations never expose raw passwords."""

    def hash(self, password: str) -> str: ...

    def verify(self, encoded_hash: str, password: str) -> bool: ...


class PasswordPolicyError(ValueError):
    """Raised before a password reaches a slow hash function."""


class Argon2idPasswordHasher:
    """Production password hasher with explicit Argon2id parameters.

    Parameters are intentionally injectable so a future calibrated implementation can
    replace this adapter without changing application use cases (Open/Closed Principle).
    """

    def __init__(
        self,
        *,
        time_cost: int = 3,
        memory_cost_kib: int = 65_536,
        parallelism: int = 2,
        hash_len: int = 32,
        salt_len: int = 16,
    ) -> None:
        self._hasher = Argon2LibraryHasher(
            time_cost=time_cost,
            memory_cost=memory_cost_kib,
            parallelism=parallelism,
            hash_len=hash_len,
            salt_len=salt_len,
            type=Type.ID,
        )

    def hash(self, password: str) -> str:
        return self._hasher.hash(_validated_password(password))

    def verify(self, encoded_hash: str, password: str) -> bool:
        if not isinstance(encoded_hash, str) or not encoded_hash.startswith("$argon2id$"):
            return False
        try:
            return self._hasher.verify(encoded_hash, password)
        except (InvalidHashError, VerificationError, VerifyMismatchError):
            return False


def _validated_password(password: str) -> str:
    if not isinstance(password, str) or len(password) < 12:
        raise PasswordPolicyError("Password must contain at least 12 characters")
    if len(password) > 1024:
        raise PasswordPolicyError("Password must not exceed 1024 characters")
    return password
