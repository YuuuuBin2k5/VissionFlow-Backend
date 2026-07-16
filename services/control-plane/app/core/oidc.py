from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any
from urllib.parse import urlparse

import jwt
from jwt import InvalidTokenError, PyJWKClient, PyJWKClientConnectionError, PyJWKClientError

from app.core.config import ConfigurationError


@dataclass(frozen=True)
class VerifiedIdentity:
    subject: str
    email: str | None
    display_name: str | None
    scopes: list[str] = field(default_factory=list)


class OidcProviderUnavailable(RuntimeError):
    """Raised when the configured OIDC key service cannot be reached."""


@dataclass(frozen=True)
class OidcSettings:
    issuer: str
    audience: str
    jwks_url: str
    allowed_algorithms: tuple[str, ...]

    @classmethod
    def from_env(cls) -> "OidcSettings":
        issuer = _require_https_url("OIDC_ISSUER", os.getenv("OIDC_ISSUER"))
        jwks_url = _require_https_url("OIDC_JWKS_URL", os.getenv("OIDC_JWKS_URL"))
        audience = _require_value("OIDC_AUDIENCE", os.getenv("OIDC_AUDIENCE"))
        algorithms = tuple(
            algorithm.strip()
            for algorithm in os.getenv("OIDC_ALLOWED_ALGORITHMS", "RS256,ES256").split(",")
            if algorithm.strip()
        )
        if not algorithms or any(algorithm not in {"RS256", "ES256"} for algorithm in algorithms):
            raise ConfigurationError("OIDC_ALLOWED_ALGORITHMS may only contain RS256 and ES256")
        return cls(issuer=issuer, audience=audience, jwks_url=jwks_url, allowed_algorithms=algorithms)


class OidcTokenVerifier:
    """Verifies signed OIDC access tokens against a configured HTTPS JWKS endpoint."""

    def __init__(self, settings: OidcSettings) -> None:
        self._settings = settings
        self._jwks_client = _get_jwks_client(settings.jwks_url)

    def verify(self, encoded_token: str) -> VerifiedIdentity:
        try:
            signing_key = self._jwks_client.get_signing_key_from_jwt(encoded_token)
            claims: dict[str, Any] = jwt.decode(
                encoded_token,
                signing_key.key,
                algorithms=list(self._settings.allowed_algorithms),
                audience=self._settings.audience,
                issuer=self._settings.issuer,
                options={"require": ["exp", "iat", "sub"]},
            )
        except PyJWKClientConnectionError as exc:
            raise OidcProviderUnavailable("OIDC key service is unavailable") from exc
        except (InvalidTokenError, PyJWKClientError) as exc:
            raise PermissionError("OIDC token is invalid") from exc

        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject.strip():
            raise PermissionError("OIDC token is missing a subject")
        email = claims.get("email")
        display_name = claims.get("name")
        scopes_claim = claims.get("scope") or claims.get("scopes") or claims.get("permissions") or ""
        if isinstance(scopes_claim, str):
            scopes = scopes_claim.split()
        elif isinstance(scopes_claim, list):
            scopes = [str(s) for s in scopes_claim]
        else:
            scopes = []
        return VerifiedIdentity(
            subject=subject,
            email=email if isinstance(email, str) else None,
            display_name=display_name if isinstance(display_name, str) else None,
            scopes=scopes,
        )


@lru_cache(maxsize=4)
def _get_jwks_client(jwks_url: str) -> PyJWKClient:
    return PyJWKClient(jwks_url, cache_jwk_set=True, lifespan=300)


def _require_value(name: str, value: str | None) -> str:
    if not value or not value.strip():
        raise ConfigurationError(f"{name} must be configured")
    return value.strip()


def _require_https_url(name: str, value: str | None) -> str:
    normalized = _require_value(name, value)
    parsed = urlparse(normalized)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ConfigurationError(f"{name} must use an HTTPS URL")
    return normalized
