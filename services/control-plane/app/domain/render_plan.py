"""Deterministic compilation of a locked Composition Studio snapshot.

Renderers consume this plan instead of directly interpreting mutable HTTP or
database payloads.  This keeps provider-specific strategies behind a stable,
typed boundary.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from app.domain.composition import CompositionValidationError, validate_composition_for_v1


class RenderPlanCompilationError(ValueError):
    """The supplied composition cannot become an authoritative render plan."""


@dataclass(frozen=True)
class RenderPlanEffect:
    key: str
    config: dict[str, Any]


@dataclass(frozen=True)
class RenderPlanKeyframe:
    property_key: str
    time_ms: int
    value: dict[str, Any]
    easing: str


@dataclass(frozen=True)
class RenderPlanClip:
    source_type: str
    source_ref: str
    timeline_start_ms: int
    duration_ms: int
    trim_in_ms: int
    transform: dict[str, Any]
    effects: tuple[RenderPlanEffect, ...]
    keyframes: tuple[RenderPlanKeyframe, ...]


@dataclass(frozen=True)
class RenderPlanTrack:
    position: int
    track_type: str
    name: str
    muted: bool
    locked: bool
    clips: tuple[RenderPlanClip, ...]


@dataclass(frozen=True)
class RenderPlan:
    workflow_run_id: str
    composition_version_id: str
    revision: int
    aspect_ratio: str
    canvas: dict[str, Any]
    duration_ms: int
    tracks: tuple[RenderPlanTrack, ...]
    fingerprint: str


def compile_render_plan(snapshot: Mapping[str, Any]) -> RenderPlan:
    """Compile one locked V1 composition revision into a canonical render plan."""

    if snapshot.get("state") != "locked":
        raise RenderPlanCompilationError("Only a locked composition version can be rendered")

    workflow_run_id = _required_string(snapshot, "workflow_run_id")
    composition_version_id = _required_string(snapshot, "version_id")
    revision = _required_positive_int(snapshot, "revision")
    aspect_ratio = _required_string(snapshot, "aspect_ratio")
    tracks = _mapping_sequence(snapshot.get("tracks"), "tracks")
    try:
        validate_composition_for_v1(aspect_ratio=aspect_ratio, tracks=tracks)
    except CompositionValidationError as exc:
        raise RenderPlanCompilationError(str(exc)) from exc

    canvas = _canvas(snapshot.get("canvas_config"), aspect_ratio)
    plan_tracks = tuple(_compile_track(track, position) for position, track in enumerate(tracks, start=1))
    duration_ms = max(
        (clip.timeline_start_ms + clip.duration_ms for track in plan_tracks for clip in track.clips),
        default=0,
    )
    if duration_ms == 0:
        raise RenderPlanCompilationError("Render plan needs at least one clip")

    canonical = {
        "workflow_run_id": workflow_run_id,
        "composition_version_id": composition_version_id,
        "revision": revision,
        "aspect_ratio": aspect_ratio,
        "canvas": canvas,
        "duration_ms": duration_ms,
        "tracks": [asdict(track) for track in plan_tracks],
    }
    fingerprint = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
    return RenderPlan(
        workflow_run_id=workflow_run_id,
        composition_version_id=composition_version_id,
        revision=revision,
        aspect_ratio=aspect_ratio,
        canvas=canvas,
        duration_ms=duration_ms,
        tracks=plan_tracks,
        fingerprint=fingerprint,
    )


def _compile_track(track: Mapping[str, Any], position: int) -> RenderPlanTrack:
    clips = _mapping_sequence(track.get("clips"), "clips")
    return RenderPlanTrack(
        position=position,
        track_type=_required_string(track, "track_type"),
        name=_required_string(track, "name"),
        muted=bool(track.get("muted", False)),
        locked=bool(track.get("locked", False)),
        clips=tuple(_compile_clip(clip) for clip in clips),
    )


def _compile_clip(clip: Mapping[str, Any]) -> RenderPlanClip:
    return RenderPlanClip(
        source_type=_required_string(clip, "source_type"),
        source_ref=_required_string(clip, "source_ref"),
        timeline_start_ms=_required_nonnegative_int(clip, "timeline_start_ms"),
        duration_ms=_required_positive_int(clip, "duration_ms"),
        trim_in_ms=_optional_nonnegative_int(clip.get("trim_in_ms"), "trim_in_ms"),
        transform=_mapping(clip.get("transform", {}), "transform"),
        effects=tuple(
            RenderPlanEffect(key=_required_string(effect, "effect_key"), config=_mapping(effect.get("config", {}), "effect config"))
            for effect in _mapping_sequence(clip.get("effects", []), "effects")
        ),
        keyframes=tuple(
            RenderPlanKeyframe(
                property_key=_required_string(keyframe, "property_key"),
                time_ms=_required_nonnegative_int(keyframe, "time_ms"),
                value=_mapping(keyframe.get("value", {}), "keyframe value"),
                easing=str(keyframe.get("easing", "linear")),
            )
            for keyframe in _mapping_sequence(clip.get("keyframes", []), "keyframes")
        ),
    )


def _canvas(value: object, aspect_ratio: str) -> dict[str, Any]:
    canvas = _mapping(value if value is not None else {}, "canvas_config")
    if aspect_ratio != "9:16":
        raise RenderPlanCompilationError("Only the 9:16 short-form canvas is supported in V1")
    width = canvas.get("width", 1080)
    height = canvas.get("height", 1920)
    if width != 1080 or height != 1920:
        raise RenderPlanCompilationError("V1 render plans require a 1080x1920 canvas")
    return {**canvas, "width": width, "height": height}


def _mapping_sequence(value: object, name: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise RenderPlanCompilationError(f"{name} must be a sequence")
    if not all(isinstance(item, Mapping) for item in value):
        raise RenderPlanCompilationError(f"{name} contains an invalid item")
    return list(value)


def _mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise RenderPlanCompilationError(f"{name} must be an object")
    return dict(value)


def _required_string(value: Mapping[str, Any], name: str) -> str:
    item = value.get(name)
    if not isinstance(item, str) or not item.strip():
        raise RenderPlanCompilationError(f"{name} must be a non-empty string")
    return item


def _required_positive_int(value: Mapping[str, Any], name: str) -> int:
    item = value.get(name)
    if not isinstance(item, int) or isinstance(item, bool) or item <= 0:
        raise RenderPlanCompilationError(f"{name} must be a positive integer")
    return item


def _required_nonnegative_int(value: Mapping[str, Any], name: str) -> int:
    item = value.get(name)
    if not isinstance(item, int) or isinstance(item, bool) or item < 0:
        raise RenderPlanCompilationError(f"{name} must be a non-negative integer")
    return item


def _optional_nonnegative_int(value: object, name: str) -> int:
    if value is None:
        return 0
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RenderPlanCompilationError(f"{name} must be a non-negative integer")
    return value
