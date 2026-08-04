"""
Credential Vault Fetcher
========================
Khi khởi động, worker tự động gọi Control Plane API để fetch tất cả
API keys đã được lưu trong Credential Vault (Gemini, Groq, OpenRouter, v.v.)
và inject vào config module + biến môi trường để LLMService sử dụng ngay.

Thiết kế:
- Không crash nếu fetch thất bại (dùng keys từ env như cũ)
- Bổ sung keys từ vault VÀO TRÊN CÙNG (ưu tiên hơn env keys)
- Dedup tự động (tránh dùng key trùng lặp)
- Log rõ ràng bao nhiêu keys đã được nạp
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

# Thêm workspace root vào path nếu cần
WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))


def _get_worker_jwt() -> Optional[str]:
    """
    Lấy JWT token để xác thực với Control Plane dưới danh nghĩa 'worker'.
    
    Thứ tự ưu tiên:
    1. VISIONFLOW_WORKER_JWT env var (nếu đã có sẵn JWT)
    2. OAuth2 client credentials flow dùng VISIONFLOW_WORKER_CLIENT_ID
       + VISIONFLOW_WORKER_CLIENT_SECRET (cách worker thường dùng)
    """
    import urllib.request
    import urllib.parse
    import json

    # Ưu tiên 1: JWT có sẵn trực tiếp
    jwt = os.getenv("VISIONFLOW_WORKER_JWT", "").strip()
    if jwt:
        return jwt

    # Ưu tiên 2: OAuth2 client credentials flow
    client_id = os.getenv("VISIONFLOW_WORKER_CLIENT_ID", "").strip()
    client_secret = os.getenv("VISIONFLOW_WORKER_CLIENT_SECRET", "").strip()
    control_plane_url = os.getenv(
        "VISIONFLOW_CONTROL_PLANE_URL",
        "https://visionflow-control-plane-free.onrender.com/api/v1",
    )

    if not client_id or not client_secret:
        return None

    token_url = os.getenv(
        "VISIONFLOW_TOKEN_URL",
        f"{control_plane_url.rstrip('/')}/auth/token",
    )

    try:
        payload = urllib.parse.urlencode({
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "audience": os.getenv("VISIONFLOW_AUTH_AUDIENCE", "visionflow-control-plane"),
            "scope": "credential:resolve",
        }).encode()
        req = urllib.request.Request(
            token_url,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            access_token = data.get("access_token", "").strip()
            if access_token:
                print(f"[CredentialFetcher] 🔐 Worker JWT obtained via OAuth2 client credentials.")
                return access_token
    except Exception as e:
        print(f"[CredentialFetcher] ⚠️  Could not obtain worker JWT via OAuth2: {e}")

    return None


def _fetch_credentials_from_vault(
    control_plane_url: str,
    organization_id: str,
    provider: str,
    worker_jwt: str,
) -> list[str]:
    """Gọi endpoint /provider-credentials/{provider}/resolve và trả về list secrets."""
    import urllib.request
    import urllib.error
    import json

    url = f"{control_plane_url.rstrip('/')}/organizations/{organization_id}/provider-credentials/{provider}/resolve"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {worker_jwt}",
            "Content-Type": "application/json",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            # Trả về danh sách secrets theo thứ tự priority
            return [item["secret"] for item in data if item.get("secret")]
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace") if e.fp else ""
        print(f"[CredentialFetcher] ⚠️  HTTP {e.code} fetching {provider}: {body[:200]}")
        return []
    except Exception as e:
        print(f"[CredentialFetcher] ⚠️  Error fetching {provider}: {e}")
        return []


def bootstrap_credentials_from_vault() -> None:
    """
    Entry point chính: fetch tất cả providers từ Credential Vault,
    bổ sung vào config và biến môi trường để LLMService tự nhận.
    """
    control_plane_url = os.getenv(
        "VISIONFLOW_CONTROL_PLANE_URL",
        "https://visionflow-control-plane-free.onrender.com/api/v1",
    )
    organization_id = os.getenv(
        "VISIONFLOW_ORGANIZATION_ID",
        "7b91598c-6c3e-4e5d-8247-d3efa203984a",
    )
    worker_jwt = _get_worker_jwt()

    if not worker_jwt:
        print(
            "[CredentialFetcher] ⚠️  VISIONFLOW_WORKER_JWT not set. "
            "Skipping Credential Vault fetch — using env keys only."
        )
        return

    print(f"[CredentialFetcher] 🔑 Fetching API keys from Credential Vault for org={organization_id}...")

    # -------------------------------------------------------
    # 1. Fetch Gemini keys
    # -------------------------------------------------------
    vault_gemini_keys = _fetch_credentials_from_vault(
        control_plane_url, organization_id, "gemini", worker_jwt
    )

    if vault_gemini_keys:
        import worker.config as cfg

        # Merge: vault keys trước (ưu tiên cao hơn), rồi env keys ở sau
        existing_env_keys: list[str] = list(cfg.GEMINI_API_KEYS)
        merged: list[str] = []
        seen: set[str] = set()
        for k in vault_gemini_keys + existing_env_keys:
            if k not in seen:
                merged.append(k)
                seen.add(k)

        # Patch config module trực tiếp (module-level list)
        cfg.GEMINI_API_KEYS.clear()
        cfg.GEMINI_API_KEYS.extend(merged)

        # Cập nhật biến môi trường để các subprocess hoặc import sau cũng nhận được
        os.environ["GEMINI_API_KEYS"] = ",".join(merged)
        if merged:
            os.environ["GEMINI_API_KEY"] = merged[0]

        print(
            f"[CredentialFetcher] ✅ Gemini: {len(vault_gemini_keys)} keys from Vault "
            f"+ {len(existing_env_keys)} from env = {len(merged)} total unique keys loaded."
        )
        # Ẩn giá trị key, chỉ log prefix
        for i, k in enumerate(merged):
            print(f"  [{i+1}] {k[:10]}...{k[-4:]} (priority {i+1})")
    else:
        print(
            f"[CredentialFetcher] ℹ️  No active Gemini credentials found in Vault. "
            f"Using {len(os.getenv('GEMINI_API_KEYS','').split(','))} key(s) from env."
        )

    # -------------------------------------------------------
    # 2. Fetch Groq key (nếu chưa có từ env)
    # -------------------------------------------------------
    if not os.getenv("GROQ_API_KEY", "").strip():
        vault_groq_keys = _fetch_credentials_from_vault(
            control_plane_url, organization_id, "groq", worker_jwt
        )
        if vault_groq_keys:
            os.environ["GROQ_API_KEY"] = vault_groq_keys[0]
            import worker.config as cfg
            cfg.GROQ_API_KEY = vault_groq_keys[0]
            print(f"[CredentialFetcher] ✅ Groq: 1 key loaded from Vault.")

    # -------------------------------------------------------
    # 3. Fetch OpenRouter key (nếu chưa có từ env)
    # -------------------------------------------------------
    if not os.getenv("OPENROUTER_API_KEY", "").strip():
        vault_or_keys = _fetch_credentials_from_vault(
            control_plane_url, organization_id, "openrouter", worker_jwt
        )
        if vault_or_keys:
            os.environ["OPENROUTER_API_KEY"] = vault_or_keys[0]
            import worker.config as cfg
            cfg.OPENROUTER_API_KEY = vault_or_keys[0]
            print(f"[CredentialFetcher] ✅ OpenRouter: 1 key loaded from Vault.")

    # -------------------------------------------------------
    # 4. Patch LLMService instance nếu đã được khởi tạo trước đó
    #    (trường hợp module bị import trước khi bootstrap)
    # -------------------------------------------------------
    try:
        from worker.services.llm_service import LLMService
        import worker.config as cfg
        # Cập nhật instance đang tồn tại trong bộ nhớ (nếu có)
        for module_name, module_obj in sys.modules.items():
            if hasattr(module_obj, "llm_service") and isinstance(
                getattr(module_obj, "llm_service", None), LLMService
            ):
                module_obj.llm_service.gemini_keys = list(cfg.GEMINI_API_KEYS)
                module_obj.llm_service.groq_key = cfg.GROQ_API_KEY
                module_obj.llm_service.openrouter_key = cfg.OPENROUTER_API_KEY
                module_obj.llm_service.api_available = (
                    len(cfg.GEMINI_API_KEYS) > 0
                    or bool(cfg.GROQ_API_KEY)
                    or bool(cfg.OPENROUTER_API_KEY)
                )
                print(f"[CredentialFetcher] 🔄 Patched live LLMService instance in '{module_name}'.")
    except Exception as patch_err:
        print(f"[CredentialFetcher] (non-fatal) Could not patch LLMService instance: {patch_err}")

    print("[CredentialFetcher] 🎉 Credential bootstrap complete.\n")
