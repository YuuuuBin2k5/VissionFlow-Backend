"""Canonical, provenance-aware publishing metadata resolution.

This module deliberately does not generate copy.  It selects the strongest
available metadata, validates its shape, and lets the caller invoke a legacy
generator only when a fallback is actually required.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any


MAX_GENERATED_HASHTAGS = 5
PLATFORMS = ("youtube", "tiktok", "instagram", "facebook")


@dataclass(frozen=True)
class MetadataIssue:
    code: str
    severity: str
    field: str
    message: str


@dataclass(frozen=True)
class ResolvedValue:
    value: Any
    source: str


@dataclass
class ResolvedPlatformMetadata:
    title: ResolvedValue | None = None
    description: ResolvedValue | None = None
    caption: ResolvedValue | None = None
    hashtags: ResolvedValue | None = None
    tags: ResolvedValue | None = None
    pinned_comment: ResolvedValue | None = None
    issues: list[MetadataIssue] = field(default_factory=list)


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _platform(metadata: object, platform: str) -> dict[str, Any]:
    return _as_dict(_as_dict(metadata).get(platform))


def normalize_hashtags(values: object, limit: int | None = None) -> list[str]:
    """Normalize, validate, and case-fold-dedupe hashtags without inventing any."""
    if not isinstance(values, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        if not isinstance(raw, str):
            continue
        tag = raw.strip()
        if not tag:
            continue
        tag = tag if tag.startswith("#") else f"#{tag}"
        body = tag[1:]
        if not body or any(ch.isspace() for ch in body):
            continue
        key = unicodedata.normalize("NFKC", body).casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(tag)
        if limit is not None and len(result) >= limit:
            break
    return result


def normalize_tags(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        if not isinstance(raw, str):
            continue
        tag = re.sub(r"\s+", " ", raw).strip()
        key = tag.casefold()
        if tag and key not in seen:
            seen.add(key)
            result.append(tag)
    return result


def _pick(field: str, user: dict[str, Any], content: dict[str, Any], fallback: object = None) -> ResolvedValue | None:
    for source, values in (("user", user), ("content_ai", content)):
        value = _text(values.get(field))
        if value is not None:
            return ResolvedValue(value, source)
    value = _text(fallback)
    return ResolvedValue(value, "generated_fallback") if value is not None else None


def _pick_list(field: str, user: dict[str, Any], content: dict[str, Any], fallback: object, generated: bool = False) -> ResolvedValue | None:
    for source, values in (("user", user), ("content_ai", content)):
        if isinstance(values.get(field), list):
            normalizer = normalize_tags if field == "tags" else normalize_hashtags
            return ResolvedValue(normalizer(values[field]), source)
    if isinstance(fallback, list):
        normalizer = normalize_tags if field == "tags" else normalize_hashtags
        limit = MAX_GENERATED_HASHTAGS if field == "hashtags" and generated else None
        return ResolvedValue(normalizer(fallback, limit) if field == "hashtags" else normalizer(fallback), "generated_fallback")
    return None


def resolve_publish_metadata(
    *,
    content_metadata: object = None,
    user_metadata: object = None,
    fallback: object = None,
    platform: str = "youtube",
) -> ResolvedPlatformMetadata:
    """Apply the single authority order: user > content AI > fallback > defaults."""
    if platform not in PLATFORMS:
        raise ValueError(f"Unsupported publish platform: {platform}")
    content = _platform(content_metadata, platform)
    user = _platform(user_metadata, platform)
    fallback_data = _platform(fallback, platform)
    result = ResolvedPlatformMetadata()
    result.title = _pick("title", user, content, fallback_data.get("title"))
    description_field = "description" if platform == "youtube" else "caption"
    chosen = _pick(description_field, user, content, fallback_data.get(description_field))
    if platform == "youtube":
        result.description = chosen
    else:
        result.caption = chosen
    result.hashtags = _pick_list("hashtags", user, content, fallback_data.get("hashtags"), generated=True)
    if platform == "youtube":
        result.tags = _pick_list("tags", user, content, fallback_data.get("tags"))
        result.pinned_comment = _pick("pinned_comment", user, content, fallback_data.get("pinned_comment"))
    for name, values in (("user", user), ("content_ai", content)):
        for field in ("description", "caption", "title"):
            if field in values and not isinstance(values[field], str):
                result.issues.append(MetadataIssue("DESCRIPTION_INVALID_TYPE" if field in ("description", "caption") else "TITLE_EMPTY", "error", field, f"{name} {field} must be a string"))
    if result.title is not None and not result.title.value.strip():
        result.issues.append(MetadataIssue("TITLE_EMPTY", "error", "title", "Title cannot be empty"))
    return result


def music_attribution_text(metadata: object) -> tuple[str | None, list[MetadataIssue]]:
    """Return only an attribution explicitly required by supplied license metadata."""
    music = _as_dict(metadata)
    if not music:
        return None, []
    if music.get("attribution_required") is True:
        text = _text(music.get("attribution_text"))
        if text:
            return text, []
        return None, [MetadataIssue("MISSING_REQUIRED_MUSIC_ATTRIBUTION", "warning", "music", "Attribution is required but attribution_text is missing")]
    return None, []


def append_required_attribution(description: str, music_metadata: object) -> tuple[str, list[MetadataIssue]]:
    attribution, issues = music_attribution_text(music_metadata)
    if attribution and attribution not in description:
        return f"{description.rstrip()}\n\n{attribution}", issues
    return description, issues
