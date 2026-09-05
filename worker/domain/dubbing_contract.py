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
            "mode": legacy.get("translation_mode") if legacy.get("translation_mode") in {"faithful", "localized_adaptation"} else "faithful",
            "timeline": [],
            "adapted_timeline": [],
        },
        "dubbing": {
            "voice_code": legacy.get("voice_code") or "edge-nam-minh",
            "voice_gender": legacy.get("voice_gender") or "female",
            "target_language": legacy.get("target_language") or "auto",
            "timing_qc": {"status": "PENDING", "segments": []},
        },
        "quality": {"state": "PENDING", "notes": []},
        "publish_metadata": legacy_seo_to_publish_metadata(legacy.get("seo")),
        # Story adaptation changes meaning, so it is deliberately opt-in.
        "enable_narration_cta": bool(legacy.get("enable_narration_cta", False)),
        "enable_seamless_loop_adaptation": bool(legacy.get("enable_seamless_loop_adaptation", False)),
    }
    return package


def record_timing_qc(timeline: object) -> dict[str, Any]:
    """Persist measured audio timing evidence; this function never estimates."""
    rows = timeline if isinstance(timeline, list) else []
    results: list[dict[str, Any]] = []
    drifts: list[int] = []
    tolerance_ms = 250
    for index, row in enumerate(rows):
        row = row if isinstance(row, dict) else {}
        target_ms = row.get("target_duration_ms")
        rendered_ms = row.get("rendered_audio_duration_ms")
        if not isinstance(target_ms, (int, float)) or not isinstance(rendered_ms, (int, float)):
            continue
        drift_ms = int(round(rendered_ms - target_ms))
        drifts.append(abs(drift_ms))
        results.append({"index": index, "target_duration_ms": int(round(target_ms)), "rendered_audio_duration_ms": int(round(rendered_ms)), "timing_drift_ms": drift_ms})
    over_tolerance = sum(1 for value in drifts if value > tolerance_ms)
    qc_status = "NOT_AVAILABLE" if not results else (
        "INCOMPLETE" if len(results) != len(rows) else
        "REVIEW_REQUIRED" if over_tolerance else "PASSED"
    )
    return {
        "status": qc_status,
        "segments": results,
        "max_timing_drift_ms": max(drifts, default=0),
        "average_timing_drift_ms": round(sum(drifts) / len(drifts), 1) if drifts else 0,
        "segments_over_tolerance": over_tolerance,
        "tolerance_ms": tolerance_ms,
    }


def select_render_text(segment: object, translation_mode: str = "faithful") -> str:
    """Faithful text remains authoritative; adaptation is an opt-in overlay."""
    row = segment if isinstance(segment, dict) else {}
    faithful = _text(row.get("translated_text")) or ""
    adapted = _text(row.get("adapted_text"))
    return adapted if translation_mode == "localized_adaptation" and adapted else faithful
