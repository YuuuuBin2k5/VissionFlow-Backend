import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa


SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.core.oidc import OidcSettings, OidcTokenVerifier  # noqa: E402


class FakeJwksClient:
    def __init__(self, public_key: object) -> None:
        self._public_key = public_key

    def get_signing_key_from_jwt(self, encoded_token: str) -> SimpleNamespace:
        return SimpleNamespace(key=self._public_key)


class OidcTokenVerifierTests(unittest.TestCase):
    def test_verifies_signature_issuer_audience_and_required_claims(self) -> None:
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        now = datetime.now(UTC)
        encoded_token = jwt.encode(
            {
                "sub": "oidc|visionflow-admin",
                "iss": "https://identity.example.com/",
                "aud": "visionflow-control-plane",
                "iat": now,
                "exp": now + timedelta(minutes=5),
                "email": "admin@example.com",
                "name": "VisionFlow Admin",
            },
            private_key,
            algorithm="RS256",
        )
        settings = OidcSettings(
            issuer="https://identity.example.com/",
            audience="visionflow-control-plane",
            jwks_url="https://identity.example.com/.well-known/jwks.json",
            allowed_algorithms=("RS256",),
        )

        with patch("app.core.oidc._get_jwks_client", return_value=FakeJwksClient(private_key.public_key())):
            identity = OidcTokenVerifier(settings).verify(encoded_token)

        self.assertEqual("oidc|visionflow-admin", identity.subject)
        self.assertEqual("admin@example.com", identity.email)
