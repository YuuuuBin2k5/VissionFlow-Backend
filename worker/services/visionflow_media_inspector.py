"""FFprobe-backed technical inspector for immutable VisionFlow exports."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from worker.domain.visionflow_qa_contract import MediaInspection, RenderArtifactForQa


class MediaInspectionError(RuntimeError):
    pass


class FfprobeMediaInspector:
    def __init__(self, storage, executable: str = "ffprobe") -> None:
        self._storage, self._executable = storage, executable

    def inspect(self, artifact: RenderArtifactForQa) -> MediaInspection:
        with tempfile.TemporaryDirectory(prefix="visionflow-qa-") as directory:
            path = Path(directory) / "artifact.mp4"
            self._storage.download_to(artifact.object_key, str(path))
            return inspect_local_mp4(path, self._executable)


def inspect_local_mp4(path: Path, executable: str = "ffprobe") -> MediaInspection:
    try:
        result = subprocess.run(
            [executable, "-v", "error", "-show_entries", "format=duration:stream=codec_type,codec_name,width,height", "-of", "json", str(path)],
            capture_output=True, text=True, check=False,
        )
        payload = json.loads(result.stdout) if result.returncode == 0 else {}
    except (OSError, json.JSONDecodeError) as exc:
        raise MediaInspectionError("FFprobe could not inspect the rendered artifact") from exc
    streams = payload.get("streams", [])
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    if not isinstance(video, dict):
        raise MediaInspectionError("Rendered artifact has no video stream")
    try:
        duration = float(payload["format"]["duration"])
        return MediaInspection(duration, int(video["width"]), int(video["height"]), str(video.get("codec_name", "")), any(stream.get("codec_type") == "audio" for stream in streams))
    except (KeyError, TypeError, ValueError) as exc:
        raise MediaInspectionError("FFprobe returned incomplete media metadata") from exc
