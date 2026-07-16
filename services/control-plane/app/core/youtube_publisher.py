from __future__ import annotations

import base64
import os
from dataclasses import dataclass

from app.core.config import ConfigurationError


@dataclass(frozen=True)
class YouTubePublisherSettings:
    client_id: str
    client_secret: str
    redirect_uri: str
    oauth_state_key: bytes

    @classmethod
    def from_env(cls) -> "YouTubePublisherSettings":
        values = {key: os.getenv(key, "").strip() for key in (
            "VISIONFLOW_YOUTUBE_CLIENT_ID", "VISIONFLOW_YOUTUBE_CLIENT_SECRET",
            "VISIONFLOW_YOUTUBE_REDIRECT_URI", "VISIONFLOW_YOUTUBE_OAUTH_STATE_KEY",
        )}
        missing = [key for key, value in values.items() if not value]
        if missing:
            raise ConfigurationError(f"Missing YouTube publisher setting: {', '.join(missing)}")
        if not values["VISIONFLOW_YOUTUBE_REDIRECT_URI"].startswith("https://"):
            raise ConfigurationError("VISIONFLOW_YOUTUBE_REDIRECT_URI must use HTTPS")
        try:
            key = base64.urlsafe_b64decode(values["VISIONFLOW_YOUTUBE_OAUTH_STATE_KEY"] + "===")
        except Exception as exc:
            raise ConfigurationError("VISIONFLOW_YOUTUBE_OAUTH_STATE_KEY must be base64url") from exc
        if len(key) < 32:
            raise ConfigurationError("VISIONFLOW_YOUTUBE_OAUTH_STATE_KEY must decode to at least 32 bytes")
        return cls(values["VISIONFLOW_YOUTUBE_CLIENT_ID"], values["VISIONFLOW_YOUTUBE_CLIENT_SECRET"], values["VISIONFLOW_YOUTUBE_REDIRECT_URI"], key)
