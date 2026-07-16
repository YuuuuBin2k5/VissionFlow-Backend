"""Dedicated encryption boundary for provider API credentials."""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import ConfigurationError


class ProviderCredentialCipher:
    def __init__(self, fernet: Fernet) -> None:
        self._fernet = fernet

    @classmethod
    def from_env(cls) -> "ProviderCredentialCipher":
        raw = os.getenv("VISIONFLOW_CREDENTIAL_ENCRYPTION_KEY", "").strip()
        if not raw:
            raise ConfigurationError("VISIONFLOW_CREDENTIAL_ENCRYPTION_KEY must be configured")
        try:
            material = base64.urlsafe_b64decode(raw + "===")
        except Exception as exc:
            raise ConfigurationError("VISIONFLOW_CREDENTIAL_ENCRYPTION_KEY must be base64url") from exc
        if len(material) < 32:
            raise ConfigurationError("VISIONFLOW_CREDENTIAL_ENCRYPTION_KEY must decode to at least 32 bytes")
        return cls(Fernet(base64.urlsafe_b64encode(hashlib.sha256(material).digest())))

    def encrypt(self, secret: str) -> str:
        if not secret.strip():
            raise ValueError("provider secret is required")
        return self._fernet.encrypt(secret.encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError) as exc:
            raise ValueError("provider credential cannot be decrypted") from exc


def secret_fingerprint(secret: str) -> str:
    """Detect duplicate keys without returning or logging plaintext."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()
