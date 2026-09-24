"""
Unified Credential Resolver for VisionFlow Auto Production.

Resolves active provider credentials (Gemini, Pexels, Groq, etc.) with priority:
1. Active record in Database `provider_credentials` table (decrypted via Fernet/ProviderCredentialCipher).
2. Environment variables fallback (GEMINI_API_KEYS, GEMINI_API_KEY, PEXELS_API_KEY, etc.).

Features:
- In-memory caching with 30s TTL to prevent DB query storming across multi-scene rendering.
- Graceful degradation: never crashes if DB is unreachable or key decryption fails.
- Hot-reload: picking up new credentials added on Web Console (/credential_vault) automatically.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import time
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("visionflow.production.credential_resolver")

# In-memory cache: provider -> (expiry_timestamp, list_of_decrypted_keys)
_CACHE: Dict[str, Tuple[float, List[str]]] = {}
_CACHE_TTL_SECONDS = 30.0

DEFAULT_MASTER_KEY = "7c82c3c7ef23758b9ea79dfa58f4a3e3c66baea5c704f47bb920b7efcfce38b4"


def _build_fernet_ciphers() -> list[Any]:
    """Builds Fernet ciphers from configured and default master encryption keys."""
    ciphers = []
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        return ciphers

    # Try official ProviderCredentialCipher first
    try:
        from app.core.credential_cipher import ProviderCredentialCipher
        ciphers.append(ProviderCredentialCipher.from_env()._fernet)
    except Exception:
        pass

    raw_candidates = [
        os.getenv("VISIONFLOW_CREDENTIAL_ENCRYPTION_KEY", "").strip(),
        DEFAULT_MASTER_KEY,
    ]
    seen_keys = set()

    for candidate in raw_candidates:
        if not candidate:
            continue
        try:
            raw = candidate.encode("utf-8")
            try:
                material = base64.urlsafe_b64decode(candidate + "===")
            except Exception:
                material = raw
            digest = hashlib.sha256(material if len(material) >= 32 else raw).digest()
            fernet_key = base64.urlsafe_b64encode(digest)
            if fernet_key not in seen_keys:
                seen_keys.add(fernet_key)
                ciphers.append(Fernet(fernet_key))
        except Exception:
            pass

    return ciphers


def _decrypt_ciphertext(ciphertext: str, ciphers: list[Any]) -> Optional[str]:
    """Attempts decryption across all available ciphers."""
    if not ciphertext or not ciphers:
        return None
    for cipher in ciphers:
        try:
            return cipher.decrypt(ciphertext.encode("ascii")).decode("utf-8").strip()
        except Exception:
            continue
    return None


def _resolve_from_db(provider: str, organization_id: Optional[str] = None) -> List[str]:
    """Queries active credentials from PostgreSQL provider_credentials table."""
    if os.getenv("VISIONFLOW_USE_DEV_REPOSITORIES") == "1":
        return []

    ciphers = _build_fernet_ciphers()
    if not ciphers:
        return []

    keys: List[str] = []

    # 1. Primary path: Use SQLAlchemy engine (guaranteed to work across Tailscale/proxy setups)
    try:
        from app.infrastructure.database import get_engine
        from sqlalchemy import text
        engine = get_engine()
        with engine.connect() as conn:
            provider_list = [provider.lower()]
            if provider.lower() == "gemini":
                provider_list.append("google")

            if organization_id:
                stmt = text(
                    "SELECT secret_ciphertext FROM provider_credentials "
                    "WHERE provider = ANY(:providers) AND status = 'active' AND organization_id = :org_id "
                    "ORDER BY priority ASC, created_at ASC"
                )
                rows = conn.execute(stmt, {"providers": provider_list, "org_id": organization_id}).fetchall()
            else:
                stmt = text(
                    "SELECT secret_ciphertext FROM provider_credentials "
                    "WHERE provider = ANY(:providers) AND status = 'active' "
                    "ORDER BY priority ASC, created_at ASC"
                )
                rows = conn.execute(stmt, {"providers": provider_list}).fetchall()

            for r in rows:
                ct = r[0]
                decrypted = _decrypt_ciphertext(ct, ciphers)
                if decrypted and decrypted not in keys:
                    keys.append(decrypted)
        if keys:
            return keys
    except Exception as sqla_err:
        logger.debug(f"[CredentialResolver] SQLAlchemy query for {provider} note: {sqla_err}")

    # 2. Secondary fallback: direct psycopg connection if raw db_url is provided
    db_url = os.getenv("DIRECT_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not db_url:
        return keys

    conn = None
    try:
        conn_str = db_url.replace("postgresql+psycopg://", "postgresql://")
        try:
            import psycopg2
            conn = psycopg2.connect(conn_str, connect_timeout=5)
        except ImportError:
            import psycopg
            conn = psycopg.connect(conn_str, timeout=5)

        with conn.cursor() as cur:
            if organization_id:
                cur.execute(
                    "SELECT secret_ciphertext FROM provider_credentials "
                    "WHERE provider IN ('gemini', 'google') AND status = 'active' AND organization_id = %s "
                    "ORDER BY priority ASC, created_at ASC",
                    (organization_id,),
                )
            else:
                cur.execute(
                    "SELECT secret_ciphertext FROM provider_credentials "
                    "WHERE provider IN ('gemini', 'google') AND status = 'active' "
                    "ORDER BY priority ASC, created_at ASC"
                )

            rows = cur.fetchall()
            for r in rows:
                ct = r[0]
                decrypted = _decrypt_ciphertext(ct, ciphers)
                if decrypted and decrypted not in keys:
                    keys.append(decrypted)
    except Exception as exc:
        logger.debug(f"[CredentialResolver] Direct DB query for {provider} skipped or failed: {exc}")
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    return keys


def _resolve_from_env(provider: str) -> List[str]:
    """Fallback resolution from environment variables."""
    keys: List[str] = []
    prov = provider.lower()

    if prov == "gemini":
        raw_multi = os.getenv("GEMINI_API_KEYS", "")
        if raw_multi:
            for k in raw_multi.replace('"', '').split(","):
                k_clean = k.strip()
                if k_clean and k_clean not in keys:
                    keys.append(k_clean)
        single = os.getenv("GEMINI_API_KEY", "").strip()
        if single and single not in keys:
            keys.insert(0, single)
    elif prov == "pexels":
        val = os.getenv("PEXELS_API_KEY", "").strip()
        if val:
            keys.append(val)
    elif prov == "groq":
        val = os.getenv("GROQ_API_KEY", "").strip()
        if val:
            keys.append(val)
    elif prov == "openrouter":
        val = os.getenv("OPENROUTER_API_KEY", "").strip()
        if val:
            keys.append(val)
    elif prov == "fal":
        val = (os.getenv("FAL_KEY") or os.getenv("FAL_API_KEY") or "").strip()
        if val:
            keys.append(val)

    return keys


def get_provider_keys(
    provider: str,
    organization_id: Optional[str] = None,
    bypass_cache: bool = False,
) -> List[str]:
    """
    Returns active credentials for the given provider:
    1. Active records from Database provider_credentials table (priority 1)
    2. Environment variable fallbacks only if DB has no keys
    """
    cache_key = f"{provider.lower()}:{organization_id or 'all'}"
    now = time.time()

    if not bypass_cache and cache_key in _CACHE:
        expiry, cached_keys = _CACHE[cache_key]
        if now < expiry:
            return list(cached_keys)

    # 1. DB Vault keys (ưu tiên hàng đầu từ database)
    db_keys = _resolve_from_db(provider, organization_id)
    if db_keys:
        _CACHE[cache_key] = (now + _CACHE_TTL_SECONDS, db_keys)
        return list(db_keys)

    # 2. Env keys (chỉ fallback nếu database hoàn toàn không có key)
    env_keys = _resolve_from_env(provider)
    _CACHE[cache_key] = (now + _CACHE_TTL_SECONDS, env_keys)
    return list(env_keys)


def get_provider_key(
    provider: str,
    organization_id: Optional[str] = None,
    bypass_cache: bool = False,
) -> Optional[str]:
    """Returns the primary active key for the given provider (highest priority)."""
    keys = get_provider_keys(provider, organization_id, bypass_cache=bypass_cache)
    return keys[0] if keys else None


def get_gemini_api_key(organization_id: Optional[str] = None) -> Optional[str]:
    """Convenience helper for primary Gemini API key."""
    return get_provider_key("gemini", organization_id)


def get_gemini_api_keys(organization_id: Optional[str] = None) -> List[str]:
    """Convenience helper for all active Gemini API keys (for model failover)."""
    return get_provider_keys("gemini", organization_id)


def get_pexels_api_key(organization_id: Optional[str] = None) -> Optional[str]:
    """Convenience helper for primary Pexels API key."""
    return get_provider_key("pexels", organization_id)


def require_provider_key(
    provider: str,
    feature_name: str,
    organization_id: Optional[str] = None,
) -> str:
    """
    Returns an active key for the provider, or raises MissingProviderCredentialError if none exists.
    """
    key = get_provider_key(provider, organization_id)
    if not key:
        try:
            from app.core.credential_exceptions import MissingProviderCredentialError
            raise MissingProviderCredentialError(provider=provider, feature_name=feature_name)
        except ImportError:
            raise ValueError(f"Thiếu API Key cho nhà cung cấp {provider} (Tính năng: {feature_name})")
    return key


def clear_credential_cache() -> None:
    """Manually invalidates the in-memory credential cache."""
    _CACHE.clear()
