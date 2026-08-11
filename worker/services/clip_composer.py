import os
import random
import math
import subprocess
import json
import shutil
from pathlib import Path
from moviepy.video.io.VideoFileClip import VideoFileClip
from moviepy.video.compositing.CompositeVideoClip import concatenate_videoclips
from moviepy import vfx

from worker.config.render_profile import (
    resolve_ffmpeg_exe,
    resolve_ffprobe_exe,
    build_unified_ffmpeg_args,
    UNIFIED_CRF,
    UNIFIED_PRESET,
    UNIFIED_FPS
)

class ClipComposer:
    def __init__(self):
        pass

    def get_video_duration(self, path: str) -> float:
        """
        Lấy thời lượng video bằng ffprobe (hỗ trợ tuyệt đối Windows & Linux).
        """
        if not path or not os.path.exists(path):
            return 0.0
        try:
            ffprobe_bin = resolve_ffprobe_exe().replace('"', '')
            cmd = [
                ffprobe_bin, "-v", "quiet", "-print_format", "json",
                "-show_format", str(path)
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            data = json.loads(res.stdout)
            return float(data.get("format", {}).get("duration", 0.0))
        except Exception as e:
            print(f"[ClipComposer Warning] Probing duration failed for {path}: {e}")

        # Fallback to VideoFileClip
        try:
            clip = VideoFileClip(path)
            duration = clip.duration
            clip.close()
            return duration
        except Exception:
            return 0.0

    def prepare_split_half_clip(self, source_path: str, total_duration: float, y_position: int, darken: bool = False) -> VideoFileClip:
        """
        Chuẩn bị một clip nửa màn hình (resized & cropped về 1080x960).
        """
        clip = VideoFileClip(source_path)

        if clip.duration < total_duration:
            clip = clip.with_effects([vfx.Loop(duration=total_duration)])
        else:
            start_trim = random.uniform(0, max(0.0, clip.duration - total_duration - 0.2))
            clip = clip.subclipped(start_trim, start_trim + total_duration)

        clip = clip.resized(height=960)
        if clip.w < 1080:
            clip = clip.resized(width=1080)

        clip = clip.cropped(x_center=clip.w / 2, y_center=clip.h / 2, width=1080, height=960)
        clip = clip.with_position((0, y_position)).with_duration(total_duration)

        if darken:
            try:
                clip = clip.with_opacity(0.72)
            except Exception:
                pass
        return clip

    def preprocess_ffmpeg_loop_concat(self, in_path: str, dur: float, out_path: str, size_str: str = "scale=1080:960:force_original_aspect_ratio=increase,crop=1080:960") -> str:
        """
        Tối ưu hóa tải GPU/CPU: Lặp hoặc cắt video/ảnh bằng FFmpeg chuẩn hóa 100% Cross-Platform.
        Hỗ trợ cả file video (.mp4) và file ảnh AI (.png, .jpg, .jpeg, .webp).
        """
        ffmpeg_bin = resolve_ffmpeg_exe().replace('"', '')
        path_str = str(in_path).lower()

        if path_str.endswith(('.png', '.jpg', '.jpeg', '.webp')):
            cmd = [
                ffmpeg_bin, "-y",
                "-loop", "1",
                "-i", str(in_path),
                "-t", f"{dur:.3f}",
                "-vf", size_str,
                "-r", str(UNIFIED_FPS),
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-preset", UNIFIED_PRESET,
                "-crf", str(UNIFIED_CRF),
                "-movflags", "+faststart",
                str(out_path)
            ]
        else:
            in_dur = self.get_video_duration(in_path)
            if in_dur < dur:
                repeats = math.ceil(dur / max(0.1, in_dur))
                cmd = [
                    ffmpeg_bin, "-y",
                    "-stream_loop", str(repeats),
                    "-i", str(in_path),
                    "-t", f"{dur:.3f}",
                    "-vf", size_str,
                    "-r", str(UNIFIED_FPS),
                    "-c:v", "libx264",
                    "-pix_fmt", "yuv420p",
                    "-preset", UNIFIED_PRESET,
                    "-crf", str(UNIFIED_CRF),
                    "-movflags", "+faststart",
                    str(out_path)
                ]
            else:
                start_trim = random.uniform(0, max(0.0, in_dur - dur - 0.2))
                cmd = [
                    ffmpeg_bin, "-y",
                    "-ss", f"{start_trim:.3f}",
                    "-i", str(in_path),
                    "-t", f"{dur:.3f}",
                    "-vf", size_str,
                    "-r", str(UNIFIED_FPS),
                    "-c:v", "libx264",
                    "-pix_fmt", "yuv420p",
                    "-preset", UNIFIED_PRESET,
                    "-crf", str(UNIFIED_CRF),
                    "-movflags", "+faststart",
                    str(out_path)
                ]

        try:
            print(f"[ClipComposer] Running Unified FFmpeg preprocess: {in_path} -> {out_path}")
            subprocess.run(cmd, capture_output=True, check=True)
            return str(out_path)
        except Exception as e:
            print(f"[ClipComposer Error] FFmpeg loop concat failed for {in_path}: {e}")
            return str(in_path)
