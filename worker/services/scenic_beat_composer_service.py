import json
import shutil
import subprocess
from pathlib import Path

import imageio_ffmpeg

from worker.config import ASSETS_DIR, OUTPUT_DIR, REACTIVE_RENDER_FPS, REACTIVE_RENDER_HEIGHT, REACTIVE_RENDER_WIDTH


class ScenicBeatComposerService:
    def _ffmpeg_path(self) -> str:
        return imageio_ffmpeg.get_ffmpeg_exe()

    def compose_background(
        self,
        background_video_paths: list,
        cut_events: list,
        duration: float,
        job_id: int,
        effect_intensity: str = "soft",
        color_grade: str = "soft_lofi",
    ) -> dict:
        if not background_video_paths:
            raise RuntimeError("Scenic beat-cut requires at least one background video.")

        scene_timeline = self.build_scene_timeline(cut_events, duration, effect_intensity)
        work_dir = Path(ASSETS_DIR) / f"scenic_{job_id}"
        if work_dir.exists():
            shutil.rmtree(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)

        normalized_paths = []
        try:
            for index, scene in enumerate(scene_timeline):
                source_path = background_video_paths[index % len(background_video_paths)]
                output_path = work_dir / f"scene_{index:03d}.mp4"
                self._normalize_scene(source_path, output_path, scene["duration"], color_grade)
                normalized_paths.append(output_path)

            background_path = Path(OUTPUT_DIR) / f"scenic_background_{job_id}.mp4"
            if effect_intensity in {"soft", "medium"} and len(normalized_paths) > 1:
                try:
                    self._xfade_scenes(normalized_paths, scene_timeline, background_path, transition_duration=0.45)
                except Exception as exc:
                    print(f"[ScenicBeatComposer Warning] xfade failed, falling back to concat: {exc}")
                    self._concat_scenes(normalized_paths, work_dir / "concat.txt", background_path)
            else:
                self._concat_scenes(normalized_paths, work_dir / "concat.txt", background_path)
            return {
                "background_composite_path": str(background_path),
                "scene_timeline": scene_timeline,
            }
        finally:
            for path in normalized_paths:
                try:
                    path.unlink(missing_ok=True)
                except Exception:
                    pass
            try:
                (work_dir / "concat.txt").unlink(missing_ok=True)
                work_dir.rmdir()
            except Exception:
                pass

    def build_scene_timeline(self, cut_events: list, duration: float, effect_intensity: str) -> list:
        min_gap, max_gap = (2.0, 3.2) if effect_intensity in {"medium", "hard"} else (4.0, 6.2)
        scene_starts = [0.0]
        last = 0.0
        for event in sorted(cut_events or [], key=lambda item: item.get("time", 0.0)):
            time_value = float(event.get("time", 0.0))
            if time_value <= 0.6 or time_value >= duration - 0.8:
                continue
            gap = time_value - last
            if gap < min_gap:
                continue
            if gap > max_gap:
                bridge = last + max_gap
                if bridge < duration - 0.8:
                    scene_starts.append(round(bridge, 3))
                    last = bridge
                    if time_value - last < min_gap:
                        continue
            scene_starts.append(round(time_value, 3))
            last = time_value

        while duration - last > max_gap:
            last += max_gap
            if last < duration - min_gap:
                scene_starts.append(round(last, 3))

        scene_starts = sorted(set(scene_starts))
        timeline = []
        for index, start in enumerate(scene_starts):
            end = scene_starts[index + 1] if index + 1 < len(scene_starts) else duration
            if end - start < 0.6:
                continue
            timeline.append({
                "index": len(timeline),
                "start": round(start, 3),
                "end": round(end, 3),
                "duration": round(end - start, 3),
                "transition": "flash_cut" if effect_intensity == "hard" else "soft_cut",
            })
        if len(timeline) > 1 and timeline[-1]["duration"] < min_gap:
            timeline[-2]["end"] = timeline[-1]["end"]
            timeline[-2]["duration"] = round(timeline[-2]["end"] - timeline[-2]["start"], 3)
            timeline.pop()
        return timeline or [{"index": 0, "start": 0.0, "end": round(duration, 3), "duration": round(duration, 3), "transition": "single"}]

    def overlay_with_audio(self, background_path: str, overlay_path: str, audio_path: str, job_id: int, duration: float) -> str:
        output_path = Path(OUTPUT_DIR) / f"tiktok_music_reactive_{job_id}.mp4"
        cmd = [
            self._ffmpeg_path(),
            "-y",
            "-i", background_path,
            "-i", overlay_path,
            "-i", audio_path,
            "-filter_complex", "[0:v][1:v]overlay=0:0:format=auto[v]",
            "-map", "[v]",
            "-map", "2:a",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-t", str(duration),
            "-shortest",
            str(output_path),
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return str(output_path)

    def _normalize_scene(self, source_path: str, output_path: Path, duration: float, color_grade: str) -> None:
        color_filter = self._color_filter(color_grade)
        video_filter = (
            f"scale={REACTIVE_RENDER_WIDTH}:{REACTIVE_RENDER_HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={REACTIVE_RENDER_WIDTH}:{REACTIVE_RENDER_HEIGHT},"
            f"fps={REACTIVE_RENDER_FPS},{color_filter},setsar=1"
        )
        cmd = [
            self._ffmpeg_path(),
            "-y",
            "-stream_loop", "-1",
            "-i", source_path,
            "-t", str(duration),
            "-vf", video_filter,
            "-an",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            str(output_path),
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def _concat_scenes(self, scene_paths: list, concat_file: Path, output_path: Path) -> None:
        concat_file.write_text(
            "\n".join(f"file '{str(path).replace(chr(92), '/')}'" for path in scene_paths),
            encoding="utf-8",
        )
        cmd = [
            self._ffmpeg_path(),
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_file),
            "-c", "copy",
            str(output_path),
        ]
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError:
            cmd = [
                self._ffmpeg_path(),
                "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_file),
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                str(output_path),
            ]
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def _xfade_scenes(self, scene_paths: list, scene_timeline: list, output_path: Path, transition_duration: float = 0.45) -> None:
        cmd = [self._ffmpeg_path(), "-y"]
        for path in scene_paths:
            cmd.extend(["-i", str(path)])

        filters = []
        cumulative = float(scene_timeline[0]["duration"])
        previous_label = "0:v"
        for index in range(1, len(scene_paths)):
            output_label = f"vx{index}"
            offset = max(0.1, cumulative - transition_duration)
            filters.append(
                f"[{previous_label}][{index}:v]xfade=transition=fade:duration={transition_duration}:offset={offset:.3f}[{output_label}]"
            )
            cumulative = cumulative + float(scene_timeline[index]["duration"]) - transition_duration
            previous_label = output_label

        cmd.extend([
            "-filter_complex", ";".join(filters),
            "-map", f"[{previous_label}]",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            str(output_path),
        ])
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def _color_filter(self, color_grade: str) -> str:
        if color_grade == "neon_contrast":
            return "eq=contrast=1.18:brightness=0.02:saturation=1.35"
        if color_grade == "high_contrast":
            return "eq=contrast=1.16:brightness=-0.02:saturation=1.2"
        if color_grade == "warm_soft":
            return "eq=contrast=1.04:brightness=0.02:saturation=1.12"
        if color_grade == "cool_melancholy":
            return "eq=contrast=1.08:brightness=-0.03:saturation=0.95"
        return "eq=contrast=1.06:brightness=0.0:saturation=1.08"
