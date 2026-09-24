"""
Scene Indexer & Keyframe Extraction Engine (Phase 2 - Section 8 & 9)
Implements:
- FFmpeg-driven shot boundary detection with millisecond timestamp precision.
- Micro-scene elimination (< min_duration) and maximum duration subdivision.
- Adaptive keyframe strategy (1-3 keyframes per scene, avoiding transition/corrupt frames).
- Keyframe image persistence and scene fingerprint generation.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import uuid

from production.contracts import SourceAssetRecord, SourceSceneRecord
from production.repositories.source_repository import get_scene_repository
from production.source_ingest import MEDIA_CACHE_DIR, compute_scene_fingerprint
from production.visual_hasher import compute_scene_visual_fingerprint

KEYFRAMES_DIR = MEDIA_CACHE_DIR / "keyframes"
KEYFRAMES_DIR.mkdir(exist_ok=True, parents=True)


def get_ffmpeg_binary() -> str:
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return exe
    except Exception:
        pass
    import shutil
    return shutil.which("ffmpeg") or "ffmpeg"


@dataclass
class SceneIndexerConfig:
    detector_algorithm: str = "ffmpeg_scene"
    threshold: float = 0.35
    min_scene_duration_sec: float = 0.8
    max_scene_duration_sec: float = 8.0
    keyframes_dir: Path = KEYFRAMES_DIR
    algorithm_version: str = "1.2"


class SceneIndexer:
    def __init__(self, config: Optional[SceneIndexerConfig] = None):
        self.config = config or SceneIndexerConfig()
        self.scene_repo = get_scene_repository()

    def get_segmentation_config_hash(self) -> str:
        """
        Scene Detection Versioning (Section 15):
        Encodes detector, threshold, duration bounds, and algorithm version into a deterministic hash.
        If threshold or bounds change, cached segmentation is cleanly invalidated.
        """
        import hashlib
        config_payload = {
            "detector": self.config.detector_algorithm,
            "threshold": round(self.config.threshold, 3),
            "min_duration": round(self.config.min_scene_duration_sec, 2),
            "max_duration": round(self.config.max_scene_duration_sec, 2),
            "version": self.config.algorithm_version,
        }
        return f"seg_{hashlib.sha256(json.dumps(config_payload, sort_keys=True).encode('utf-8')).hexdigest()[:12]}"

    def detect_scene_boundaries(self, video_path: Path, total_duration: float) -> List[Tuple[float, float]]:
        """
        Runs FFmpeg scene filter to detect cuts.
        Returns list of (start_sec, end_sec) intervals.
        """
        if total_duration <= 0.0:
            return [(0.0, 1.0)]

        ffmpeg_bin = get_ffmpeg_binary()
        cmd = [
            ffmpeg_bin,
            "-i", str(video_path),
            "-filter:v", f"select='gt(scene,{self.config.threshold})',showinfo",
            "-f", "null",
            "-",
        ]

        cuts: List[float] = []
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            # Parse showinfo pts_time
            # e.g.: [Parsed_showinfo_1 @ 0000021c3fa6c040] n:   1 pts: 128000 pts_time:5.33333 ...
            for line in res.stderr.splitlines():
                if "pts_time:" in line:
                    match = re.search(r"pts_time:([0-9.]+)", line)
                    if match:
                        t = float(match.group(1))
                        if t > 0.0 and (not cuts or t - cuts[-1] >= self.config.min_scene_duration_sec):
                            cuts.append(t)
        except Exception:
            pass

        # If no cuts detected or only 1 cut, subdivide uniformly based on max_scene_duration_sec
        intervals: List[Tuple[float, float]] = []
        all_points = [0.0] + [c for c in cuts if 0.0 < c < total_duration] + [total_duration]
        all_points = sorted(list(set(all_points)))

        for i in range(len(all_points) - 1):
            s = all_points[i]
            e = all_points[i + 1]
            seg_dur = e - s

            if seg_dur < self.config.min_scene_duration_sec:
                # Merge tiny segment with previous if possible
                if intervals:
                    prev_s, _ = intervals.pop()
                    intervals.append((prev_s, e))
                else:
                    intervals.append((s, e))
            elif seg_dur > self.config.max_scene_duration_sec:
                # Subdivide long scene
                num_chunks = int(seg_dur // self.config.max_scene_duration_sec) + 1
                chunk_len = seg_dur / num_chunks
                for c_idx in range(num_chunks):
                    cs = s + c_idx * chunk_len
                    ce = s + (c_idx + 1) * chunk_len
                    intervals.append((round(cs, 2), round(ce, 2)))
            else:
                intervals.append((round(s, 2), round(e, 2)))

        # Ensure at least 1 interval
        if not intervals:
            intervals.append((0.0, round(total_duration, 2)))

        return intervals

    def extract_keyframes(
        self,
        video_path: Path,
        start_sec: float,
        end_sec: float,
        scene_id: str,
    ) -> List[str]:
        """
        Adaptive Keyframe Strategy (Section 9):
        - Short (< 2.5s) -> 1 keyframe (50% point)
        - Normal (2.5s - 6s) -> 2 keyframes (30%, 70%)
        - Long (> 6s) -> 3 keyframes (20%, 50%, 80%)
        Avoids transition and corrupt frames at exact boundaries.
        """
        duration = end_sec - start_sec
        ffmpeg_bin = get_ffmpeg_binary()

        if duration <= 2.5:
            ratios = [0.50]
        elif duration <= 6.0:
            ratios = [0.30, 0.70]
        else:
            ratios = [0.20, 0.50, 0.80]

        extracted_paths: List[str] = []

        for idx, ratio in enumerate(ratios):
            target_ts = start_sec + duration * ratio
            kf_filename = f"kf_{scene_id}_{idx}_{ratio:.2f}.jpg"
            kf_path = self.config.keyframes_dir / kf_filename

            cmd = [
                ffmpeg_bin,
                "-y",
                "-ss", f"{target_ts:.3f}",
                "-i", str(video_path),
                "-vframes", "1",
                "-q:v", "2",
                str(kf_path),
            ]

            try:
                subprocess.run(cmd, capture_output=True, check=True, timeout=10)
                if kf_path.exists() and kf_path.stat().st_size > 500:
                    extracted_paths.append(str(kf_path))
            except Exception:
                pass

        return extracted_paths

    def index_source(self, source: SourceAssetRecord) -> List[SourceSceneRecord]:
        """
        Processes an ingested source:
        1. Checks if scenes already indexed for this source with matching segmentation version.
        2. Detects cuts & creates intervals.
        3. Extracts adaptive keyframes.
        4. Calculates perceptual visual dHash fingerprint.
        5. Saves to scene_repository.
        """
        seg_hash = self.get_segmentation_config_hash()

        # Idempotency / Cache check (Section 15): If indexed with EXACT same segmentation hash, reuse!
        existing_scenes = self.scene_repo.list_by_source(source.id)
        if existing_scenes and all(s.analysis_version == seg_hash for s in existing_scenes):
            return existing_scenes

        video_path = Path(source.storage_ref or source.original_uri or "")
        intervals = self.detect_scene_boundaries(video_path, source.duration)

        records: List[SourceSceneRecord] = []
        for idx, (s_time, e_time) in enumerate(intervals):
            dur = round(e_time - s_time, 2)
            scene_id = f"scn_{uuid.uuid4().hex[:10]}"
            fingerprint = compute_scene_fingerprint(source.fingerprint, s_time, e_time)

            keyframes = self.extract_keyframes(video_path, s_time, e_time, scene_id)
            visual_fp = compute_scene_visual_fingerprint(keyframes)

            scene_rec = SourceSceneRecord(
                id=scene_id,
                source_id=source.id,
                start_sec=s_time,
                end_sec=e_time,
                duration_sec=dur,
                fingerprint=fingerprint,
                visual_fingerprint=visual_fp,
                description="",  # To be populated by analyzer
                transcript=None,  # To be populated by analyzer/whisper
                entities=[],
                actions=[],
                location_context=None,
                shot_type=None,
                motion_score=0.5,
                technical_quality_score=0.85 if source.width >= 1080 else 0.75,
                embedding_ref=None,
                analysis_version=seg_hash,
                keyframes=keyframes,
            )
            records.append(scene_rec)

        self.scene_repo.save_batch(records)
        return records


scene_indexer = SceneIndexer()
