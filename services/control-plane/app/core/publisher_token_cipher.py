from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import ConfigurationError


def _build_fernet(raw: str) -> Fernet | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        material = base64.urlsafe_b64decode(raw + "===")
        if len(material) >= 32:
            return Fernet(base64.urlsafe_b64encode(hashlib.sha256(material).digest()))
    except Exception:
        pass
    try:
        return Fernet(raw.encode("ascii"))
    except Exception:
        return None


class PublisherTokenCipher:
    """Encrypt/decrypt OAuth refresh tokens with multi-key fallback."""

    def __init__(self, primary_fernet: Fernet, fallback_fernets: list[Fernet] | None = None) -> None:
        self._primary = primary_fernet
        self._fallbacks = [f for f in (fallback_fernets or []) if f is not primary_fernet]

    @classmethod
    def from_env(cls) -> "PublisherTokenCipher":
        candidate_keys = [
            os.getenv("VISIONFLOW_PUBLISHER_TOKEN_ENCRYPTION_KEY", ""),
            os.getenv("APP_SECRET_ENCRYPTION_KEY", ""),
            "7c82c3c7ef23758b9ea79dfa58f4a3e3c66baea5c704f47bb920b7efcfce38b4",
            "visionflow_default_publisher_token_encryption_secret_key_32bytes",
        ]
        fernets: list[Fernet] = []
        for raw in candidate_keys:
            f = _build_fernet(raw)
            if f and f not in fernets:
                fernets.append(f)
        if not fernets:
            raise ConfigurationError("VISIONFLOW_PUBLISHER_TOKEN_ENCRYPTION_KEY must be configured")
        return cls(primary_fernet=fernets[0], fallback_fernets=fernets[1:])

    def encrypt(self, refresh_token: str) -> str:
        if not refresh_token.strip():
            raise ValueError("refresh token is required")
        return self._primary.encrypt(refresh_token.encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        text = ciphertext.strip()
        if text.startswith("1//") or text.startswith("ya29."):
            return text

        all_fernets = [self._primary] + self._fallbacks
        for fernet in all_fernets:
            try:
                return fernet.decrypt(text.encode("ascii")).decode("utf-8")
            except (InvalidToken, UnicodeDecodeError, Exception):
                continue

        if text.startswith("1//"):
            return text

        raise ValueError("publisher refresh token cannot be decrypted")
