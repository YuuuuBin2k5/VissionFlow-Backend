"""Typed, deterministic render input compiled from a locked composition."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


class RenderPlanValidationError(ValueError):
    """A locked composition cannot be represented by the V1 renderer."""


@dataclass(frozen=True)
class EffectDefinition:
    key: str
    track_types: frozenset[str]
    supports_config: bool = False


EFFECT_REGISTRY: dict[str, EffectDefinition] = {
    "cinematic_push": EffectDefinition("cinematic_push", frozenset({"video"})),
    "impact_shake": EffectDefinition("impact_shake", frozenset({"video"})),
    "caption_pop": EffectDefinition("caption_pop", frozenset({"caption", "video"})),
    "soft_glow": EffectDefinition("soft_glow", frozenset({"video", "overlay"})),
    "motion_blur": EffectDefinition("motion_blur", frozenset({"video", "overlay"})),
}


@dataclass(frozen=True)
class RenderPlanEffect:
    key: str

    def to_payload(self) -> dict[str, str]:
        return {"key": self.key}


@dataclass(frozen=True)
class RenderPlanKeyframe:
    property_key: str
    time_ms: int
    value: float
    easing: str

    def to_payload(self) -> dict[str, object]:
        return {
            "property_key": self.property_key,
            "time_ms": self.time_ms,
            "value": self.value,
            "easing": self.easing,
        }


@dataclass(frozen=True)
class RenderPlanClip:
    source_type: str
    source_ref: str
    timeline_start_ms: int
    duration_ms: int
    trim_in_ms: int
    transform: tuple[tuple[str, object], ...]
    effects: tuple[RenderPlanEffect, ...]
    keyframes: tuple[RenderPlanKeyframe, ...]

    def to_payload(self) -> dict[str, object]:
        return {
            "source_type": self.source_type,
            "source_ref": self.source_ref,
            "timeline_start_ms": self.timeline_start_ms,
            "duration_ms": self.duration_ms,
            "trim_in_ms": self.trim_in_ms,
            "transform": dict(self.transform),
            "effects": [effect.to_payload() for effect in self.effects],
            "keyframes": [keyframe.to_payload() for keyframe in self.keyframes],
        }


@dataclass(frozen=True)
class RenderPlanTrack:
    track_type: str
    name: str
    muted: bool
    clips: tuple[RenderPlanClip, ...]

    def to_payload(self) -> dict[str, object]:
        return {
            "track_type": self.track_type,
            "name": self.name,
            "muted": self.muted,
            "clips": [clip.to_payload() for clip in self.clips],
        }


@dataclass(frozen=True)
class CompositionRenderPlan:
    workflow_run_id: str
    composition_version_id: str
    aspect_ratio: str
    tracks: tuple[RenderPlanTrack, ...]
    plan_hash: str

    @property
    def effect_keys(self) -> tuple[str, ...]:
        return tuple(
            effect.key
            for track in self.tracks
            for clip in track.clips
            for effect in clip.effects
        )

    @property
    def scale_keyframes(self) -> tuple[RenderPlanKeyframe, ...]:
        return tuple(
            keyframe
            for track in self.tracks
            for clip in track.clips
            for keyframe in clip.keyframes
            if keyframe.property_key == "scale"
        )

    def canonical_payload(self) -> dict[str, object]:
        return {
            "workflow_run_id": self.workflow_run_id,
            "composition_version_id": self.composition_version_id,
            "aspect_ratio": self.aspect_ratio,
            "tracks": [track.to_payload() for track in self.tracks],
        }


def compile_composition_render_plan(
    workflow_run_id: str,
    composition: dict[str, Any],
) -> CompositionRenderPlan:
    """Compile one immutable composition snapshot into V1 renderer input.

    This is deliberately pure: no storage, API, provider or framework access.
    The hash is calculated from canonical JSON so a renderer can prove exactly
    which locked version produced an artifact.
    """
    if not workflow_run_id.strip():
        raise RenderPlanValidationError("workflow_run_id is required")
    if composition.get("state") != "locked":
        raise RenderPlanValidationError("render plan requires a locked composition")
    version_id = _required_string(composition.get("version_id"), "composition version_id")
    aspect_ratio = _required_string(composition.get("aspect_ratio", "9:16"), "aspect_ratio")
    if aspect_ratio != "9:16":
        raise RenderPlanValidationError("VisionFlow V1 render plan only supports 9:16")
    raw_tracks = composition.get("tracks")
    if not isinstance(raw_tracks, list):
        raise RenderPlanValidationError("composition tracks must be a list")

    tracks = tuple(_compile_track(track, index) for index, track in enumerate(raw_tracks, start=1))
    provisional = {
        "workflow_run_id": workflow_run_id,
        "composition_version_id": version_id,
        "aspect_ratio": aspect_ratio,
        "tracks": [track.to_payload() for track in tracks],
    }
    plan_hash = hashlib.sha256(_canonical_json(provisional).encode("utf-8")).hexdigest()
    return CompositionRenderPlan(
        workflow_run_id=workflow_run_id,
        composition_version_id=version_id,
        aspect_ratio=aspect_ratio,
        tracks=tracks,
        plan_hash=plan_hash,
    )


def _compile_track(raw_track: object, position: int) -> RenderPlanTrack:
    if not isinstance(raw_track, dict):
        raise RenderPlanValidationError(f"track {position} must be an object")
    track_type = _required_string(raw_track.get("track_type"), f"track {position} track_type")
    if track_type not in {"video", "audio", "overlay", "caption"}:
        raise RenderPlanValidationError(f"track {position} has unsupported type '{track_type}'")
    raw_clips = raw_track.get("clips", [])
    if not isinstance(raw_clips, list):
        raise RenderPlanValidationError(f"track {position} clips must be a list")
    return RenderPlanTrack(
        track_type=track_type,
        name=_required_string(raw_track.get("name", track_type), f"track {position} name"),
        muted=bool(raw_track.get("muted", False)),
        clips=tuple(_compile_clip(clip, track_type, position, clip_position) for clip_position, clip in enumerate(raw_clips, start=1)),
    )


def _compile_clip(raw_clip: object, track_type: str, track_position: int, clip_position: int) -> RenderPlanClip:
    label = f"track {track_position} clip {clip_position}"
    if not isinstance(raw_clip, dict):
        raise RenderPlanValidationError(f"{label} must be an object")
    source_type = _required_string(raw_clip.get("source_type"), f"{label} source_type")
    if source_type not in {"scene", "asset", "text"}:
        raise RenderPlanValidationError(f"{label} has unsupported source_type '{source_type}'")
    transform = raw_clip.get("transform", {})
    if not isinstance(transform, dict):
        raise RenderPlanValidationError(f"{label} transform must be an object")
    return RenderPlanClip(
        source_type=source_type,
        source_ref=_required_string(raw_clip.get("source_ref"), f"{label} source_ref"),
        timeline_start_ms=_non_negative_int(raw_clip.get("timeline_start_ms"), f"{label} timeline_start_ms"),
        duration_ms=_positive_int(raw_clip.get("duration_ms"), f"{label} duration_ms"),
        trim_in_ms=_non_negative_int(raw_clip.get("trim_in_ms", 0), f"{label} trim_in_ms"),
        transform=tuple(sorted(transform.items())),
        effects=_compile_effects(raw_clip.get("effects", []), track_type, label),
        keyframes=_compile_keyframes(raw_clip.get("keyframes", []), label),
    )


def _compile_effects(raw_effects: object, track_type: str, label: str) -> tuple[RenderPlanEffect, ...]:
    if not isinstance(raw_effects, list):
        raise RenderPlanValidationError(f"{label} effects must be a list")
    result: list[RenderPlanEffect] = []
    for effect_position, raw_effect in enumerate(raw_effects, start=1):
        if not isinstance(raw_effect, dict):
            raise RenderPlanValidationError(f"{label} effect {effect_position} must be an object")
        key = _required_string(raw_effect.get("effect_key"), f"{label} effect {effect_position} key")
        definition = EFFECT_REGISTRY.get(key)
        if definition is None:
            raise RenderPlanValidationError(f"{label} effect '{key}' is not supported")
        if track_type not in definition.track_types:
            raise RenderPlanValidationError(f"effect '{key}' is not valid on {track_type} tracks")
        config = raw_effect.get("config", {})
        if not isinstance(config, dict):
            raise RenderPlanValidationError(f"{label} effect '{key}' config must be an object")
        if config and not definition.supports_config:
            raise RenderPlanValidationError(f"{label} effect '{key}' does not support configuration")
        result.append(RenderPlanEffect(key=key))
    return tuple(result)


def _compile_keyframes(raw_keyframes: object, label: str) -> tuple[RenderPlanKeyframe, ...]:
    if not isinstance(raw_keyframes, list):
        raise RenderPlanValidationError(f"{label} keyframes must be a list")
    result: list[RenderPlanKeyframe] = []
    for keyframe_position, raw_keyframe in enumerate(raw_keyframes, start=1):
        if not isinstance(raw_keyframe, dict):
            raise RenderPlanValidationError(f"{label} keyframe {keyframe_position} must be an object")
        property_key = _required_string(raw_keyframe.get("property_key"), f"{label} keyframe property_key")
        if property_key != "scale":
            raise RenderPlanValidationError(f"{label} keyframe property '{property_key}' is not supported")
        value_payload = raw_keyframe.get("value")
        if not isinstance(value_payload, dict) or not isinstance(value_payload.get("value"), (int, float)):
            raise RenderPlanValidationError(f"{label} scale keyframe must contain numeric value.value")
        value = float(value_payload["value"])
        if not 0.5 <= value <= 2.0:
            raise RenderPlanValidationError(f"{label} scale keyframe value must be between 0.5 and 2.0")
        result.append(RenderPlanKeyframe(
            property_key=property_key,
            time_ms=_non_negative_int(raw_keyframe.get("time_ms"), f"{label} keyframe time_ms"),
            value=value,
            easing=_required_string(raw_keyframe.get("easing", "linear"), f"{label} keyframe easing"),
        ))
    return tuple(sorted(result, key=lambda item: (item.time_ms, item.property_key, item.easing)))


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _required_string(value: object, name: str) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not normalized:
        raise RenderPlanValidationError(f"{name} is required")
    return normalized


def _non_negative_int(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RenderPlanValidationError(f"{name} must be a non-negative integer")
    return value


def _positive_int(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise RenderPlanValidationError(f"{name} must be a positive integer")
    return value
