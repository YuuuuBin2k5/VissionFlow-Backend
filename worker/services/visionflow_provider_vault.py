"""Load ordered provider keys into the isolated render-worker process only."""

from __future__ import annotations

import os
from typing import Protocol


class ProviderCredentialGateway(Protocol):
    def resolve_provider_credentials(self, provider: str, *, trace_id: str | None = None) -> list[dict]: ...


def hydrate_provider_environment(gateway: ProviderCredentialGateway) -> None:
    """Prefer Vault values while preserving legacy env fallback during migration."""
    mappings = {
        "gemini": "GEMINI_API_KEYS",
        "groq": "GROQ_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
        "pexels": "PEXELS_API_KEY",
        "pixabay": "PIXABAY_API_KEY",
        "coverr": "COVERR_API_KEY",
    }
    for provider, env_name in mappings.items():
        records = gateway.resolve_provider_credentials(provider)
        secrets = [str(record["secret"]).strip() for record in records if str(record.get("secret", "")).strip()]
        if not secrets:
            continue
        # Gemini has native multi-key fallback. Other adapters consume the
        # first ordered key until their provider-specific retry adapter lands.
        os.environ[env_name] = ",".join(secrets) if provider == "gemini" else secrets[0]
