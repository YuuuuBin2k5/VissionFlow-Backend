"""Versioned semantic validation for Composition Studio snapshots.

The HTTP schema validates shape.  This module validates the renderable V1
contract before a revision is persisted, and is deliberately dependency-free
so the repository can enforce the same invariant for every caller.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


class CompositionValidationError(ValueError):
    """A syntactically valid composition violates the supported render contract."""


@dataclass(frozen=True)
class EffectDefinition:
    key: str
    track_types: frozenset[str]
    supports_config: bool = False


EFFECT_REGISTRY: dict[str, EffectDefinition] = {
    "cinematic_push": EffectDefinition("cinematic_push", frozenset({"video"})),
    "impact_shake": EffectDefinition("impact_shake", frozenset({"video"})),
    "caption_pop": EffectDefinition("caption_pop", frozenset({"video", "caption"})),
    "soft_glow": EffectDefinition("soft_glow", frozenset({"video", "overlay"})),
    "motion_blur": EffectDefinition("motion_blur", frozenset({"video", "overlay"})),
}

_TRACK_TYPES = frozenset({"video", "audio", "overlay", "caption"})
_SOURCE_TYPES = frozenset({"scene", "asset", "text"})
_EASINGS = frozenset({"linear", "ease_in", "ease_out", "ease_in_out"})


def validate_composition_for_v1(*, aspect_ratio: str, tracks: Sequence[Mapping[str, Any]]) -> None:
    """Reject data that cannot be deterministically compiled by the V1 renderer."""

    if aspect_ratio != "9:16":
        raise CompositionValidationError("Only the 9:16 short-form canvas is supported in V1")

    has_visual_clip = False
    for track_index, track in enumerate(tracks, start=1):
        track_type = str(track.get("track_type", ""))
        if track_type not in _TRACK_TYPES:
            raise CompositionValidationError(f"Track {track_index} has unsupported track_type '{track_type}'")

        for clip_index, clip in enumerate(_as_sequence(track.get("clips")), start=1):
            path = f"Track {track_index}, clip {clip_index}"
            source_type = str(clip.get("source_type", ""))
            if source_type not in _SOURCE_TYPES:
                raise CompositionValidationError(f"{path} has unsupported source_type '{source_type}'")
            if track_type in {"video", "overlay", "caption"}:
                has_visual_clip = True

            start_ms = _as_int(clip.get("timeline_start_ms"), f"{path} timeline_start_ms")
            duration_ms = _as_int(clip.get("duration_ms"), f"{path} duration_ms")
            if duration_ms <= 0 or duration_ms > 90_000:
                raise CompositionValidationError(f"{path} duration_ms must be between 1 and 90000")

            for effect in _as_sequence(clip.get("effects")):
                effect_key = str(effect.get("effect_key", ""))
                definition = EFFECT_REGISTRY.get(effect_key)
                if definition is None:
                    raise CompositionValidationError(f"{path} uses unsupported effect '{effect_key}'")
                if track_type not in definition.track_types:
                    raise CompositionValidationError(f"Effect '{effect_key}' is not supported on {track_type} tracks")
                if not definition.supports_config and effect.get("config", {}) != {}:
                    raise CompositionValidationError(f"Effect '{effect_key}' does not accept config in V1")

            for keyframe in _as_sequence(clip.get("keyframes")):
                if keyframe.get("property_key") != "scale":
                    raise CompositionValidationError(f"{path} supports only scale keyframes in V1")
                time_ms = _as_int(keyframe.get("time_ms"), f"{path} keyframe time_ms")
                if time_ms < start_ms or time_ms > start_ms + duration_ms:
                    raise CompositionValidationError(f"{path} keyframe must be inside its clip timeline range")
                if str(keyframe.get("easing", "linear")) not in _EASINGS:
                    raise CompositionValidationError(f"{path} has unsupported keyframe easing")
                value = keyframe.get("value", {})
                scale = value.get("value") if isinstance(value, Mapping) else None
                if not isinstance(scale, (int, float)) or isinstance(scale, bool) or not 0.5 <= scale <= 2.0:
                    raise CompositionValidationError(f"{path} scale keyframe value must be between 0.5 and 2.0")

    if not has_visual_clip:
        raise CompositionValidationError("Composition needs at least one video, overlay, or caption clip")


def _as_sequence(value: object) -> Sequence[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise CompositionValidationError("Composition collection must be a sequence")
    if not all(isinstance(item, Mapping) for item in value):
        raise CompositionValidationError("Composition collection contains an invalid item")
    return value


def _as_int(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise CompositionValidationError(f"{field_name} must be an integer")
    return value
