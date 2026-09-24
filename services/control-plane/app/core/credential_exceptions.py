from __future__ import annotations

from typing import Optional


PROVIDER_DISPLAY_NAMES = {
    "gemini": "Google Gemini & Imagen 3",
    "google": "Google Gemini & Imagen 3",
    "pexels": "Pexels Stock Video",
    "elevenlabs": "ElevenLabs Voice AI",
    "fal": "Fal.ai Multi-Model Video",
    "groq": "Groq LLM",
    "openrouter": "OpenRouter AI",
    "runway": "Runway Gen-3",
    "kling": "Kling AI",
    "luma": "Luma Dream Machine",
}

PROVIDER_DOCS_URLS = {
    "gemini": "https://aistudio.google.com/app/apikey",
    "google": "https://aistudio.google.com/app/apikey",
    "pexels": "https://www.pexels.com/api/",
    "elevenlabs": "https://elevenlabs.io/app/speech-synthesis",
    "fal": "https://fal.ai/dashboard/keys",
    "groq": "https://console.groq.com/keys",
    "openrouter": "https://openrouter.ai/keys",
}


class MissingProviderCredentialError(Exception):
    """Raised when an enterprise feature requires an API key that is not in the Database Vault."""

    def __init__(
        self,
        provider: str,
        feature_name: str,
        docs_url: Optional[str] = None,
        detail: Optional[str] = None,
    ):
        self.provider = provider.lower()
        self.provider_display_name = PROVIDER_DISPLAY_NAMES.get(self.provider, provider.title())
        self.feature_name = feature_name
        self.docs_url = docs_url or PROVIDER_DOCS_URLS.get(self.provider, "https://aistudio.google.com/app/apikey")
        self.detail = detail or (
            f"Tính năng '{feature_name}' yêu cầu API Key của {self.provider_display_name}. "
            "Vui lòng cấu hình khóa trong Kho Khóa (Provider Vault) của tổ chức để kích hoạt."
        )
        super().__init__(self.detail)


class InvalidProviderCredentialError(Exception):
    """Raised when an API key is revoked, leaked, invalid, or rate-limited by the provider."""

    def __init__(
        self,
        provider: str,
        feature_name: str,
        detail: str,
        docs_url: Optional[str] = None,
    ):
        self.provider = provider.lower()
        self.provider_display_name = PROVIDER_DISPLAY_NAMES.get(self.provider, provider.title())
        self.feature_name = feature_name
        self.docs_url = docs_url or PROVIDER_DOCS_URLS.get(self.provider, "https://aistudio.google.com/app/apikey")
        self.detail = detail
        super().__init__(self.detail)
