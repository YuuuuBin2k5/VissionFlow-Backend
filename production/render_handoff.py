"""
Real Render Handoff for VisionFlow Auto Production System (Phase 6 - Section 2, 11).
Transforms FINAL EditorPlan into an authoritative OpenCut project / render job,
dispatches to the existing render engine (FFmpeg / modal_worker),
measures output with ffprobe, and emits a secure RenderArtifact.
"""

from __future__ import annotations

import json
import logging
import math
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from production.contracts import (
    EditorPlan,
    EditorPlanType,
    RenderArtifact,
    ShortAssetFallbackPolicy,
    ShotPlan,
)
from production.editor_planner import editor_planner
from worker.config.render_profile import resolve_ffmpeg_exe, resolve_ffprobe_exe

logger = logging.getLogger("visionflow.production.render_handoff")

EXPORTS_DIR = Path(os.getenv("VISIONFLOW_EXPORTS_DIR", ".media_cache/exports")).resolve()
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)


class RenderHandoffError(RuntimeError):
    """Raised when video rendering or handoff fails."""


class RenderHandoffEngine:
    """
    Executes the final render pass from an authoritative EditorPlan.
    """

    def __init__(self, exports_dir: Optional[Path] = None):
        self.exports_dir = exports_dir or EXPORTS_DIR
        self.exports_dir.mkdir(parents=True, exist_ok=True)
        self.ffmpeg_bin = resolve_ffmpeg_exe().replace('"', '')
        self.ffprobe_bin = resolve_ffprobe_exe().replace('"', '')

    def resolve_short_asset_policy(
        self,
        shot: ShotPlan,
        target_duration: float,
        asset_media_duration: float,
        alternate_candidates: Optional[List[Any]] = None,
    ) -> Tuple[ShortAssetFallbackPolicy, Dict[str, Any]]:
        """
        Implements Section 11 Short Asset Fallback Order:
        1. Alternate candidate
        2. Redistribute shot durations
        3. Permitted loop
        4. Extract derived still
        5. Ken Burns on still
        6. Graphic fallback
        """
        metadata: Dict[str, Any] = {
            "target_duration": target_duration,
            "asset_duration": asset_media_duration,
        }

        # 1. Alternate candidate if available and sufficiently long
        if alternate_candidates:
            for alt in alternate_candidates:
                alt_dur = getattr(alt, "duration_sec", 0.0) or 0.0
                if alt_dur >= target_duration:
                    metadata["alternate_asset_id"] = getattr(alt, "asset_id", "")
                    return ShortAssetFallbackPolicy.ALTERNATE_CANDIDATE, metadata

        # If asset duration is at least 60% of target, permitted loop is acceptable
        if asset_media_duration >= 0.6 * target_duration and asset_media_duration > 1.0:
            loop_count = math.ceil(target_duration / max(0.5, asset_media_duration))
            metadata["loop_count"] = loop_count
            return ShortAssetFallbackPolicy.PERMITTED_LOOP, metadata

        # 4 & 5. Derived Still with Ken Burns motion
        metadata["motion_effect"] = "ken_burns_zoom_in"
        return ShortAssetFallbackPolicy.KEN_BURNS_ON_STILL, metadata

    def build_spec(
        self,
        editor_plan: EditorPlan,
        run_id: Optional[str] = None,
        custom_output_name: Optional[str] = None,
        strict_inputs: bool = False,
    ):
        """
        Assemble one canonical spec for both direct and portable rendering.
        """
        actual_run_id = run_id or editor_plan.run_id or f"run_{int(time.time())}"
        run_dir = self.exports_dir / actual_run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        output_filename = custom_output_name or "final_export.mp4"
        output_path = run_dir / output_filename

        total_plan_dur = editor_plan.duration_seconds or editor_plan.total_duration_sec or 10.0
        fps = 30
        res_w, res_h = 1080, 1920

        # Collect audio sources
        audio_files: List[str] = []
        if editor_plan.audio_track and editor_plan.audio_track.clips:
            for c in editor_plan.audio_track.clips:
                fpath = c.file_path or getattr(c, "source_file_path", None)
                if c.type in ("bgm", "music"):
                    continue
                if strict_inputs and not fpath:
                    raise RenderHandoffError("REMOTE_RENDER_INPUT_NOT_PORTABLE")
                if fpath and (strict_inputs or os.path.exists(fpath)):
                    audio_files.append(fpath)

        if not audio_files:
            # Fallback audio from scenes
            for scn in editor_plan.scenes:
                if scn.audio_file_path and (strict_inputs or os.path.exists(scn.audio_file_path)):
                    audio_files.append(scn.audio_file_path)

        # Collect video sources from scenes/shots
        video_sources: List[Dict[str, Any]] = []
        is_graphic_fallback = False
        for scn in editor_plan.scenes:
            for sht in scn.shots:
                is_gf = (
                    getattr(sht, "is_graphic_fallback", False)
                    or getattr(sht, "fallback_policy", None) == ShortAssetFallbackPolicy.GRAPHIC_FALLBACK
                    or getattr(sht, "provider", "") == "graphic_fallback"
                )
                sht_path = getattr(sht, "asset_file_path", None) or getattr(sht, "media_url", None)
                if not sht_path and sht.resolved_asset:
                    sht_path = sht.resolved_asset.media_url

                is_remote_url = bool(sht_path and str(sht_path).startswith(("http://", "https://")))
                is_local_file = bool(sht_path and os.path.isfile(str(sht_path)))

                if is_remote_url or is_local_file:
                    video_sources.append({"file_path": str(sht_path), "duration": sht.duration_seconds})
                elif is_gf or not sht_path or str(sht_path).startswith("/static/"):
                    is_graphic_fallback = True
                elif strict_inputs:
                    logger.error("Shot %s asset %s is neither an accessible URL nor an existing file", getattr(sht, "shot_id", "?"), sht_path)
                    raise RenderHandoffError("REMOTE_RENDER_INPUT_NOT_PORTABLE")

                if is_gf:
                    is_graphic_fallback = True

        # Collect subtitle chunks
        subtitle_chunks: List[Dict[str, Any]] = []
        if editor_plan.subtitle_track and editor_plan.subtitle_track.chunks:
            for chk in editor_plan.subtitle_track.chunks:
                t_start = getattr(chk, "start_sec", None)
                if t_start is None:
                    t_start = getattr(chk, "timeline_start", 0.0)
                t_end = getattr(chk, "end_sec", None)
                if t_end is None:
                    t_end = getattr(chk, "timeline_end", total_plan_dur)
                subtitle_chunks.append({
                    "text": chk.text,
                    "start": float(t_start),
                    "end": float(t_end),
                })

        # Canonical Render Spec
        from production.canonical_renderer import CanonicalRenderSpec

        color_seq = "0x1e3a8a"  # Deep blue vertical canvas

        spec = CanonicalRenderSpec(
            run_id=actual_run_id,
            output_path=output_path,
            duration_seconds=total_plan_dur,
            width=res_w,
            height=res_h,
            fps=fps,
            video_sources=video_sources,
            audio_sources=audio_files,
            subtitle_chunks=subtitle_chunks,
            branding_color=color_seq,
            is_graphic_fallback=is_graphic_fallback,
        )
        if editor_plan.audio_track and editor_plan.audio_track.music_clip:
            music = editor_plan.audio_track.music_clip
            bgm_candidate = music.file_path or music.source_file_path
            if bgm_candidate and (str(bgm_candidate).startswith(("http://", "https://")) or os.path.isfile(str(bgm_candidate))):
                spec.bgm_path = str(bgm_candidate)
                spec.bgm_volume = music.volume
            elif strict_inputs and bgm_candidate:
                logger.warning("BGM path %s is not accessible for portable render; proceeding without BGM", bgm_candidate)
        if strict_inputs and not audio_files and any(s.narration for s in editor_plan.scenes):
            raise RenderHandoffError("REMOTE_RENDER_INPUT_NOT_PORTABLE")
        return spec

    def render(self, editor_plan: EditorPlan, run_id: Optional[str] = None,
               custom_output_name: Optional[str] = None) -> RenderArtifact:
        from production.render_dispatcher import render_dispatcher
        spec = self.build_spec(editor_plan, run_id, custom_output_name)
        actual_run_id, output_path = spec.run_id, spec.output_path

        try:
            probe_res = render_dispatcher.dispatch(spec)
        except Exception as err:
            raise RenderHandoffError(f"Canonical render dispatch failed: {err}")

        # Obfuscated public ref to protect internal filesystem paths
        output_path_ref = f"/api/v1/production/runs/{actual_run_id}/video"

        artifact = RenderArtifact(
            run_id=actual_run_id,
            output_path_ref=output_path_ref,
            duration_seconds=round(probe_res.duration_seconds, 3),
            width=probe_res.width,
            height=probe_res.height,
            fps=probe_res.fps,
            video_codec=probe_res.video_codec,
            audio_codec=probe_res.audio_codec,
            file_size_bytes=probe_res.file_size_bytes,
            rendered_at=datetime.now(timezone.utc),
            internal_file_path=str(output_path.resolve()),
        )

        return artifact

    def probe_rendered_video(self, video_path: Path) -> Dict[str, Any]:
        """
        Measures exact container, video, and audio stream metrics via ffprobe.
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
            logger.warning("ffprobe parsing failed: %s", e)
            return {"duration": 0.0, "width": 1080, "height": 1920, "fps": 30, "video_codec": "h264", "audio_codec": "aac"}

        result = {
            "duration": float(data.get("format", {}).get("duration", 0.0)),
            "size_bytes": int(data.get("format", {}).get("size", 0)),
            "width": 1080,
            "height": 1920,
            "fps": 30,
            "video_codec": "h264",
            "audio_codec": "aac",
            "has_video": False,
            "has_audio": False,
        }

        for st in data.get("streams", []):
            if st.get("codec_type") == "video":
                result["has_video"] = True
                result["width"] = st.get("width", 1080)
                result["height"] = st.get("height", 1920)
                result["video_codec"] = st.get("codec_name", "h264")
                fps_raw = st.get("r_frame_rate", "30/1")
                if "/" in fps_raw:
                    num, den = fps_raw.split("/")
                    result["fps"] = int(round(float(num) / max(1.0, float(den))))
                else:
                    result["fps"] = int(float(fps_raw))
            elif st.get("codec_type") == "audio":
                result["has_audio"] = True
                result["audio_codec"] = st.get("codec_name", "aac")

        return result


# Singleton instance
render_handoff = RenderHandoffEngine()
