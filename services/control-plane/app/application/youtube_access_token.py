"""Refresh short-lived YouTube access tokens without exposing stored refresh tokens."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.core.publisher_token_cipher import PublisherTokenCipher
from app.core.youtube_publisher import YouTubePublisherSettings


class HttpResponse(Protocol):
    status_code: int
    def json(self) -> object: ...


class HttpClient(Protocol):
    def post(self, url: str, **kwargs: object) -> HttpResponse: ...


@dataclass(frozen=True)
class YouTubeAccessToken:
    value: str
    expires_in_seconds: int


class YouTubeAccessTokenRefresher:
    """Control-Plane-only OAuth refresh boundary."""

    def __init__(self, http: HttpClient, cipher: PublisherTokenCipher, settings: YouTubePublisherSettings) -> None:
        self._http, self._cipher, self._settings = http, cipher, settings

    def refresh(self, encrypted_refresh_token: str) -> YouTubeAccessToken:
        refresh_token = self._cipher.decrypt(encrypted_refresh_token)
        response = self._http.post(
            "https://oauth2.googleapis.com/token",
            data={"client_id": self._settings.client_id, "client_secret": self._settings.client_secret, "refresh_token": refresh_token, "grant_type": "refresh_token"},
            timeout=(3, 20),
        )
        if response.status_code != 200:
            data = response.json() if hasattr(response, "json") else {}
            err_code = data.get("error") if isinstance(data, dict) else ""
            if err_code == "invalid_grant":
                raise RuntimeError("YOUTUBE_SESSION_EXPIRED: Token YouTube đã hết hạn (Google OAuth)")
            raise RuntimeError(f"YouTube token refresh failed: {err_code or response.status_code}")
        data = response.json() if hasattr(response, "json") else {}
        value = data.get("access_token") if isinstance(data, dict) else None
        expires = data.get("expires_in") if isinstance(data, dict) else None
        if not isinstance(value, str) or not value or not isinstance(expires, int) or expires < 60:
            raise RuntimeError("Google could not issue a usable YouTube access token")
        return YouTubeAccessToken(value=value, expires_in_seconds=expires)
