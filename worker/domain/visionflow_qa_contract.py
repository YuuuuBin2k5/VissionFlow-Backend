"""Technical QA contract for a rendered VisionFlow short-form artifact."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RenderArtifactForQa:
    object_key: str
    content_type: str
    byte_size: int
    checksum_sha256: str


@dataclass(frozen=True)
class MediaInspection:
    duration_seconds: float
    width: int
    height: int
    video_codec: str
    has_audio: bool


@dataclass(frozen=True)
class QaReport:
    passed: bool
    checks: tuple[str, ...]


class QualityContractViolation(ValueError):
    """Raised when an artifact is not publish-reviewable."""


def validate_short_form_artifact(artifact: RenderArtifactForQa, inspection: MediaInspection) -> QaReport:
    failures: list[str] = []
    if not artifact.object_key.startswith("visionflow/") or not artifact.object_key.endswith("/exports/final.mp4"):
        failures.append("artifact key must be a VisionFlow final export")
    if artifact.content_type != "video/mp4":
        failures.append("artifact content type must be video/mp4")
    if artifact.byte_size < 16_384:
        failures.append("artifact is too small to be a valid video export")
    if len(artifact.checksum_sha256) != 64 or any(char not in "0123456789abcdef" for char in artifact.checksum_sha256.lower()):
        failures.append("artifact must have a SHA-256 checksum")
    if not 10 <= inspection.duration_seconds <= 180:
        failures.append("short-form duration must be between 10 and 180 seconds")
    if inspection.width <= 0 or inspection.height <= 0 or inspection.height / inspection.width < 1.7:
        failures.append("short-form export must be vertical")
    if inspection.video_codec.lower() not in {"h264", "avc", "avc1"}:
        failures.append("export must use H.264 video")
    if not inspection.has_audio:
        failures.append("export must include audio")
    if failures:
        raise QualityContractViolation("; ".join(failures))
    return QaReport(True, ("artifact_integrity", "mp4_h264", "vertical", "duration", "audio"))
