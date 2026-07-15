"""RS256 access-token signing and JWKS publication for VisionFlow self-auth.

This module is a security adapter, not an HTTP concern.  Routers and use cases
depend on its narrow protocols so a managed HSM/KMS signer can be introduced
without rewriting the authentication application layer.
"""

from __future__ import annotations

import base64
import os
import secrets
import time
from dataclasses import dataclass
from collections.abc import Callable
from typing import Any, Protocol
from urllib.parse import urlparse

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

from app.core.config import ConfigurationError


class AccessTokenSigner(Protocol):
    def issue(self, *, subject: str, session_id: str, extra_claims: dict[str, Any] | None = None) -> str: ...

    def jwks(self) -> dict[str, list[dict[str, Any]]]: ...


@dataclass(frozen=True)
class InternalAuthSettings:
    issuer: str
    audience: str
    key_id: str
    private_key_pem: bytes
    access_token_ttl_seconds: int

    @classmethod
    def from_env(cls) -> "InternalAuthSettings":
        encoded_key = _required("VISIONFLOW_AUTH_PRIVATE_KEY_PEM_BASE64")
        try:
            private_key_pem = base64.b64decode(encoded_key, validate=True)
        except ValueError as exc:
            raise ConfigurationError("VISIONFLOW_AUTH_PRIVATE_KEY_PEM_BASE64 must be valid base64") from exc
        if not private_key_pem:
            raise ConfigurationError("VISIONFLOW_AUTH_PRIVATE_KEY_PEM_BASE64 must not be empty")
        ttl_raw = os.getenv("VISIONFLOW_AUTH_ACCESS_TOKEN_TTL_SECONDS", "900")
        try:
            ttl_seconds = int(ttl_raw)
        except ValueError as exc:
            raise ConfigurationError("VISIONFLOW_AUTH_ACCESS_TOKEN_TTL_SECONDS must be an integer") from exc
        if not 60 <= ttl_seconds <= 3600:
            raise ConfigurationError("VISIONFLOW_AUTH_ACCESS_TOKEN_TTL_SECONDS must be between 60 and 3600")
        return cls(
            issuer=_https_url("VISIONFLOW_AUTH_ISSUER"),
            audience=_required("VISIONFLOW_AUTH_AUDIENCE"),
            key_id=_required("VISIONFLOW_AUTH_KEY_ID"),
            private_key_pem=private_key_pem,
            access_token_ttl_seconds=ttl_seconds,
        )


class Rs256AccessTokenSigner:
    """Signs short-lived, audience-bound access tokens and exposes a public JWKS."""

    def __init__(self, settings: InternalAuthSettings, *, clock: Callable[[], float] = time.time) -> None:
        self._settings = settings
        self._clock = clock
        self._private_key = _load_rsa_private_key(settings.private_key_pem)

    def issue(self, *, subject: str, session_id: str, extra_claims: dict[str, Any] | None = None) -> str:
        if not subject.strip() or not session_id.strip():
            raise ValueError("subject and session_id are required")
        now = int(self._clock())
        claims: dict[str, Any] = {
            "iss": self._settings.issuer,
            "aud": self._settings.audience,
            "sub": subject,
            "sid": session_id,
            "iat": now,
            "nbf": now,
            "exp": now + self._settings.access_token_ttl_seconds,
            "jti": _token_id(now, subject, session_id),
            "token_use": "access",
        }
        if extra_claims:
            forbidden = set(extra_claims).intersection(claims)
            if forbidden:
                raise ValueError(f"Reserved token claims may not be overwritten: {sorted(forbidden)}")
            claims.update(extra_claims)
        return jwt.encode(
            claims,
            self._private_key,
            algorithm="RS256",
            headers={"kid": self._settings.key_id, "typ": "JWT"},
        )

    def jwks(self) -> dict[str, list[dict[str, Any]]]:
        public_jwk = jwt.algorithms.RSAAlgorithm.to_jwk(self._private_key.public_key(), as_dict=True)
        public_jwk.update({"kid": self._settings.key_id, "use": "sig", "alg": "RS256"})
        return {"keys": [public_jwk]}


class InternalAccessTokenVerifier:
    """Verifies only VisionFlow-issued access tokens; never accepts refresh tokens."""

    def __init__(self, settings: InternalAuthSettings) -> None:
        self._settings = settings
        self._public_key = _load_rsa_private_key(settings.private_key_pem).public_key()

    def verify(self, encoded: str) -> dict[str, Any]:
        try:
            claims = jwt.decode(
                encoded,
                self._public_key,
                algorithms=["RS256"],
                audience=self._settings.audience,
                issuer=self._settings.issuer,
                options={"require": ["exp", "iat", "sub", "sid", "token_use"]},
            )
        except jwt.PyJWTError as exc:
            raise PermissionError("internal access token is invalid") from exc
        if claims.get("token_use") != "access":
            raise PermissionError("token is not an access token")
        return claims


def _token_id(now: int, subject: str, session_id: str) -> str:
    # JWT IDs must not collide if an operator signs in multiple times in a second.
    # They are audit identifiers only, never bearer credentials.
    del now, subject, session_id
    return secrets.token_urlsafe(24)


def _load_rsa_private_key(pem: bytes) -> RSAPrivateKey:
    try:
        key = serialization.load_pem_private_key(pem, password=None)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError("VISIONFLOW_AUTH_PRIVATE_KEY_PEM_BASE64 must contain an unencrypted RSA private key") from exc
    if not isinstance(key, RSAPrivateKey):
        raise ConfigurationError("VISIONFLOW_AUTH_PRIVATE_KEY_PEM_BASE64 must contain an RSA private key")
    return key


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value or not value.strip():
        raise ConfigurationError(f"{name} must be configured")
    return value.strip()


def _https_url(name: str) -> str:
    value = _required(name)
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ConfigurationError(f"{name} must use an HTTPS URL")
    return value
