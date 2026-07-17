"""
TTS Providers Package
=====================
Registry trung tâm của tất cả TTS Strategy implementations.

Để thêm provider mới (vd: Google Cloud TTS, Azure Neural):
  1. Tạo file mới: worker/services/tts_providers/google_tts_provider.py
  2. Kế thừa TTSProvider và implement synthesize()
  3. Thêm 1 dòng vào TTS_PROVIDER_REGISTRY bên dưới
  → Không cần sửa bất kỳ file nào khác (OCP compliant)
"""
from __future__ import annotations

from worker.services.tts_providers.base import TTSProvider


def _build_registry() -> dict:
    """
    Lazy-load provider classes để tránh ImportError khi optional dependencies
    (edge_tts, requests) chưa được cài đặt trong môi trường hiện tại.
    """
    registry: dict = {}
    try:
        from worker.services.tts_providers.edge_tts_provider import EdgeTTSProvider
        registry["edge-tts"] = EdgeTTSProvider
    except ImportError:
        pass
    try:
        from worker.services.tts_providers.elevenlabs_provider import ElevenLabsProvider
        registry["elevenlabs"] = ElevenLabsProvider
    except ImportError:
        pass
    try:
        from worker.services.tts_providers.fptai_provider import FPTAIProvider
        registry["fptai"] = FPTAIProvider
    except ImportError:
        pass
    return registry


# ── Registry: source_name → Provider class ────────────────────────────────────
TTS_PROVIDER_REGISTRY: dict[str, type[TTSProvider]] = _build_registry()

__all__ = [
    "TTSProvider",
    "TTS_PROVIDER_REGISTRY",
]
