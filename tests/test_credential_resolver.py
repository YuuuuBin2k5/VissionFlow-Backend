import pytest
from unittest.mock import patch
from production.credential_resolver import (
    get_provider_keys,
    get_provider_key,
    get_gemini_api_key,
    get_gemini_api_keys,
    get_pexels_api_key,
    clear_credential_cache,
)


def test_credential_resolver_env_fallback():
    clear_credential_cache()
    with patch.dict("os.environ", {
        "GEMINI_API_KEYS": "env-gemini-1, env-gemini-2",
        "GEMINI_API_KEY": "env-gemini-single",
        "PEXELS_API_KEY": "env-pexels-key",
        "DIRECT_DATABASE_URL": "",
        "DATABASE_URL": "",
    }, clear=True):
        clear_credential_cache()
        gemini_keys = get_gemini_api_keys()
        assert "env-gemini-1" in gemini_keys
        assert "env-gemini-2" in gemini_keys
        assert "env-gemini-single" in gemini_keys

        primary_gemini = get_gemini_api_key()
        assert primary_gemini is not None
        assert primary_gemini in gemini_keys

        pexels_key = get_pexels_api_key()
        assert pexels_key == "env-pexels-key"


def test_credential_resolver_caching():
    clear_credential_cache()
    with patch.dict("os.environ", {
        "GEMINI_API_KEY": "initial-key",
        "DIRECT_DATABASE_URL": "",
        "DATABASE_URL": "",
    }, clear=True):
        clear_credential_cache()
        key1 = get_gemini_api_key()
        assert key1 == "initial-key"

        # Change env without clearing cache: should still return cached key1
        with patch.dict("os.environ", {"GEMINI_API_KEY": "changed-key"}, clear=True):
            key2 = get_gemini_api_key()
            assert key2 == "initial-key"

            # Clear cache: should now return changed-key
            clear_credential_cache()
            key3 = get_gemini_api_key()
            assert key3 == "changed-key"


def test_credential_resolver_empty_graceful():
    clear_credential_cache()
    with patch.dict("os.environ", {
        "GEMINI_API_KEYS": "",
        "GEMINI_API_KEY": "",
        "PEXELS_API_KEY": "",
        "DIRECT_DATABASE_URL": "",
        "DATABASE_URL": "",
    }, clear=True):
        clear_credential_cache()
        assert get_gemini_api_key() is None
        assert get_gemini_api_keys() == []
        assert get_pexels_api_key() is None
