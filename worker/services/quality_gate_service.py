import json
import os
import subprocess
from pathlib import Path

import imageio_ffmpeg
from PIL import Image

from worker.config import REACTIVE_MIN_FILE_SIZE_MB


class QualityGateService:
    def _ffmpeg_path(self) -> str:
        return imageio_ffmpeg.get_ffmpeg_exe()

    def _ffprobe_path(self) -> str:
        ffmpeg_path = Path(self._ffmpeg_path())
        candidate = ffmpeg_path.with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
        return str(candidate if candidate.exists() else ffmpeg_path)

    def probe_duration(self, media_path: str) -> float:
        ffprobe = self._ffprobe_path()
        if not Path(ffprobe).name.startswith("ffmpeg"):
            cmd = [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                media_path,
            ]
            result = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            return float(json.loads(result.stdout)["format"]["duration"])

        try:
            from moviepy import AudioFileClip, VideoFileClip
        except ImportError:
            from moviepy.editor import AudioFileClip, VideoFileClip

        suffix = Path(media_path).suffix.lower()
        clip = AudioFileClip(media_path) if suffix in {".mp3", ".wav", ".m4a", ".aac"} else VideoFileClip(media_path)
        try:
            return float(clip.duration)
        finally:
            clip.close()

    def _extract_frame(self, video_path: str, timestamp: float, output_path: Path) -> None:
        cmd = [
            self._ffmpeg_path(),
            "-y",
            "-ss",
            str(max(0.0, timestamp)),
            "-i",
            video_path,
            "-frames:v",
            "1",
            str(output_path),
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def _is_black_frame(self, image_path: Path) -> bool:
        image = Image.open(image_path).convert("RGB").resize((1, 1))
        r, g, b = image.getpixel((0, 0))
        return (r + g + b) / 3 < 5

    def validate_video(self, video_path: str, audio_path: str, job_id: int) -> None:
        size_mb = os.path.getsize(video_path) / (1024 * 1024)
        if size_mb < REACTIVE_MIN_FILE_SIZE_MB:
            raise RuntimeError(f"Quality gate failed: output file is too small ({size_mb:.2f}MB).")

        video_duration = self.probe_duration(video_path)
        audio_duration = self.probe_duration(audio_path)
        # Allow audio source to be longer than video (FFmpeg trims via -t flag).
        # Only raise mismatch if the audio is SHORTER than the video (something truly went wrong).
        if video_duration and audio_duration:
            if audio_duration < video_duration and abs(video_duration - audio_duration) > 0.5:
                raise RuntimeError(
                    f"Quality gate failed: audio/video duration mismatch ({audio_duration:.2f}s vs {video_duration:.2f}s)."
                )

        duration = video_duration or audio_duration
        if duration <= 0:
            return

        sample_times = [1.0, max(1.0, duration / 2), max(1.0, duration - 1.0)]
        temp_dir = Path(video_path).parent / f"quality_frames_{job_id}"
        temp_dir.mkdir(exist_ok=True)
        try:
            for idx, timestamp in enumerate(sample_times):
                frame_path = temp_dir / f"sample_{idx}.png"
                self._extract_frame(video_path, timestamp, frame_path)
                if self._is_black_frame(frame_path):
                    raise RuntimeError(f"Quality gate failed: blackout frame detected at {timestamp:.2f}s.")
        finally:
            for frame in temp_dir.glob("*.png"):
                frame.unlink(missing_ok=True)
            temp_dir.rmdir()
