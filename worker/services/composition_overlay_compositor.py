"""Secure FFmpeg compositor for locked image-overlay timeline clips."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from worker.domain.composition_render_plan import CompositionRenderPlan


class OverlayCompositingError(RuntimeError):
    """A locked overlay layer could not be materialized or composited."""


@dataclass(frozen=True)
class OverlayLayer:
    source_key: str
    start_ms: int
    duration_ms: int
    transform: dict[str, Any]


@dataclass(frozen=True)
class ResolvedOverlayLayer:
    path: Path
    start_ms: int
    duration_ms: int
    transform: dict[str, Any]


class OverlayAssetMaterializer:
    """Downloads only workflow-scoped, image-safe object keys into the workspace."""

    _IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp"})

    def __init__(self, storage) -> None:
        self._storage = storage

    def download(self, render_plan: CompositionRenderPlan, workspace: Path) -> tuple[ResolvedOverlayLayer, ...]:
        destination_root = workspace / "overlays"
        destination_root.mkdir(parents=True, exist_ok=True)
        resolved: list[ResolvedOverlayLayer] = []
        for index, layer in enumerate(overlay_layers(render_plan), start=1):
            key = _validate_overlay_key(layer.source_key, render_plan.workflow_run_id, self._IMAGE_SUFFIXES)
            destination = destination_root / f"overlay-{index:02d}{Path(key).suffix.lower()}"
            path = Path(self._storage.download_to(key, str(destination)))
            if not path.is_file():
                raise OverlayCompositingError("Object storage did not materialize an overlay image")
            resolved.append(ResolvedOverlayLayer(path, layer.start_ms, layer.duration_ms, layer.transform))
        return tuple(resolved)


class FfmpegOverlayCompositor:
    def __init__(self, executable: str = "ffmpeg") -> None:
        self._executable = executable

    def apply(self, source_path: str, layers: tuple[ResolvedOverlayLayer, ...], workspace: Path) -> str:
        if not layers:
            return source_path
        output_path = workspace / "composition-overlaid.mp4"
        completed = subprocess.run(
            build_ffmpeg_command(self._executable, Path(source_path), layers, output_path),
            capture_output=True, text=True, check=False,
        )
        if completed.returncode != 0 or not output_path.is_file():
            raise OverlayCompositingError("FFmpeg failed to apply the locked overlay layer")
        return str(output_path)


def overlay_layers(render_plan: CompositionRenderPlan) -> tuple[OverlayLayer, ...]:
    layers: list[OverlayLayer] = []
    for track in render_plan.tracks:
        if track.track_type != "overlay" or track.muted:
            continue
        for clip in track.clips:
            if clip.source_type != "asset":
                raise OverlayCompositingError("V1 overlay tracks require an uploaded image asset")
            layers.append(OverlayLayer(clip.source_ref, clip.timeline_start_ms, clip.duration_ms, dict(clip.transform)))
    return tuple(sorted(layers, key=lambda layer: (layer.start_ms, layer.duration_ms, layer.source_key)))


def build_ffmpeg_command(executable: str, source_path: Path, layers: tuple[ResolvedOverlayLayer, ...], output_path: Path) -> list[str]:
    command = [executable, "-y", "-i", str(source_path)]
    for layer in layers:
        command.extend(["-loop", "1", "-i", str(layer.path)])
    filters: list[str] = []
    previous = "0:v"
    for index, layer in enumerate(layers, start=1):
        scale, x, y, opacity = _normalized_transform(layer.transform)
        overlay_label, output_label = f"overlay{index}", f"video{index}"
        filters.append(f"[{index}:v]scale=trunc(iw*{scale:.4f}/2)*2:-2,colorchannelmixer=aa={opacity:.4f}[{overlay_label}]")
        start, end = layer.start_ms / 1000, (layer.start_ms + layer.duration_ms) / 1000
        filters.append(f"[{previous}][{overlay_label}]overlay=x='(W-w)*{x:.4f}':y='(H-h)*{y:.4f}':enable='between(t,{start:.3f},{end:.3f})'[{output_label}]")
        previous = output_label
    command.extend([
        "-filter_complex", ";".join(filters), "-map", f"[{previous}]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "copy",
        "-shortest", "-movflags", "+faststart", str(output_path),
    ])
    return command


def _validate_overlay_key(key: str, workflow_run_id: str, suffixes: frozenset[str]) -> str:
    normalized = key.strip().replace("\\", "/")
    prefix = f"visionflow/{workflow_run_id}/"
    if not normalized.startswith(prefix) or ".." in normalized.split("/") or Path(normalized).suffix.lower() not in suffixes:
        raise OverlayCompositingError("Overlay asset must be a workflow-scoped PNG, JPEG, or WebP object")
    return normalized


def _normalized_transform(transform: dict[str, Any]) -> tuple[float, float, float, float]:
    def number(name: str, default: float) -> float:
        value = transform.get(name, default)
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else default
    scale = min(2.0, max(0.1, number("scale", 1.0)))
    x = min(1.0, max(0.0, (number("x", 0.0) + 1.0) / 2.0))
    y = min(1.0, max(0.0, (number("y", 0.0) + 1.0) / 2.0))
    opacity = min(1.0, max(0.0, number("opacity", 1.0)))
    return scale, x, y, opacity
