from __future__ import annotations

import base64

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.config import ConfigurationError
from app.core.internal_tokens import InternalAuthSettings, Rs256AccessTokenSigner
from app.core.passwords import Argon2idPasswordHasher, PasswordPolicyError


def test_argon2id_hashes_and_verifies_passwords() -> None:
    hasher = Argon2idPasswordHasher(memory_cost_kib=8_192, time_cost=1)

    encoded = hasher.hash("a secure VisionFlow password")

    assert encoded.startswith("$argon2id$")
    assert hasher.verify(encoded, "a secure VisionFlow password") is True
    assert hasher.verify(encoded, "wrong password") is False
    assert hasher.verify("$argon2i$v=19$invalid", "a secure VisionFlow password") is False


def test_argon2id_rejects_short_password() -> None:
    with pytest.raises(PasswordPolicyError, match="at least 12"):
        Argon2idPasswordHasher().hash("too-short")


def test_rs256_token_and_jwks_are_public_key_verifiable(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_auth_env(monkeypatch)
    signer = Rs256AccessTokenSigner(InternalAuthSettings.from_env(), clock=lambda: 1_700_000_000)

    encoded = signer.issue(subject="user-42", session_id="session-99", extra_claims={"email": "a@example.com"})
    jwk = signer.jwks()["keys"][0]
    public_key = jwt.algorithms.RSAAlgorithm.from_jwk(jwk)
    decoded = jwt.decode(
        encoded,
        public_key,
        algorithms=["RS256"],
        audience="visionflow-control-plane",
        issuer="https://api.visionflow.example",
        options={"verify_exp": False},
    )

    assert jwt.get_unverified_header(encoded)["kid"] == "visionflow-2026-01"
    assert "d" not in jwk
    assert decoded["sub"] == "user-42"
    assert decoded["sid"] == "session-99"
    assert decoded["token_use"] == "access"
    assert decoded["exp"] == 1_700_000_900


def test_internal_auth_settings_reject_non_https_issuer(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_auth_env(monkeypatch)
    monkeypatch.setenv("VISIONFLOW_AUTH_ISSUER", "http://localhost:8000")

    with pytest.raises(ConfigurationError, match="HTTPS"):
        InternalAuthSettings.from_env()


def test_internal_auth_settings_rejects_short_lived_or_overlong_access_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_auth_env(monkeypatch)
    monkeypatch.setenv("VISIONFLOW_AUTH_ACCESS_TOKEN_TTL_SECONDS", "30")

    with pytest.raises(ConfigurationError, match="between 60 and 3600"):
        InternalAuthSettings.from_env()


def _set_auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    private_key = rsa.generate_private_key(public_exponent=65_537, key_size=2_048)
    pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    monkeypatch.setenv("VISIONFLOW_AUTH_PRIVATE_KEY_PEM_BASE64", base64.b64encode(pem).decode("ascii"))
    monkeypatch.setenv("VISIONFLOW_AUTH_ISSUER", "https://api.visionflow.example")
    monkeypatch.setenv("VISIONFLOW_AUTH_AUDIENCE", "visionflow-control-plane")
    monkeypatch.setenv("VISIONFLOW_AUTH_KEY_ID", "visionflow-2026-01")
    monkeypatch.setenv("VISIONFLOW_AUTH_ACCESS_TOKEN_TTL_SECONDS", "900")
