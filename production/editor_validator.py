"""
Deterministic EditorPlan Validator (Phase 5 - Section 17, 18)
Enforces strict mathematical, media, rights, and timeline constraints.
BLOCKS execution on malformed or drifting timelines.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Tuple

from production.contracts import EditorPlan, EditorPlanType, RightsState

logger = logging.getLogger("visionflow.production.editor_validator")


class ValidationResult(tuple):
    def __new__(cls, is_valid: bool, errors: List[str], warnings: List[str]):
        return tuple.__new__(cls, (is_valid, errors, warnings))

    @property
    def is_valid(self) -> bool:
        return self[0]

    @property
    def errors(self) -> List[str]:
        return self[1]

    @property
    def warnings(self) -> List[str]:
        return self[2]

    def __getitem__(self, item: Any) -> Any:
        if isinstance(item, str):
            if item == "is_valid":
                return self[0]
            if item == "errors":
                return self[1]
            if item == "warnings":
                return self[2]
            raise KeyError(f"No key '{item}' in ValidationResult")
        return tuple.__getitem__(self, item)


class EditorPlanValidator:
    """
    Deterministic validator for EditorPlan and multi-track timeline integrity.
    Verifies that all timestamps, trims, assets, audio references, and rights
    satisfy broadcast-grade constraints before handoff to OpenCutBridge or renderer.
    """

    MAX_DRIFT_SECONDS = 0.100  # 100 milliseconds max timeline drift

    @classmethod
    def validate(cls, plan: EditorPlan, strict_files: bool = False) -> ValidationResult:
        """
        Validates EditorPlan.
        Returns ValidationResult (is_valid, blocking_errors, non_blocking_warnings).
        Supports tuple unpacking: is_valid, errors, warnings = validate(plan)
        Supports dict-like access: result["is_valid"]
        Supports attribute access: result.is_valid
        """
        errors: List[str] = []
        warnings: List[str] = []

        if not plan.scenes:
            errors.append("Validation Error: EditorPlan has 0 scenes.")
            return ValidationResult(False, errors, warnings)

        # 1. Timeline Arithmetic & Drift Check
        current_timeline = 0.0
        sum_scene_durations = 0.0

        for s_idx, scn in enumerate(plan.scenes, 1):
            scene_dur = scn.actual_duration_seconds or scn.actual_duration_sec or 0.0
            sum_scene_durations += scene_dur

            # Check scene timeline bounds
            if scn.timeline_start < 0.0 or scn.timeline_end < 0.0:
                errors.append(f"Scene {s_idx} ({scn.scene_id}) has negative timeline bounds: [{scn.timeline_start}, {scn.timeline_end}]")

            if scn.timeline_end < scn.timeline_start:
                errors.append(f"Scene {s_idx} ({scn.scene_id}) timeline_end ({scn.timeline_end}) < timeline_start ({scn.timeline_start})")

            # Check gaps between consecutive scenes
            if s_idx > 1:
                prev_scene = plan.scenes[s_idx - 2]
                gap = scn.timeline_start - prev_scene.timeline_end
                if abs(gap) > 0.005:  # more than 5ms
                    if gap > 0:
                        errors.append(f"Unintended timeline gap of {gap:.3f}s between scene {s_idx - 1} and scene {s_idx}")
                    else:
                        errors.append(f"Unintended timeline overlap of {abs(gap):.3f}s between scene {s_idx - 1} and scene {s_idx}")

            # Check audio file if final plan
            if plan.plan_type == EditorPlanType.FINAL.value:
                if not scn.audio_file_path and strict_files:
                    errors.append(f"Final EditorPlan scene {s_idx} missing audio_file_path")
                elif scn.audio_file_path and strict_files and not Path(scn.audio_file_path).exists():
                    errors.append(f"Scene {s_idx} audio file does not exist: '{scn.audio_file_path}'")

            # 2. Shots Verification
            if not scn.shots:
                errors.append(f"Scene {s_idx} ({scn.scene_id}) has 0 visual shots.")
                continue

            scene_shot_sum = 0.0
            for shot_idx, shot in enumerate(scn.shots, 1):
                scene_shot_sum += shot.duration_sec

                # No negative timestamps
                if shot.timeline_start < 0.0 or shot.timeline_end < 0.0:
                    errors.append(f"Shot {shot.shot_id} has negative timeline timestamp: [{shot.timeline_start}, {shot.timeline_end}]")

                if shot.timeline_end < shot.timeline_start:
                    errors.append(f"Shot {shot.shot_id} timeline_end ({shot.timeline_end}) < timeline_start ({shot.timeline_start})")

                # Asset trim validity
                if shot.asset_trim_start < 0.0:
                    errors.append(f"Shot {shot.shot_id} asset_trim_start is negative ({shot.asset_trim_start})")

                if shot.asset_trim_end <= shot.asset_trim_start:
                    errors.append(f"Shot {shot.shot_id} asset_trim_end ({shot.asset_trim_end}) <= asset_trim_start ({shot.asset_trim_start})")

                # Media presence check if strict
                if strict_files and shot.media_url and not shot.media_url.startswith("http"):
                    lower_url = shot.media_url.lower()
                    if any(lower_url.endswith(ext) for ext in (".mp4", ".mov", ".avi", ".mkv", ".jpg", ".png")):
                        if not Path(shot.media_url).exists():
                            errors.append(f"Shot {shot.shot_id} media file does not exist on disk: '{shot.media_url}'")

                # Check rights state in provenance
                rights_state = shot.provenance.get("rights_state")
                if rights_state == RightsState.BLOCKED.value:
                    errors.append(f"Shot {shot.shot_id} has BLOCKED commercial rights.")

            # Multi-shot sum must match scene duration within tolerance
            shot_drift = abs(scene_shot_sum - scene_dur)
            if shot_dur_diff := round(shot_drift, 3) > cls.MAX_DRIFT_SECONDS:
                errors.append(f"Scene {s_idx} shots duration sum ({scene_shot_sum:.3f}s) differs from scene duration ({scene_dur:.3f}s) by {shot_dur_diff:.3f}s (> 100ms)")

        # 3. Overall Timeline Drift Calculation
        total_timeline = plan.scenes[-1].timeline_end if plan.scenes else 0.0
        drift = abs(total_timeline - sum_scene_durations)
        plan.timeline_drift_ms = round(drift * 1000.0, 2)

        if drift > cls.MAX_DRIFT_SECONDS:
            errors.append(f"Timeline drift {drift:.3f}s exceeds maximum allowed threshold of {cls.MAX_DRIFT_SECONDS:.3f}s (100ms)")

        # 4. Subtitle Track Validation
        if plan.subtitle_track and plan.subtitle_track.chunks:
            for c_idx, chunk in enumerate(plan.subtitle_track.chunks, 1):
                if chunk.start_sec < 0.0 or chunk.end_sec < 0.0:
                    errors.append(f"Subtitle chunk {c_idx} has negative timestamp: [{chunk.start_sec}, {chunk.end_sec}]")
                if chunk.end_sec < chunk.start_sec:
                    errors.append(f"Subtitle chunk {c_idx} end ({chunk.end_sec}) < start ({chunk.start_sec})")
                if chunk.end_sec > total_timeline + 0.150:
                    warnings.append(f"Subtitle chunk {c_idx} ends ({chunk.end_sec}s) slightly after total timeline ({total_timeline:.2f}s)")

        is_valid = len(errors) == 0
        return ValidationResult(is_valid, errors, warnings)
