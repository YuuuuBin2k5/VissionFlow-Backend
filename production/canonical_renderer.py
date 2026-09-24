"""
Canonical FFmpeg Renderer for VisionFlow Auto Production System (Phase 7 - Section 2).
Single authoritative implementation for multi-track video assembly, Ken Burns still motion,
audio resampling, ducking, subtitle safe zones, and broadcast-compliant MP4 export.
"""

from __future__ import annotations

import json
import logging
import math
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from worker.config.render_profile import resolve_ffmpeg_exe, resolve_ffprobe_exe

logger = logging.getLogger("visionflow.production.canonical_renderer")


@dataclass
class CanonicalRenderSpec:
    """
    Standardized specification for a canonical video composition pass.
    """
    run_id: str
    output_path: Path
    duration_seconds: float
    width: int = 1080
    height: int = 1920
    fps: int = 30
    video_sources: List[Dict[str, Any]] = field(default_factory=list)
    audio_sources: List[str] = field(default_factory=list)
    bgm_path: Optional[str] = None
    bgm_volume: float = 0.15
    subtitles_ass_path: Optional[str] = None
    subtitle_chunks: List[Dict[str, Any]] = field(default_factory=list)
    branding_color: str = "0x1e3a8a"  # Deep blue vertical canvas
    is_graphic_fallback: bool = False
    enable_ken_burns: bool = True


@dataclass
class CanonicalProbeResult:
    duration_seconds: float
    width: int
    height: int
    fps: int
    video_codec: str
    audio_codec: str
    file_size_bytes: int
    has_video: bool
    has_audio: bool


class CanonicalRenderError(RuntimeError):
    """Raised when canonical rendering fails."""


