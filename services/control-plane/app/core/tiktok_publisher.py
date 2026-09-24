from __future__ import annotations

import base64
import os
from dataclasses import dataclass

from app.core.config import ConfigurationError


@dataclass(frozen=True)
class TikTokPublisherSettings:
    """Cấu hình cho TikTok Content Posting API (Cách 1 chính ngạch)."""
    client_key: str
    client_secret: str
    redirect_uri: str
    oauth_state_key: bytes

    @classmethod
    def from_env(cls) -> "TikTokPublisherSettings":
        client_key = (
            os.getenv("VISIONFLOW_TIKTOK_CLIENT_KEY", "").strip()
            or os.getenv("TIKTOK_CLIENT_KEY", "").strip()
        )
        client_secret = (
            os.getenv("VISIONFLOW_TIKTOK_CLIENT_SECRET", "").strip()
            or os.getenv("TIKTOK_CLIENT_SECRET", "").strip()
        )
        redirect_uri = (
            os.getenv("VISIONFLOW_TIKTOK_REDIRECT_URI", "").strip()
            or os.getenv("TIKTOK_REDIRECT_URI", "").strip()
            or "http://localhost:8000/integrations/tiktok/oauth/callback"
        )
        oauth_state_key = (
            os.getenv("VISIONFLOW_TIKTOK_OAUTH_STATE_KEY", "").strip()
            or os.getenv("TIKTOK_OAUTH_STATE_KEY", "").strip()
            or os.getenv("VISIONFLOW_YOUTUBE_OAUTH_STATE_KEY", "").strip()
            or "c2VjdXJlX3Rpa3Rva19zdGF0ZV9rZXlfZm9yX3Zpc2lvbmZsb3dfb2F1dGhfMjAyNg=="
        )

        if not client_key:
            # Fallback placeholder for development / sandbox if not set
            client_key = "aw_placeholder_key"
        if not client_secret:
            client_secret = "placeholder_secret"

        if not redirect_uri.startswith("https://") and not redirect_uri.startswith("http://"):
            redirect_uri = "https://" + redirect_uri

        try:
            key = base64.urlsafe_b64decode(oauth_state_key + "===")
        except Exception as exc:
            raise ConfigurationError("VISIONFLOW_TIKTOK_OAUTH_STATE_KEY must be base64url") from exc
        if len(key) < 16:
            raise ConfigurationError("VISIONFLOW_TIKTOK_OAUTH_STATE_KEY must decode to at least 16 bytes")

        return cls(client_key, client_secret, redirect_uri, key)
