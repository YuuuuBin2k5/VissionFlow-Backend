"""Filesystem workspace isolated by VisionFlow workflow run."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RenderWorkspace:
    root: Path
    workflow_run_id: str

    @property
    def path(self) -> Path: return self.root / "visionflow" / self.workflow_run_id
    @property
    def assets_path(self) -> Path: return self.path / "assets"
    @property
    def subtitles_path(self) -> Path: return self.path / "subtitles"
    @property
    def output_path(self) -> Path: return self.path / "export.mp4"

    def create(self) -> "RenderWorkspace":
        for directory in (self.assets_path, self.subtitles_path): directory.mkdir(parents=True, exist_ok=True)
        return self