class CanonicalFFmpegRenderer:
    """
    Canonical video rendering engine.
    Ensures 100% behavioral parity between Local Render Daemon, Direct Local Render,
    and Modal Serverless Cloud Worker.
    """

    def __init__(self, ffmpeg_bin: Optional[str] = None, ffprobe_bin: Optional[str] = None):
        self.ffmpeg_bin = (ffmpeg_bin or resolve_ffmpeg_exe()).replace('"', '')
        self.ffprobe_bin = (ffprobe_bin or resolve_ffprobe_exe()).replace('"', '')

    def probe(self, video_path: Path) -> CanonicalProbeResult:
        """
        Measures media file properties using ffprobe.
        """
        cmd = [
            self.ffprobe_bin,
            "-v", "error",
            "-show_entries", "format=duration,size:stream=codec_type,codec_name,width,height,r_frame_rate",
            "-of", "json",
            str(video_path.resolve()),
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            data = json.loads(res.stdout or "{}")
        except Exception as e:
            logger.warning("ffprobe probe failed: %s", e)
            return CanonicalProbeResult(
                duration_seconds=0.0,
                width=1080,
                height=1920,
                fps=30,
                video_codec="h264",
                audio_codec="aac",
                file_size_bytes=0,
                has_video=False,
                has_audio=False,
            )

        duration = float(data.get("format", {}).get("duration", 0.0))
        size_bytes = int(data.get("format", {}).get("size", 0))
        width = 1080
        height = 1920
        fps = 30
        video_codec = "h264"
        audio_codec = "aac"
        has_video = False
        has_audio = False

        for st in data.get("streams", []):
            if st.get("codec_type") == "video":
                has_video = True
                width = int(st.get("width", 1080))
                height = int(st.get("height", 1920))
                video_codec = st.get("codec_name", "h264")
                fps_raw = st.get("r_frame_rate", "30/1")
                if "/" in fps_raw:
                    num, den = fps_raw.split("/")
                    fps = int(round(float(num) / max(1.0, float(den))))
                else:
                    fps = int(float(fps_raw))
            elif st.get("codec_type") == "audio":
                has_audio = True
                audio_codec = st.get("codec_name", "aac")

        return CanonicalProbeResult(
            duration_seconds=round(duration, 3),
            width=width,
            height=height,
            fps=fps,
            video_codec=video_codec,
            audio_codec=audio_codec,
            file_size_bytes=size_bytes,
            has_video=has_video,
            has_audio=has_audio,
        )

    def render(self, spec: CanonicalRenderSpec) -> CanonicalProbeResult:
        """
        Executes canonical composition according to spec.
        """
        spec.output_path.parent.mkdir(parents=True, exist_ok=True)
        total_dur = max(1.0, spec.duration_seconds)
        res_w, res_h = spec.width, spec.height
        fps = spec.fps

        inputs: List[str] = []
        filter_parts: List[str] = []

        # -------------------------------------------------------------------
        # 1. Audio Stream Assembly
        # -------------------------------------------------------------------
        valid_audio_files = [f for f in spec.audio_sources if f and os.path.exists(f)]
        audio_map = "[aout]"

        if valid_audio_files:
            norm_audio_tags = []
            for idx, apath in enumerate(valid_audio_files):
                inputs.extend(["-i", str(Path(apath).resolve())])
                filter_parts.append(
                    f"[{idx}:a]aresample=44100,aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo[a{idx}]"
                )
                norm_audio_tags.append(f"[a{idx}]")

            if len(valid_audio_files) > 1:
                filter_parts.append(f"{''.join(norm_audio_tags)}concat=n={len(valid_audio_files)}:v=0:a=1[aspeech]")
            else:
                filter_parts.append(f"{norm_audio_tags[0]}anull[aspeech]")

            # Optional BGM mixing with ducking
            if spec.bgm_path and os.path.exists(spec.bgm_path):
                # Narration feeds both the ducking sidechain and the final mix.
                # FFmpeg filter outputs are single-consumer unless split.
                filter_parts.append("[aspeech]asplit=2[aspeech_sidechain][aspeech_mix]")
                bgm_idx = inputs.count("-i")
                inputs.extend(["-i", str(Path(spec.bgm_path).resolve())])
                filter_parts.append(
                    f"[{bgm_idx}:a]aresample=44100,aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,"
                    f"volume={spec.bgm_volume}[abgm_raw]"
                )
                filter_parts.append(
                    f"[abgm_raw][aspeech_sidechain]sidechaincompress=threshold=0.08:ratio=10:attack=15:release=250[abgm_ducked]"
                )
                filter_parts.append(
                    f"[aspeech_mix][abgm_ducked]amix=inputs=2:duration=first:dropout_transition=2[aout]"
                )
            else:
                filter_parts.append("[aspeech]anull[aout]")
        else:
            # Synthetic sine tone for offline deterministic audio testing
            inputs.extend(["-f", "lavfi", "-i", f"sine=f=440:b=4:d={total_dur}"])
            filter_parts.append("[0:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo[aout]")

        # -------------------------------------------------------------------
        # 2. Video Stream Assembly
        # -------------------------------------------------------------------
        v_idx = inputs.count("-i")
        primary_media = None
        for src in spec.video_sources:
            mpath = src.get("file_path") or src.get("media_path")
            if mpath and os.path.exists(mpath):
                primary_media = mpath
                break

        if primary_media:
            is_image = primary_media.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
            if is_image and spec.enable_ken_burns:
                total_frames = max(1, int(round(total_dur * fps)))
                inputs.extend(["-loop", "1", "-i", str(Path(primary_media).resolve()), "-t", f"{total_dur:.3f}"])
                ken_burns_vf = (
                    f"zoompan=z='min(zoom+0.0015,1.25)':d={total_frames}:"
                    f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={res_w}x{res_h}:fps={fps},"
                    f"format=yuv420p"
                )
                filter_parts.append(f"[{v_idx}:v]{ken_burns_vf}[vbase]")
            else:
                inputs.extend(["-stream_loop", "-1", "-i", str(Path(primary_media).resolve()), "-t", f"{total_dur:.3f}"])
                vf_scale = f"fps={fps},format=yuv420p,scale={res_w}:{res_h}:force_original_aspect_ratio=increase,crop={res_w}:{res_h},setsar=1"
                filter_parts.append(f"[{v_idx}:v]{vf_scale}[vbase]")
        else:
            inputs.extend([
                "-f", "lavfi",
                "-i", f"color=c={spec.branding_color}:s={res_w}x{res_h}:d={total_dur}:r={fps}"
            ])
            filter_parts.append(f"[{v_idx}:v]format=yuv420p[vbase]")

        curr_v = "[vbase]"

        # -------------------------------------------------------------------
        # 3. Subtitles Overlay (ASS file or DrawText in Safe Margins)
        # -------------------------------------------------------------------
        if spec.subtitles_ass_path and os.path.exists(spec.subtitles_ass_path):
            ass_escaped = spec.subtitles_ass_path.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
            filter_parts.append(f"{curr_v}subtitles=filename='{ass_escaped}'[vout]")
            curr_v = "[vout]"
        elif spec.subtitle_chunks:
            draw_filters = []
            for chunk in spec.subtitle_chunks[:15]:
                text_clean = str(chunk.get("text", "")).replace("'", "").replace(":", "").replace("\\", "")
                t_start = float(chunk.get("start", 0.0))
                t_end = float(chunk.get("end", total_dur))
                if text_clean.strip():
                    draw_filters.append(
                        f"drawtext=text='{text_clean}':fontcolor=white:fontsize=48:box=1:boxcolor=black@0.6:"
                        f"x=(w-text_w)/2:y=h-360:enable='between(t,{t_start:.2f},{t_end:.2f})'"
                    )
            if draw_filters:
                filter_parts.append(f"{curr_v}{','.join(draw_filters)}[vout]")
                curr_v = "[vout]"
            else:
                filter_parts.append(f"{curr_v}null[vout]")
                curr_v = "[vout]"
        else:
            filter_parts.append(f"{curr_v}null[vout]")
            curr_v = "[vout]"

        filter_str = ";".join(filter_parts)

        cmd = [
            self.ffmpeg_bin, "-y",
            *inputs,
            "-filter_complex", filter_str,
            "-map", curr_v,
            "-map", audio_map,
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-r", str(fps),
            "-c:a", "aac",
            "-strict", "-2",
            "-b:a", "192k",
            "-t", f"{total_dur:.3f}",
            str(spec.output_path.resolve()),
        ]

        logger.info("Executing canonical FFmpeg render for %s: %s", spec.run_id, " ".join(cmd[:10]))
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if res.returncode != 0:
                raise CanonicalRenderError(f"FFmpeg render failed (code {res.returncode}): {res.stderr[-300:]}")
        except FileNotFoundError:
            raise CanonicalRenderError(f"FFmpeg binary not found at: {self.ffmpeg_bin}")

        if not spec.output_path.exists() or spec.output_path.stat().st_size == 0:
            raise CanonicalRenderError(f"Output file was not created or empty: {spec.output_path}")

        probe_res = self.probe(spec.output_path)
        return probe_res


canonical_renderer = CanonicalFFmpegRenderer()
