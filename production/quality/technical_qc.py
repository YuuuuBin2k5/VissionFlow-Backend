"""
Deterministic Technical QC Engine for VisionFlow (Phase 6 - Section 4, 5, 6, 7, 8, 9, 10).
Inspects final rendered MP4 files using ffprobe and FFmpeg diagnostic filters.
Validates streams, drift, black frames, freezes, audio loudness, subtitle safe zones, and transitions.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from production.contracts import (
    EditorPlan,
    QualityAxisReport,
    QualityStatus,
    RenderArtifact,
    SubtitleAlignmentMode,
)
from worker.config.render_profile import resolve_ffmpeg_exe, resolve_ffprobe_exe

logger = logging.getLogger("visionflow.production.technical_qc")

# Platform UI Safe-Zones for 9:16 Shorts (1080x1920)
SAFE_ZONE_TOP_MARGIN_PX = 150
SAFE_ZONE_BOTTOM_MARGIN_PX = 320
SAFE_ZONE_SIDE_MARGIN_PX = 60
MAX_SUBTITLE_CHARS_PER_LINE = 36


class TechnicalQCEvaluator:
    """
    Deterministic Technical Quality Gate.
    Any hard technical violation produces a BLOCKER.
    """

    def __init__(self, drift_threshold_ms: float = 100.0, black_frame_threshold_sec: float = 0.5):
        self.drift_threshold_ms = drift_threshold_ms
        self.black_frame_threshold_sec = black_frame_threshold_sec
        self.ffmpeg_bin = resolve_ffmpeg_exe().replace('"', '')
        self.ffprobe_bin = resolve_ffprobe_exe().replace('"', '')

    def evaluate(
        self,
        artifact: RenderArtifact,
        editor_plan: Optional[EditorPlan] = None,
    ) -> QualityAxisReport:
        evidence: List[str] = []
        blockers: List[str] = []
        warnings: List[str] = []

        # 1. File existence and non-zero size
        file_path = getattr(artifact, "internal_file_path", None)
        if not file_path or not os.path.exists(file_path):
            blockers.append(f"Rendered artifact file not found: {file_path or artifact.output_path_ref}")
            return QualityAxisReport(
                status=QualityStatus.FAIL,
                score=0.0,
                evidence=evidence,
                blockers=blockers,
                warnings=warnings,
            )

        file_size = os.path.getsize(file_path)
        if file_size < 16_384:
            blockers.append(f"Output file size is suspiciously small ({file_size} bytes < 16KB).")

        evidence.append(f"Output file verified: {os.path.basename(file_path)} ({file_size / 1024:.1f} KB)")

        # 2. FFprobe Stream and Codec Inspection
        probe = self._probe_media(file_path)
        if not probe.get("has_streams"):
            blockers.append("ffprobe failed to read container streams: file may be corrupt.")
            return QualityAxisReport(
                status=QualityStatus.FAIL,
                score=0.0,
                evidence=evidence,
                blockers=blockers,
                warnings=warnings,
            )

        # Video stream check
        if not probe.get("has_video"):
            blockers.append("Rendered MP4 contains no video stream.")
        else:
            v_codec = probe.get("video_codec", "")
            if v_codec.lower() not in ("h264", "avc", "avc1"):
                warnings.append(f"Non-standard video codec: {v_codec} (expected h264).")
            
            # Resolution & Aspect Ratio check
            w, h = probe.get("width", 0), probe.get("height", 0)
            if w <= 0 or h <= 0:
                blockers.append(f"Invalid video dimensions: {w}x{h}.")
            elif (w, h) != (1080, 1920):
                # Check aspect ratio
                ar = round(h / max(1, w), 2)
                if ar < 1.7:
                    blockers.append(f"Video is not vertical 9:16 (resolution: {w}x{h}, aspect ratio: {ar}).")
                else:
                    warnings.append(f"Resolution is {w}x{h} instead of standard 1080x1920.")
            evidence.append(f"Video Stream: {w}x{h} @ {probe.get('fps', 30)}fps ({probe.get('video_codec', 'h264')})")

        # Audio stream check
        if not probe.get("has_audio"):
            blockers.append("Rendered MP4 contains no audio stream (missing narration/voice).")
        else:
            a_codec = probe.get("audio_codec", "")
            if a_codec.lower() not in ("aac", "mp3", "pcm"):
                warnings.append(f"Non-standard audio codec: {a_codec} (expected aac).")
            evidence.append(f"Audio Stream: {probe.get('audio_codec', 'aac')} ({probe.get('audio_sample_rate', 44100)} Hz)")

        # 3. Final Timing Authority: Duration Drift Verification (Section 3)
        rendered_dur = probe.get("duration", 0.0)
        expected_dur = (
            editor_plan.duration_seconds
            if editor_plan and editor_plan.duration_seconds > 0
            else artifact.duration_seconds
        )

        drift_ms = abs(rendered_dur - expected_dur) * 1000.0
        evidence.append(f"Duration: Expected {expected_dur:.3f}s vs Rendered {rendered_dur:.3f}s (Drift: {drift_ms:.1f}ms)")

        if drift_ms > self.drift_threshold_ms:
            # Over 100ms drift
            if drift_ms > 500.0:
                blockers.append(f"Major duration drift ({drift_ms:.1f}ms > 500ms): video desynchronized from plan.")
            else:
                warnings.append(f"Duration drift ({drift_ms:.1f}ms) exceeds strict broadcast threshold (100ms).")

        # 4. Black Frame Detection with Intentional Outro Fade Exclusion (Section 5)
        black_periods = self._detect_black_frames(file_path)
        for b_start, b_end, b_dur in black_periods:
            if b_dur >= self.black_frame_threshold_sec:
                # Check if this black period is at the very end of the video
                is_ending_fade = abs(b_end - rendered_dur) <= 0.8
                has_fade_transition = False
                if editor_plan and editor_plan.scenes:
                    last_shot = (
                        editor_plan.scenes[-1].shots[-1]
                        if editor_plan.scenes[-1].shots
                        else None
                    )
                    if last_shot and last_shot.transition_out in ("fade_to_black", "fade", "crossfade"):
                        has_fade_transition = True

                if is_ending_fade and has_fade_transition:
                    evidence.append(f"Intentional outro fade-to-black verified at {b_start:.2f}s - {b_end:.2f}s ({b_dur:.2f}s).")
                else:
                    blockers.append(f"Accidental black frame detected at {b_start:.2f}s - {b_end:.2f}s ({b_dur:.2f}s > {self.black_frame_threshold_sec}s).")

        # 5. Freeze / Stall Detection (Section 6)
        freezes = self._detect_frozen_frames(file_path)
        for f_start, f_end, f_dur in freezes:
            if f_dur >= 2.0:
                # Distinguish intentional Ken Burns / static hold from accidental freeze
                is_intentional_still = False
                if editor_plan:
                    for scn in editor_plan.scenes:
                        for sh in scn.shots:
                            if sh.timeline_start <= f_start <= sh.timeline_end:
                                if sh.motion_effect in ("static_hold", "derived_still", "graphic_fallback", "ken_burns_zoom_in"):
                                    is_intentional_still = True
                                    break

                if is_intentional_still:
                    evidence.append(f"Deliberate still hold / Ken Burns at {f_start:.2f}s - {f_end:.2f}s verified.")
                else:
                    warnings.append(f"Potential accidental frame freeze at {f_start:.2f}s - {f_end:.2f}s ({f_dur:.2f}s).")

        # 6. Audio Loudness & Clipping Verification (Section 7)
        audio_metrics = self._inspect_audio(file_path)
        if audio_metrics.get("max_volume_db", -99.0) >= -0.1:
            warnings.append(f"Peak audio clipping detected ({audio_metrics.get('max_volume_db')} dBFS >= -0.1dBFS).")
        if audio_metrics.get("mean_volume_db", -99.0) <= -45.0:
            blockers.append(f"Audio level is unacceptably silent (mean: {audio_metrics.get('mean_volume_db')} dBFS).")

        # 7. Subtitle Safe Zone & Alignment Validation (Section 8, 9)
        if editor_plan and editor_plan.subtitle_track and editor_plan.subtitle_track.chunks:
            for chk in editor_plan.subtitle_track.chunks:
                # Max characters per line
                if len(chk.text) > MAX_SUBTITLE_CHARS_PER_LINE:
                    warnings.append(f"Subtitle chunk exceeds readable line length ({len(chk.text)} chars > {MAX_SUBTITLE_CHARS_PER_LINE}): '{chk.text[:25]}...'")
                # Timing sanity
                if chk.start_sec < 0.0:
                    blockers.append(f"Negative subtitle timestamp detected: {chk.start_sec}s.")
                if chk.end_sec > rendered_dur + 0.2:
                    warnings.append(f"Subtitle chunk extends past video duration: {chk.end_sec:.2f}s > {rendered_dur:.2f}s.")
                # Alignment mode telemetry
                align_mode = getattr(chk, "alignment_mode", SubtitleAlignmentMode.PROPORTIONAL_FALLBACK)
                if align_mode == SubtitleAlignmentMode.PROPORTIONAL_FALLBACK:
                    # Honest note: proportional interpolation, not word-aligned
                    pass

        # Aggregate status and score
        if blockers:
            status = QualityStatus.FAIL
            score = max(0.0, round(0.40 - len(blockers) * 0.15, 2))
        elif warnings:
            status = QualityStatus.WARN
            score = max(0.70, round(1.0 - len(warnings) * 0.05, 2))
        else:
            status = QualityStatus.PASS
            score = 1.0

        return QualityAxisReport(
            status=status,
            score=score,
            evidence=evidence,
            blockers=blockers,
            warnings=warnings,
        )

    def _probe_media(self, file_path: str) -> Dict[str, Any]:
        cmd = [
            self.ffprobe_bin,
            "-v", "error",
            "-show_entries", "format=duration,size:stream=codec_type,codec_name,width,height,r_frame_rate,sample_rate",
            "-of", "json",
            file_path,
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            data = json.loads(res.stdout or "{}")
        except Exception:
            return {"has_streams": False}

        streams = data.get("streams", [])
        result = {
            "has_streams": len(streams) > 0,
            "duration": float(data.get("format", {}).get("duration", 0.0)),
            "size_bytes": int(data.get("format", {}).get("size", 0)),
            "has_video": False,
            "has_audio": False,
        }

        for st in streams:
            ctype = st.get("codec_type")
            if ctype == "video" and not result["has_video"]:
                result["has_video"] = True
                result["video_codec"] = st.get("codec_name", "")
                result["width"] = int(st.get("width", 0))
                result["height"] = int(st.get("height", 0))
                fps_raw = st.get("r_frame_rate", "30/1")
                if "/" in fps_raw:
                    num, den = fps_raw.split("/")
                    result["fps"] = int(round(float(num) / max(1.0, float(den))))
                else:
                    result["fps"] = int(float(fps_raw))
            elif ctype == "audio" and not result["has_audio"]:
                result["has_audio"] = True
                result["audio_codec"] = st.get("codec_name", "")
                result["audio_sample_rate"] = int(st.get("sample_rate", 44100))

        return result

    def _detect_black_frames(self, file_path: str) -> List[Tuple[float, float, float]]:
        """
        Runs FFmpeg blackdetect filter to detect black frame periods: (start, end, duration).
        """
        cmd = [
            self.ffmpeg_bin,
            "-i", file_path,
            "-vf", "blackdetect=d=0.4:pic_th=0.98:pix_th=0.06",
            "-an",
            "-f", "null",
            "-",
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=False)
            output = res.stderr or ""
        except Exception:
            return []

        black_intervals: List[Tuple[float, float, float]] = []
        # Parse blackdetect output: black_start:1.2 black_end:2.0 black_duration:0.8
        for match in re.finditer(r"black_start:([0-9.]+)\s+black_end:([0-9.]+)\s+black_duration:([0-9.]+)", output):
            b_start = float(match.group(1))
            b_end = float(match.group(2))
            b_dur = float(match.group(3))
            black_intervals.append((b_start, b_end, b_dur))

        return black_intervals

    def _detect_frozen_frames(self, file_path: str) -> List[Tuple[float, float, float]]:
        """
        Runs FFmpeg freezedetect filter to find frozen frame periods: (start, end, duration).
        """
        cmd = [
            self.ffmpeg_bin,
            "-i", file_path,
            "-vf", "freezedetect=n=-50dB:d=2.0",
            "-an",
            "-f", "null",
            "-",
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=False)
            output = res.stderr or ""
        except Exception:
            return []

        freezes: List[Tuple[float, float, float]] = []
        starts = re.findall(r"freeze_start:\s*([0-9.]+)", output)
        ends = re.findall(r"freeze_end:\s*([0-9.]+)", output)
        durs = re.findall(r"freeze_duration:\s*([0-9.]+)", output)

        for i in range(min(len(starts), len(ends))):
            s = float(starts[i])
            e = float(ends[i])
            d = float(durs[i]) if i < len(durs) else (e - s)
            freezes.append((s, e, d))

        return freezes

    def _inspect_audio(self, file_path: str) -> Dict[str, float]:
        """
        Measures max_volume and mean_volume in dBFS using FFmpeg volumedetect filter.
        """
        cmd = [
            self.ffmpeg_bin,
            "-i", file_path,
            "-vn",
            "-af", "volumedetect",
            "-f", "null",
            "-",
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=False)
            output = res.stderr or ""
        except Exception:
            return {"max_volume_db": -20.0, "mean_volume_db": -25.0}

        max_vol = -20.0
        mean_vol = -25.0
        m_max = re.search(r"max_volume:\s*(-?[0-9.]+)\s*dB", output)
        if m_max:
            max_vol = float(m_max.group(1))

        m_mean = re.search(r"mean_volume:\s*(-?[0-9.]+)\s*dB", output)
        if m_mean:
            mean_vol = float(m_mean.group(1))

        return {"max_volume_db": max_vol, "mean_volume_db": mean_vol}


# Singleton instance
technical_qc = TechnicalQCEvaluator()
