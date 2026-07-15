import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.core.config import ConfigurationError  # noqa: E402
from app.core.oidc import OidcSettings  # noqa: E402


class OidcSettingsTests(unittest.TestCase):
    def test_reads_a_strict_https_oidc_configuration(self) -> None:
        values = {
            "OIDC_ISSUER": "https://identity.example.com/",
            "OIDC_AUDIENCE": "visionflow-control-plane",
            "OIDC_JWKS_URL": "https://identity.example.com/.well-known/jwks.json",
            "OIDC_ALLOWED_ALGORITHMS": "RS256,ES256",
        }
        with patch.dict(os.environ, values, clear=True):
            settings = OidcSettings.from_env()

        self.assertEqual(("RS256", "ES256"), settings.allowed_algorithms)

    def test_rejects_non_https_jwks_url(self) -> None:
        values = {
            "OIDC_ISSUER": "https://identity.example.com/",
            "OIDC_AUDIENCE": "visionflow-control-plane",
            "OIDC_JWKS_URL": "http://identity.example.com/jwks.json",
        }
        with patch.dict(os.environ, values, clear=True):
            with self.assertRaisesRegex(ConfigurationError, "HTTPS"):
                OidcSettings.from_env()

    def test_rejects_symmetric_or_unsigned_algorithms(self) -> None:
        values = {
            "OIDC_ISSUER": "https://identity.example.com/",
            "OIDC_AUDIENCE": "visionflow-control-plane",
            "OIDC_JWKS_URL": "https://identity.example.com/jwks.json",
            "OIDC_ALLOWED_ALGORITHMS": "HS256,none",
        }
        with patch.dict(os.environ, values, clear=True):
            with self.assertRaisesRegex(ConfigurationError, "RS256"):
                OidcSettings.from_env()
