"""Versioned, backwards-compatible contract for translation and dubbing jobs.

The renderer still accepts legacy flat fields.  This module is the boundary that
turns them into a durable workflow package, so new callers do not need to know
about temporary paths or SEO-provider-specific response shapes.
"""
from __future__ import annotations

from typing import Any


DUBBING_PACKAGE_VERSION = "dubbing-workflow-package/v1"


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def legacy_seo_to_publish_metadata(seo: object) -> dict[str, Any]:
    """Map old dubbing SEO output into the canonical publisher contract.

    No branding, CTA or hashtags are invented here; the resolver remains the
    only place that chooses precedence for publishing.
    """
    raw = seo if isinstance(seo, dict) else {}
    hashtags = raw.get("hashtags") if isinstance(raw.get("hashtags"), list) else []
    tags = raw.get("tags") if isinstance(raw.get("tags"), list) else []
    description = _text(raw.get("caption_seo")) or _text(raw.get("description"))
    youtube = {
        key: value
        for key, value in {
            "title": _text(raw.get("title")),
            "description": description,
            "hashtags": hashtags,
            "tags": tags,
            "pinned_comment": _text(raw.get("pinned_comment")),
        }.items()
        if value not in (None, [])
    }
    return {"youtube": youtube} if youtube else {}


def build_dubbing_workflow_package(
    metadata: object,
    *,
    source_asset_id: str | None = None,
) -> dict[str, Any]:
    """Normalize a dispatch payload without discarding legacy compatibility."""
    legacy = dict(metadata) if isinstance(metadata, dict) else {}
    source_asset_id = source_asset_id or _text(legacy.get("source_asset_id"))
    package: dict[str, Any] = {
        "version": DUBBING_PACKAGE_VERSION,
        "source": {
            "asset_id": source_asset_id,
            "kind": "source_video",
            "status": "READY" if source_asset_id else "LEGACY_PENDING_IMPORT",
        },
        "translation": {
            "mode": "faithful",
            "timeline": [],
            "adapted_timeline": [],
            "source_language": legacy.get("source_language") or "auto",
            "target_language": legacy.get("target_language") or "vi",
        },
        "dubbing": {
            "voice_code": legacy.get("voice_code") or "edge-nam-minh",
            "voice_gender": legacy.get("voice_gender") or "female",
            "target_language": legacy.get("target_language") or "auto",
            "timing_qc": {"status": "PENDING", "segments": []},
        },
        "quality": {"state": "PENDING", "notes": []},
        "enable_narration_cta": bool(legacy.get("enable_narration_cta", False)),
        "enable_seamless_loop_adaptation": bool(legacy.get("enable_seamless_loop_adaptation", False)),
        "legacy_job_metadata": legacy,
    }
    publish_metadata = legacy_seo_to_publish_metadata(legacy.get("seo") or legacy.get("seo_tags_metadata"))
    if publish_metadata:
        package["publish_metadata"] = publish_metadata
    return package

