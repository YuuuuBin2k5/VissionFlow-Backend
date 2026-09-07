"""
Editor Planner & Deterministic Timeline Engine (Phase 5 - Sections 5 to 21)
Coordinates:
ScriptPlan + VisualPlan + ResolvedAssets + actual TTS durations -> EditorPlan

Invariant:
actual_duration_seconds from ffprobe is the CANONICAL TIMING SOURCE.
All timeline arithmetic is deterministic with millisecond precision and drift <= 100ms.
"""

from __future__ import annotations

import logging
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from production.config_loader import config_loader
from production.contracts import (
    AssetCandidate,
    AssetResolutionResult,
    AudioClipPlan,
    AudioTrackPlan,
    EditorPlan,
    EditorPlanType,
    RightsState,
    SceneAssetResolution,
    SceneNarration,
    ScenePlan,
    ScriptPlan,
    ShotPlan,
    SubtitleChunkPlan,
    SubtitleTrackPlan,
    VisualIntent,
    VisualPlan,
    VisualRole,
)
from production.editor_validator import EditorPlanValidator
from production.tts_service import SceneTTSResult
from worker.services.subtitle_renderer import SubtitleRenderer

logger = logging.getLogger("visionflow.production.editor_planner")


# Default config-driven pacing bounds per visual role (Section 8)
ROLE_PACING_CONFIG = {
    VisualRole.HOOK.value: {"min_sec": 1.5, "target_sec": 2.2, "max_sec": 3.5, "pacing": "fast"},
    VisualRole.ESTABLISHING.value: {"min_sec": 2.0, "target_sec": 3.5, "max_sec": 5.5, "pacing": "medium"},
    VisualRole.PROCESS.value: {"min_sec": 2.0, "target_sec": 3.0, "max_sec": 5.0, "pacing": "medium"},
    VisualRole.DETAIL.value: {"min_sec": 1.8, "target_sec": 3.2, "max_sec": 5.0, "pacing": "deliberate"},
    VisualRole.EVIDENCE.value: {"min_sec": 2.5, "target_sec": 4.0, "max_sec": 6.5, "pacing": "deliberate"},
    VisualRole.CONTRAST.value: {"min_sec": 1.8, "target_sec": 2.8, "max_sec": 4.5, "pacing": "medium"},
    VisualRole.REVEAL.value: {"min_sec": 2.2, "target_sec": 3.8, "max_sec": 5.5, "pacing": "deliberate"},
    VisualRole.RESET.value: {"min_sec": 1.5, "target_sec": 2.5, "max_sec": 4.0, "pacing": "fast"},
    VisualRole.GRAPHIC.value: {"min_sec": 1.8, "target_sec": 3.0, "max_sec": 5.0, "pacing": "medium"},
    VisualRole.TRANSITION_SUPPORT.value: {"min_sec": 1.0, "target_sec": 1.8, "max_sec": 3.0, "pacing": "fast"},
}


