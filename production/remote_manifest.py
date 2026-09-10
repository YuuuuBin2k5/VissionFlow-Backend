"""Versioned, declarative wire contract. No paths, commands, or persisted URLs."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")]
Checksum = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


def validate_storage_ref(value: str) -> str:
    import re
    if (not re.fullmatch(r"visionflow/production/(?:inputs|outputs|attempts|graphics|review)/[A-Za-z0-9_./-]{1,900}", value)
            or any(part in ("", ".", "..") for part in value.split("/"))):
        raise ValueError("REMOTE_RENDER_INPUT_NOT_PORTABLE")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class PortableArtifact(WireModel):
    artifact_id: Identifier
    role: Literal["VIDEO", "IMAGE", "TTS", "MUSIC", "SUBTITLE"]
    storage_ref: str
    checksum_sha256: Checksum
    size_bytes: int = Field(gt=0, le=10 * 1024**3)
    mime_type: Literal["video/mp4", "video/webm", "video/quicktime", "image/png", "image/jpeg", "image/webp", "audio/wav", "audio/mpeg", "audio/mp4", "audio/ogg", "text/x-ssa"]
    download_url: str | None = Field(default=None, max_length=8192)

    _storage_ref = field_validator("storage_ref")(validate_storage_ref)


class PortableVideo(WireModel):
    artifact_id: Identifier
    duration: float = Field(gt=0, le=3600)


class PortableSubtitle(WireModel):
    text: str = Field(max_length=2000)
    start: float = Field(ge=0, le=3600)
    end: float = Field(gt=0, le=3600)

    @model_validator(mode="after")
    def ordered(self):
        if self.end <= self.start:
            raise ValueError("Invalid subtitle interval")
        return self


class PortableRenderSpec(WireModel):
    duration_seconds: float = Field(ge=1, le=3600)
    width: int = Field(default=1080, ge=64, le=3840, multiple_of=2)
    height: int = Field(default=1920, ge=64, le=3840, multiple_of=2)
    fps: int = Field(default=30, ge=1, le=60)
    video_sources: list[PortableVideo] = Field(default_factory=list, max_length=500)
    audio_sources: list[Identifier] = Field(default_factory=list, max_length=500)
    bgm_artifact_id: Identifier | None = None
    subtitles_artifact_id: Identifier | None = None
    bgm_volume: float = Field(default=.15, ge=0, le=1)
    subtitle_chunks: list[PortableSubtitle] = Field(default_factory=list, max_length=2000)
    branding_color: str = Field(default="0x1e3a8a", pattern=r"^0x[0-9a-fA-F]{6}$")
    is_graphic_fallback: bool = False
    enable_ken_burns: bool = True


class PortableRenderManifest(WireModel):
    job_id: UUID
    run_id: Identifier
    render_spec_version: Literal["canonical-v1"] = "canonical-v1"
    render_spec: PortableRenderSpec
    artifacts: list[PortableArtifact] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def references_exist(self):
        assets = {item.artifact_id: item for item in self.artifacts}
        if len(assets) != len(self.artifacts):
            raise ValueError("Duplicate artifact ID")
        spec = self.render_spec
        refs = [(v.artifact_id, {"VIDEO", "IMAGE"}) for v in spec.video_sources]
        refs += [(a, {"TTS"}) for a in spec.audio_sources]
        refs += [(spec.bgm_artifact_id, {"MUSIC"}), (spec.subtitles_artifact_id, {"SUBTITLE"})]
        for ref, roles in refs:
            if ref is not None and (ref not in assets or assets[ref].role not in roles):
                raise ValueError("REMOTE_RENDER_INPUT_NOT_PORTABLE")
        return self

    def persisted(self) -> dict:
        value = self.model_dump(mode="json")
        for artifact in value["artifacts"]:
            artifact.pop("download_url", None)
        return value


def materialize_spec(manifest: PortableRenderManifest, paths: dict[str, Path], output: Path):
    from production.canonical_renderer import CanonicalRenderSpec
    spec = manifest.render_spec
    return CanonicalRenderSpec(
        run_id=manifest.run_id, output_path=output, duration_seconds=spec.duration_seconds,
        width=spec.width, height=spec.height, fps=spec.fps,
        video_sources=[{"file_path": str(paths[v.artifact_id]), "duration": v.duration} for v in spec.video_sources],
        audio_sources=[str(paths[a]) for a in spec.audio_sources],
        bgm_path=str(paths[spec.bgm_artifact_id]) if spec.bgm_artifact_id else None,
        subtitles_ass_path=str(paths[spec.subtitles_artifact_id]) if spec.subtitles_artifact_id else None,
        bgm_volume=spec.bgm_volume, subtitle_chunks=[c.model_dump() for c in spec.subtitle_chunks],
        branding_color=spec.branding_color, is_graphic_fallback=spec.is_graphic_fallback,
        enable_ken_burns=spec.enable_ken_burns,
    )
