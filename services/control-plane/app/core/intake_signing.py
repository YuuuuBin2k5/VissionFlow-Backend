"""Canonical HMAC signing for the isolated legacy-intake stream."""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass

from app.core.config import ConfigurationError


@dataclass(frozen=True)
class IntakeSigningSettings:
    key_id: str
    key: bytes

    @classmethod
    def from_env(cls) -> "IntakeSigningSettings":
        key_id = (os.getenv("VISIONFLOW_INTAKE_HMAC_KEY_ID") or "").strip()
        key = (os.getenv("VISIONFLOW_INTAKE_HMAC_KEY") or "").strip()
        if not key_id or not key:
            raise ConfigurationError(
                "VISIONFLOW_INTAKE_HMAC_KEY_ID and VISIONFLOW_INTAKE_HMAC_KEY must be configured"
            )
        return cls(key_id=key_id, key=key.encode("utf-8"))


def canonical_message_bytes(envelope: dict[str, object]) -> bytes:
    import json

    return json.dumps(envelope, separators=(",", ":"), sort_keys=True).encode("utf-8")


def sign(envelope: dict[str, object], settings: IntakeSigningSettings) -> str:
    return hmac.new(settings.key, canonical_message_bytes(envelope), hashlib.sha256).hexdigest()