class EditorPlanner:
    """
    Main Editor Planning Engine.
    Builds both preliminary DRAFT EditorPlans (using estimated speech duration)
    and broadcast-grade FINAL EditorPlans (strictly grounded in ffprobe actual duration).
    """

    def __init__(self):
        self.subtitle_renderer = SubtitleRenderer()
        thresholds = config_loader.quality_thresholds or {}
        self.pacing_config = thresholds.get("editor_pacing", ROLE_PACING_CONFIG)

    # -----------------------------------------------------------------------
    # 1. Draft Editor Plan (Preliminary Visual Handoff)
    # -----------------------------------------------------------------------
    def build_draft_editor_plan(
        self,
        script_plan: ScriptPlan,
        visual_plan: Optional[VisualPlan] = None,
        resolved_assets: Optional[AssetResolutionResult] = None,
        run_id: str = "run_default",
    ) -> EditorPlan:
        """
        Constructs preliminary DRAFT_EDITOR_PLAN using estimated speech durations.
        Render ready is False.
        """
        plan_id = f"plan_draft_{uuid.uuid4().hex[:8]}"
        scenes: List[ScenePlan] = []
        curr_timeline = 0.0

        for scn in script_plan.scenes:
            scene_id = scn.scene_id or f"scene_{scn.scene_index:03d}"
            est_dur = scn.estimated_speech_duration_sec or 4.5

            # Gather resolved shots for this scene
            resolutions = (
                [r for r in resolved_assets.resolutions if r.scene_id == scene_id]
                if resolved_assets else []
            )

            shots = self._reconcile_shots_for_scene(
                scene_id=scene_id,
                target_duration=est_dur,
                resolutions=resolutions,
                scene_start_timeline=curr_timeline,
                is_draft=True,
            )

            timeline_end = round(curr_timeline + est_dur, 3)
            scenes.append(
                ScenePlan(
                    scene_id=scene_id,
                    narration=scn.narration,
                    audio_asset_id=None,
                    audio_file_path=None,
                    actual_duration_seconds=None,  # Strictly None in draft
                    timeline_start=curr_timeline,
                    timeline_end=timeline_end,
                    shots=shots,
                )
            )
            curr_timeline = timeline_end

        total_dur = round(curr_timeline, 3)
        return EditorPlan(
            plan_id=plan_id,
            run_id=run_id,
            script_version="1.0-draft",
            plan_type=EditorPlanType.DRAFT.value,
            duration_seconds=total_dur,
            aspect_ratio="9:16",
            timeline_drift_ms=0.0,
            scenes=scenes,
            is_render_ready=False,
            created_at=datetime.now(timezone.utc),
        )

    # -----------------------------------------------------------------------
    # 2. Final Editor Plan (Strict Grounding in Actual TTS Audio)
    # -----------------------------------------------------------------------
    def build_final_editor_plan(
        self,
        script_plan: ScriptPlan,
        resolved_assets: AssetResolutionResult,
        tts_results: List[SceneTTSResult],
        visual_plan: Optional[VisualPlan] = None,
        run_id: str = "run_default",
        locked_shots: Optional[Dict[str, ShotPlan]] = None,
        bgm_asset_url: Optional[str] = None,
    ) -> EditorPlan:
        """
        Constructs authoritative FINAL_EDITOR_PLAN.
        CANONICAL TIMING SOURCE: actual_duration_seconds from ffprobe for each scene.
        Guarantees exact duration normalization and timeline drift <= 100ms.
        """
        plan_id = f"plan_final_{uuid.uuid4().hex[:8]}"
        tts_map = {res.scene_id: res for res in tts_results}
        locked_map = locked_shots or {}

        scenes: List[ScenePlan] = []
        voice_clips: List[AudioClipPlan] = []
        subtitle_chunks: List[SubtitleChunkPlan] = []

        curr_timeline = 0.0
        used_sources: List[str] = []

        for scn in script_plan.scenes:
            scene_id = scn.scene_id or f"scene_{scn.scene_index:03d}"
            tts_res = tts_map.get(scene_id)
            if not tts_res:
                raise ValueError(f"Missing actual TTS audio timing for scene '{scene_id}'")

            actual_dur = tts_res.actual_duration_seconds
            if actual_dur <= 0.0:
                raise ValueError(f"Invalid actual audio duration {actual_dur} for scene '{scene_id}'")

            scene_start = round(curr_timeline, 3)
            scene_end = round(curr_timeline + actual_dur, 3)

            # Audio voice clip for track planning
            voice_clips.append(
                AudioClipPlan(
                    clip_id=f"voice_{scene_id}",
                    scene_id=scene_id,
                    audio_asset_id=tts_res.audio_asset_id,
                    file_path=tts_res.audio_file_path,
                    timeline_start=scene_start,
                    timeline_end=scene_end,
                    duration_sec=actual_dur,
                    volume=1.0,
                )
            )

            # Subtitle chunking
            scene_chunks = self._generate_subtitles_for_scene(
                narration=scn.narration,
                word_timestamps=tts_res.word_timestamps,
                scene_start=scene_start,
                actual_dur=actual_dur,
                scene_id=scene_id,
            )
            subtitle_chunks.extend(scene_chunks)

            # Reconcile visual shots for this scene
            resolutions = [r for r in resolved_assets.resolutions if r.scene_id == scene_id]

            shots = self._reconcile_shots_for_scene(
                scene_id=scene_id,
                target_duration=actual_dur,
                resolutions=resolutions,
                scene_start_timeline=scene_start,
                is_draft=False,
                locked_shots=locked_map,
                recent_sources=used_sources,
            )

            scenes.append(
                ScenePlan(
                    scene_id=scene_id,
                    narration=scn.narration,
                    audio_asset_id=tts_res.audio_asset_id,
                    audio_file_path=tts_res.audio_file_path,
                    actual_duration_seconds=actual_dur,
                    timeline_start=scene_start,
                    timeline_end=scene_end,
                    shots=shots,
                )
            )

            for s in shots:
                if s.source_id:
                    used_sources.append(s.source_id)

            curr_timeline = scene_end

        total_duration = round(curr_timeline, 3)

        # Audio track plan with ducking
        music_clip = None
        if bgm_asset_url:
            music_clip = AudioClipPlan(
                clip_id="bgm_main",
                audio_asset_id="bgm_track_01",
                file_path=bgm_asset_url,
                timeline_start=0.0,
                timeline_end=total_duration,
                duration_sec=total_duration,
                volume=0.15,
                ducking_factor=0.20,
            )

        audio_track = AudioTrackPlan(
            voice_clips=voice_clips,
            music_clip=music_clip,
            ducking_enabled=True,
            ducking_idle_db=-18.0,
            ducking_speech_db=-30.0,
        )

        subtitle_track = SubtitleTrackPlan(
            track_id="track_subtitles_primary",
            language=script_plan.scenes[0].narration if script_plan.scenes else "vi",
            chunks=subtitle_chunks,
        )

        final_plan = EditorPlan(
            plan_id=plan_id,
            run_id=run_id,
            script_version="1.0-final-ffprobe",
            plan_type=EditorPlanType.FINAL.value,
            duration_seconds=total_duration,
            aspect_ratio="9:16",
            timeline_drift_ms=0.0,
            scenes=scenes,
            audio_track=audio_track,
            subtitle_track=subtitle_track,
            is_render_ready=True,
            created_at=datetime.now(timezone.utc),
        )

        # Validate final plan deterministically
        is_valid, errors, warnings = EditorPlanValidator.validate(final_plan, strict_files=False)
        if not is_valid:
            error_summary = "; ".join(errors)
            logger.error(f"Final EditorPlan failed validation: {error_summary}")
            raise ValueError(f"Malformed final EditorPlan: {error_summary}")

        return final_plan

    # -----------------------------------------------------------------------
    # 3. Visual Reconciliation & Shot Partitioning (Sections 7, 8, 9, 10, 11)
    # -----------------------------------------------------------------------
    def _reconcile_shots_for_scene(
        self,
        scene_id: str,
        target_duration: float,
        resolutions: List[SceneAssetResolution],
        scene_start_timeline: float,
        is_draft: bool = False,
        locked_shots: Optional[Dict[str, ShotPlan]] = None,
        recent_sources: Optional[List[str]] = None,
    ) -> List[ShotPlan]:
        """
        Reconciles visual candidate shots to exact target duration.
        Normalizes multi-shot sequence without gaps or overflows.
        """
        locked_map = locked_shots or {}
        recent = recent_sources or []

        # If no resolutions found, create graphic fallback shot
        if not resolutions:
            return [
                ShotPlan(
                    shot_id=f"shot_{scene_id}_01",
                    asset_id=f"gfx_{scene_id}",
                    source_id="graphic_backdrop",
                    provider="graphic_fallback",
                    media_url="/static/motion_typography_backdrop.mp4",
                    thumbnail_url="/static/gfx_backdrop_thumb.jpg",
                    timeline_start=scene_start_timeline,
                    timeline_end=round(scene_start_timeline + target_duration, 3),
                    duration_sec=target_duration,
                    asset_trim_start=0.0,
                    asset_trim_end=target_duration,
                    visual_role=VisualRole.PROCESS.value,
                    transition_out="cut",
                    match_score=0.50,
                )
            ]

        # Check if actual duration warrants shot count reconciliation (Section 7)
        shot_count = len(resolutions)

        # If actual duration is too short (< 3.2s) and 3 shots were planned: condense to 2
        if target_duration < 3.2 and shot_count == 3:
            resolutions = [resolutions[0], resolutions[-1]]
            shot_count = 2
        elif target_duration < 2.0 and shot_count >= 2:
            resolutions = [resolutions[0]]
            shot_count = 1

        # Calculate duration weights based on visual role pacing
        weights = []
        for res in resolutions:
            role = (res.selected_candidate.visual_role_score if res.selected_candidate else None) or "PROCESS"
            role_key = getattr(res.selected_candidate, "visual_role", "PROCESS").upper() if res.selected_candidate else "PROCESS"
            cfg = self.pacing_config.get(role_key, ROLE_PACING_CONFIG.get("PROCESS", {}))
            weights.append(cfg.get("target_sec", 3.0))

        sum_weights = sum(weights) or 1.0

        # Multi-shot normalization (Section 9)
        shot_durations = [
            round((w / sum_weights) * target_duration, 3) for w in weights
        ]

        # Absorb rounding differences in last shot to guarantee 0 drift
        dur_sum = sum(shot_durations[:-1])
        shot_durations[-1] = round(target_duration - dur_sum, 3)

        shots: List[ShotPlan] = []
        shot_timeline_start = scene_start_timeline

        for idx, (res, shot_dur) in enumerate(zip(resolutions, shot_durations), 1):
            shot_id = f"shot_{scene_id}_{idx:02d}"

            # Check if this shot has a manual lock from Phase 4 (Section 21)
            matched_locked = locked_map.get(shot_id)
            if not matched_locked:
                for k, v in locked_map.items():
                    if k == shot_id or k.endswith(f"_{idx:02d}") or (hasattr(v, "shot_id") and (v.shot_id == shot_id or v.shot_id.endswith(f"_{idx:02d}"))):
                        matched_locked = v
                        break

            if matched_locked:
                matched_locked.timeline_start = shot_timeline_start
                matched_locked.timeline_end = round(shot_timeline_start + shot_dur, 3)
                matched_locked.duration_sec = shot_dur
                matched_locked.target_duration_seconds = shot_dur
                if (matched_locked.asset_trim_end or 0.0) <= (matched_locked.asset_trim_start or 0.0):
                    matched_locked.asset_trim_start = 0.0
                    matched_locked.asset_trim_end = shot_dur
                matched_locked.is_locked = True
                shots.append(matched_locked)
                shot_timeline_start = matched_locked.timeline_end
                continue

            cand = res.selected_candidate
            if not cand:
                cand = self._get_fallback_candidate(res, shot_dur)

            # Asset Trim Validity Check (Section 10)
            asset_duration = cand.duration_sec if cand.duration_sec > 0 else 10.0
            trim_start = cand.start_sec if cand.start_sec >= 0.0 else 0.0

            motion_effect = None
            if cand.provider == "graphic_fallback" or "image" in str(cand.provenance.get("origin", "")).lower():
                # Ken Burns motion for static frames / graphic assets (Section 13)
                motion_effect = "ken_burns_zoom_in"
                trim_end = round(trim_start + shot_dur, 3)
            elif asset_duration >= shot_dur:
                # Normal trim within media duration bounds
                trim_end = round(trim_start + shot_dur, 3)
                if trim_end > asset_duration:
                    trim_start = max(0.0, round(asset_duration - shot_dur, 3))
                    trim_end = asset_duration
            else:
                # Clip is shorter than required shot duration (Section 10)
                # Check if an alternate candidate has sufficient duration
                viable_alt = next((alt for alt in res.alternate_candidates if alt.duration_sec >= shot_dur), None)
                if viable_alt:
                    cand = viable_alt
                    asset_duration = cand.duration_sec
                    trim_start = 0.0
                    trim_end = round(shot_dur, 3)
                else:
                    # Apply Ken Burns static hold or safe loop
                    motion_effect = "ken_burns_pan_right"
                    trim_start = 0.0
                    trim_end = min(asset_duration, shot_dur)

            # Transition determination (Section 12)
            # Default is cut. Transitions between scenes or reveal shots may use crossfade (0.3s)
            is_last_in_scene = idx == shot_count
            v_role = getattr(cand, "visual_role", "PROCESS").upper()
            transition_out = "cut"
            trans_dur = 0.0

            if is_last_in_scene and v_role in ("REVEAL", "RESET"):
                transition_out = "crossfade"
                trans_dur = 0.3

            shot_timeline_end = round(shot_timeline_start + shot_dur, 3)

            shot_plan = ShotPlan(
                shot_id=shot_id,
                asset_id=cand.asset_id,
                source_id=cand.source_id,
                provider=cand.provider,
                media_url=cand.media_url,
                thumbnail_url=cand.thumbnail_url,
                timeline_start=shot_timeline_start,
                timeline_end=shot_timeline_end,
                duration_sec=shot_dur,
                asset_trim_start=trim_start,
                asset_trim_end=trim_end,
                visual_role=v_role,
                transition_out=transition_out,
                transition_duration_sec=trans_dur,
                motion_effect=motion_effect,
                match_score=cand.composite_score,
                is_locked=cand.is_locked,
                provenance={
                    "provider": cand.provider,
                    "source_id": cand.source_id,
                    "rights_state": cand.rights_state.value if hasattr(cand.rights_state, "value") else str(cand.rights_state),
                    "original_url": cand.media_url,
                },
            )
            shots.append(shot_plan)
            shot_timeline_start = shot_timeline_end

        return shots

    # -----------------------------------------------------------------------
    # 4. Subtitle Chunking Integration (Section 14)
    # -----------------------------------------------------------------------
    def _generate_subtitles_for_scene(
        self,
        narration: str,
        word_timestamps: List[Dict[str, Any]],
        scene_start: float,
        actual_dur: float,
        scene_id: str,
    ) -> List[SubtitleChunkPlan]:
        """
        Groups words into 3-5 word subtitle phrases synchronized with actual TTS audio.
        """
        chunks: List[SubtitleChunkPlan] = []

        if word_timestamps:
            raw_chunks = self.subtitle_renderer.group_words_into_chunks(
                word_timestamps,
                max_words=4,
                max_gap_ms=320,
                max_chars_per_chunk=26,
            )
            for chk in raw_chunks:
                if not chk:
                    continue
                phrase_text = " ".join(item.get("word", "") for item in chk)
                start_ms = chk[0].get("start_ms", 0)
                end_ms = chk[-1].get("end_ms", 0)
                s_sec = round(scene_start + (start_ms / 1000.0), 3)
                e_sec = round(scene_start + (end_ms / 1000.0), 3)
                dur = round(max(0.4, e_sec - s_sec), 3)

                chunks.append(
                    SubtitleChunkPlan(
                        text=phrase_text,
                        start_sec=s_sec,
                        end_sec=e_sec,
                        duration_sec=dur,
                        scene_id=scene_id,
                    )
                )

        if not chunks:
            # Fallback proportional chunking from text
            words = narration.split()
            step = 4
            num_groups = math.ceil(len(words) / step)
            time_per_group = actual_dur / max(1, num_groups)

            for g_idx in range(num_groups):
                phrase = " ".join(words[g_idx * step:(g_idx + 1) * step])
                s_sec = round(scene_start + g_idx * time_per_group, 3)
                e_sec = round(scene_start + (g_idx + 1) * time_per_group, 3)
                chunks.append(
                    SubtitleChunkPlan(
                        text=phrase,
                        start_sec=s_sec,
                        end_sec=e_sec,
                        duration_sec=round(e_sec - s_sec, 3),
                        scene_id=scene_id,
                    )
                )

        return chunks

    def _get_fallback_candidate(self, res: SceneAssetResolution, duration_sec: float) -> AssetCandidate:
        return AssetCandidate(
            asset_id=f"gfx_{res.scene_id}_{res.shot_order}",
            source_id="graphic_backdrop",
            provider="graphic_fallback",
            start_sec=0.0,
            end_sec=duration_sec,
            duration_sec=duration_sec,
            thumbnail_url="/static/gfx_backdrop_thumb.jpg",
            media_url="/static/motion_typography_backdrop.mp4",
            composite_score=0.50,
            rights_state=RightsState.APPROVED_STOCK,
        )


    def export_opencut_timeline(
        self,
        editor_plan: EditorPlan,
        project_name: str = "VisionFlow Master Project",
        aspect_ratio: str = "9:16",
    ) -> Dict[str, Any]:
        """
        Converts deterministic EditorPlan to standard OpenCut Project Schema JSON.
        Maps:
        - ShotPlans -> Video Track Clips with startSec, durationSec, asset_trim_start/end, transitions
        - AudioTrack -> Audio Track Clips with startSec, durationSec, volumeDb
        - SubtitleTrack -> Text Track Clips with startSec, durationSec, styling
        """
        total_dur = (
            editor_plan.duration_seconds
            or editor_plan.total_duration_seconds
            or (editor_plan.scenes[-1].timeline_end if editor_plan.scenes else 30.0)
        )

        video_clips = []
        for s_idx, scn in enumerate(editor_plan.scenes):
            scene_num = scn.scene_index or (s_idx + 1)
            for sh_idx, shot in enumerate(scn.shots):
                shot_num = shot.shot_index or (sh_idx + 1)
                source_url = ""
                if shot.resolved_asset:
                    source_url = shot.resolved_asset.media_url or shot.resolved_asset.thumbnail_url or ""
                elif hasattr(shot, "media_url") and shot.media_url:
                    source_url = shot.media_url

                clip_dur = shot.target_duration_seconds or shot.duration_sec or 3.0
                video_clips.append({
                    "id": shot.shot_id or f"clip_scn_{scene_num}_shot_{shot_num}",
                    "name": f"Cảnh {scene_num}.{shot_num}: {shot.visual_role or 'Shot'}",
                    "type": "video",
                    "startSec": round(shot.timeline_start or 0.0, 3),
                    "durationSec": round(clip_dur, 3),
                    "sourceUrl": source_url,
                    "visual_prompt": shot.visual_prompt or "",
                    "sceneIndex": scene_num,
                    "xPercent": 50,
                    "yPercent": 50,
                    "opacity": 1.0,
                    "scale": 1.0,
                    "asset_trim_start": round(shot.asset_trim_start or 0.0, 3),
                    "asset_trim_end": round(shot.asset_trim_end or clip_dur, 3),
                    "trimStartSec": round(shot.asset_trim_start or 0.0, 3),
                    "trimEndSec": round(shot.asset_trim_end or clip_dur, 3),
                    "transition": shot.transition_out or "cut",
                    "motion_effect": shot.motion_effect,
                    "motionEffect": shot.motion_effect,
                    "isLocked": shot.is_locked,
                    "provenance": shot.provenance or {},
                })

        audio_clips = []
        if editor_plan.audio_track and editor_plan.audio_track.clips:
            for c in editor_plan.audio_track.clips:
                audio_clips.append({
                    "id": c.clip_id,
                    "name": "Giọng Lồng Tiếng AI" if c.type == "voice" else "Nhạc Nền BGM",
                    "type": "audio",
                    "startSec": round(c.timeline_start, 3),
                    "durationSec": round(c.duration_seconds if hasattr(c, "duration_seconds") else c.duration_sec, 3),
                    "sourceUrl": c.file_path or getattr(c, "source_file_path", "") or "",
                    "volume": round(10 ** (c.volume_db / 20.0), 3) if getattr(c, "volume_db", None) is not None else getattr(c, "volume", 1.0),
                    "volumeDb": getattr(c, "volume_db", 0.0),
                    "fadeInSec": getattr(c, "fade_in_sec", 0.0),
                    "fadeOutSec": getattr(c, "fade_out_sec", 0.0),
                    "duckingFactor": getattr(c, "ducking_factor", None),
                })
        else:
            # Fallback audio from scenes
            for s_idx, scn in enumerate(editor_plan.scenes):
                if scn.audio_file_path:
                    dur = scn.actual_duration_seconds or (scn.timeline_end - scn.timeline_start)
                    audio_clips.append({
                        "id": f"audio_scene_{s_idx + 1}",
                        "name": f"Giọng Cảnh {s_idx + 1}",
                        "type": "audio",
                        "startSec": round(scn.timeline_start or 0.0, 3),
                        "durationSec": round(dur, 3),
                        "sourceUrl": scn.audio_file_path,
                        "volume": 1.0,
                    })

        text_clips = []
        if editor_plan.subtitle_track and editor_plan.subtitle_track.chunks:
            for ch_idx, chk in enumerate(editor_plan.subtitle_track.chunks):
                text_clips.append({
                    "id": getattr(chk, "chunk_id", None) or f"sub_{ch_idx + 1}",
                    "name": f"Sub: {chk.text[:15]}...",
                    "type": "text",
                    "startSec": round(chk.timeline_start if hasattr(chk, "timeline_start") else chk.start_sec, 3),
                    "durationSec": round(chk.duration_seconds if hasattr(chk, "duration_seconds") else chk.duration_sec, 3),
                    "textData": {
                        "content": chk.text,
                        "fontSize": 72,
                        "fontFamily": "Montserrat",
                        "color": "#FFE600",
                        "outlineColor": "#000000",
                        "presetStyle": "hormozi",
                    },
                    "xPercent": 50,
                    "yPercent": 78,
                    "opacity": 1.0,
                    "scale": 1.0,
                })
        else:
            # Fallback text from scenes
            for s_idx, scn in enumerate(editor_plan.scenes):
                dur = scn.actual_duration_seconds or (scn.timeline_end - scn.timeline_start) if scn.timeline_end else 4.0
                chunks = self._generate_subtitles_for_scene(
                    narration=scn.narration,
                    word_timestamps=[],
                    scene_start=scn.timeline_start or 0.0,
                    actual_dur=dur,
                    scene_id=scn.scene_id,
                )
                for chk in chunks:
                    text_clips.append({
                        "id": f"sub_scn_{s_idx + 1}_{len(text_clips)}",
                        "name": f"Sub: {chk.text[:15]}...",
                        "type": "text",
                        "startSec": round(chk.start_sec, 3),
                        "durationSec": round(chk.duration_sec, 3),
                        "textData": {
                            "content": chk.text,
                            "fontSize": 72,
                            "fontFamily": "Montserrat",
                            "color": "#FFE600",
                            "outlineColor": "#000000",
                            "presetStyle": "hormozi",
                        },
                        "xPercent": 50,
                        "yPercent": 78,
                        "opacity": 1.0,
                        "scale": 1.0,
                    })

        tracks = [
            {
                "id": "track_video_main",
                "title": "🎥 Track Video Phân Cảnh (Scene Visuals)",
                "type": "video",
                "clips": video_clips,
            },
            {
                "id": "track_audio_voice",
                "title": "🎙️ Track Giọng Lồng Tiếng AI",
                "type": "audio",
                "clips": audio_clips,
            },
            {
                "id": "track_text_captions",
                "title": "💬 Track Phụ Đề & Title Banner",
                "type": "text",
                "clips": text_clips,
            },
        ]

        return {
            "version": "1.0.0-opencut",
            "projectName": project_name,
            "aspectRatio": aspect_ratio,
            "totalDurationSec": round(total_dur, 3),
            "fps": 30,
            "tracks": tracks,
            "metadata": {
                "plan_id": editor_plan.plan_id,
                "plan_type": editor_plan.plan_type.value if hasattr(editor_plan.plan_type, "value") else str(editor_plan.plan_type),
                "timeline_drift_ms": editor_plan.timeline_drift_ms,
                "is_render_ready": editor_plan.is_render_ready,
                "script_version": editor_plan.script_version,
            },
        }


# Global singleton
editor_planner = EditorPlanner()
