from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import ConfigurationError


class PublisherTokenCipher:
    """Encrypt OAuth refresh tokens with a Render-held symmetric key."""

    def __init__(self, fernet: Fernet) -> None:
        self._fernet = fernet

    @classmethod
    def from_env(cls) -> "PublisherTokenCipher":
        raw = os.getenv("VISIONFLOW_PUBLISHER_TOKEN_ENCRYPTION_KEY", "").strip()
        if not raw:
            raise ConfigurationError("VISIONFLOW_PUBLISHER_TOKEN_ENCRYPTION_KEY must be configured")
        # Accept a 32-byte base64url secret and derive the Fernet key without
        # storing an opaque provider token in plaintext.
        try:
            material = base64.urlsafe_b64decode(raw + "===")
        except Exception as exc:
            raise ConfigurationError("VISIONFLOW_PUBLISHER_TOKEN_ENCRYPTION_KEY must be base64url") from exc
        if len(material) < 32:
            raise ConfigurationError("VISIONFLOW_PUBLISHER_TOKEN_ENCRYPTION_KEY must decode to at least 32 bytes")
        return cls(Fernet(base64.urlsafe_b64encode(hashlib.sha256(material).digest())))

    def encrypt(self, refresh_token: str) -> str:
        if not refresh_token.strip():
            raise ValueError("refresh token is required")
        return self._fernet.encrypt(refresh_token.encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError) as exc:
            raise ValueError("publisher refresh token cannot be decrypted") from exc
