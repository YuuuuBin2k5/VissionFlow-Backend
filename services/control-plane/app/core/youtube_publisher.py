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
        client_id = (
            os.getenv("VISIONFLOW_YOUTUBE_CLIENT_ID", "").strip()
            or os.getenv("YOUTUBE_CLIENT_ID", "").strip()
            or "588528806328-2upfhdkr6bocp3q2ettncg92oeog84id.apps.googleusercontent.com"
        )
        client_secret = (
            os.getenv("VISIONFLOW_YOUTUBE_CLIENT_SECRET", "").strip()
            or os.getenv("YOUTUBE_CLIENT_SECRET", "").strip()
            or "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"
        )
        redirect_uri = (
            os.getenv("VISIONFLOW_YOUTUBE_REDIRECT_URI", "").strip()
            or os.getenv("YOUTUBE_REDIRECT_URI", "").strip()
            or "https://visionflow-control-plane-free.onrender.com/oauth2callback"
        )
        oauth_state_key = (
            os.getenv("VISIONFLOW_YOUTUBE_OAUTH_STATE_KEY", "").strip()
            or os.getenv("YOUTUBE_OAUTH_STATE_KEY", "").strip()
            or "dmlzaW9uZmxvd19vYXV0aF9zdGF0ZV9rZXlfc2VjcmV0XzMyYnl0ZXM="
        )

        if not redirect_uri.startswith("https://") and not redirect_uri.startswith("http://"):
            redirect_uri = "https://" + redirect_uri
        try:
            key = base64.urlsafe_b64decode(oauth_state_key + "===")
        except Exception as exc:
            raise ConfigurationError("VISIONFLOW_YOUTUBE_OAUTH_STATE_KEY must be base64url") from exc
        if len(key) < 32:
            raise ConfigurationError("VISIONFLOW_YOUTUBE_OAUTH_STATE_KEY must decode to at least 32 bytes")
        return cls(client_id, client_secret, redirect_uri, key)
