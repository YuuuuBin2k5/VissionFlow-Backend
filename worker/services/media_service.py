import os
import gc
import json
import random
import numpy as np
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageChops

from moviepy.video.io.VideoFileClip import VideoFileClip
from moviepy.video.VideoClip import ImageClip
from moviepy.video.compositing.CompositeVideoClip import CompositeVideoClip
from moviepy.video.compositing.CompositeVideoClip import concatenate_videoclips
from moviepy.audio.io.AudioFileClip import AudioFileClip
from moviepy.audio.AudioClip import CompositeAudioClip

from worker.config import ASSETS_DIR, OUTPUT_DIR, FONTS_DIR
from worker.services.cockpit_bridge import dispatch_log_to_cockpit, update_task_progress
from worker.services.video_quality_scoring_service import VideoQualityScoringService as QualityScorer

# Import modularized components
from worker.services.tts_engine import TTSEngine, VOICE_REGISTRY
from worker.services.subtitle_renderer import SubtitleRenderer
from worker.services.clip_composer import ClipComposer
from worker.services.audio_mixer import AudioMixer
from worker.services.split_screen_renderer import SplitScreenRenderer
from worker.services.final_exporter import FinalExporter

class MediaService:
    def __init__(self):
        self.tts_engine = TTSEngine()
        self.sub_renderer = SubtitleRenderer()
        self.composer = ClipComposer()
        self.mixer = AudioMixer()
        self.split_renderer = SplitScreenRenderer()
        self.exporter = FinalExporter()
        self.quality_scorer = QualityScorer()

    async def generate_tts(self, text: str, output_audio_path: str, voice_code: str) -> list:
        """
        Sinh file âm thanh từ text. Ủy quyền cho TTSEngine.
        """
        return await self.tts_engine.generate_tts(text, output_audio_path, voice_code)

    def group_words_into_chunks(self, word_timestamps: list, max_words: int = 4, max_gap_ms: int = 500) -> list:
        return self.sub_renderer.group_words_into_chunks(word_timestamps, max_words, max_gap_ms)

    def wrap_text(self, text: str, font, max_width: int) -> list:
        return self.sub_renderer.wrap_text(text, font, max_width)

    def _apply_default_vietsub_policy(self, visual_style_plan: dict | None) -> dict:
        return self.sub_renderer._apply_default_vietsub_policy(visual_style_plan)

    def _ensure_vietsub_word_timestamps(
        self,
        word_timestamps: list | None,
        full_voice_script: str,
        voice_audio_path: str,
        total_duration: float,
    ) -> list:
        if word_timestamps:
            usable = [
                item for item in word_timestamps
                if str(item.get("word", "")).strip()
                and float(item.get("end_ms", 0)) > float(item.get("start_ms", 0))
            ]
            if usable:
                return usable

        print("[MediaService] VIETSUB_FALLBACK: missing word timestamps, estimating Vietnamese subtitle timing.")
        estimated_words = self.tts_engine._estimate_timestamps_by_char_weight(full_voice_script, voice_audio_path)
        return estimated_words

    def _apply_scene_motion(
        self,
        clip,
        scene_motion: str,
        scene_index: int,
        bass_data: list,
        fps: int = 24,
        start_time: float = 0.0,
        cut_events: list = None,
        drop_events: list = None,
    ):
        """
        Tạo hiệu ứng giật nảy Z-Pulse chuẩn cinematic và visual beat nhẹ cho mỗi scene.
        """
        scene_motion = scene_motion or "slow_zoom"
        if scene_motion == "push_in":
            base_scale = 1.045 + (0.015 if scene_index % 2 else 0)
        elif scene_motion == "beat_push":
            base_scale = 1.075 if scene_index % 2 else 1.035
        elif scene_motion == "slow_zoom":
            base_scale = 1.028
        else:
            base_scale = 1.0

        jitter_events = []
        if cut_events:
            jitter_events.extend(cut_events)
        if drop_events:
            jitter_events.extend(drop_events)

        if not bass_data:
            if base_scale <= 1.0 and not jitter_events:
                return clip
            try:
                zoomed_scale = max(base_scale, 1.01 if jitter_events else 1.0)
                zoomed = clip.resized(height=int(1920 * zoomed_scale))
                if zoomed.w < 1080:
                    zoomed = zoomed.resized(width=1080)

                if jitter_events:
                    def static_jitter_filter(gf, t):
                        frame = gf(t)
                        h, w, c = frame.shape
                        absolute_t = start_time + t
                        apply_jitter = False
                        for ev_t in jitter_events:
                            if 0.0 <= absolute_t - ev_t <= 0.1:
                                apply_jitter = True
                                break
                        dx, dy = 0, 0
                        if apply_jitter:
                            dx = random.choice([-4, -3, -2, 2, 3, 4])
                            dy = random.choice([-4, -3, -2, 2, 3, 4])

                        pil_img = Image.fromarray(frame)
                        left = (w - 1080) // 2 + dx
                        top = (h - 1920) // 2 + dy
                        left = max(0, min(w - 1080, left))
                        top = max(0, min(h - 1920, top))

                        cropped_img = pil_img.crop((left, top, left + 1080, top + 1920))
                        return np.array(cropped_img)

                    return zoomed.transform(static_jitter_filter)

                return zoomed.cropped(
                    x_center=zoomed.w / 2,
                    y_center=zoomed.h / 2,
                    width=1080,
                    height=1920,
                )
            except Exception as motion_error:
                print(f"[MediaService Warning] Scene motion static fallback: {motion_error}")
                return clip

        def dynamic_scale_fn(t):
            absolute_t = start_time + t
            frame_idx = min(len(bass_data) - 1, int(absolute_t * fps))
            bass_val = float(bass_data[frame_idx]) if bass_data else 0.0
            return base_scale + (bass_val * 0.04)

        def dynamic_scale_filter(gf, t):
            frame = gf(t)
            h, w, c = frame.shape
            scale_t = float(dynamic_scale_fn(t))

            absolute_t = start_time + t
            apply_jitter = False
            for ev_t in jitter_events:
                if 0.0 <= absolute_t - ev_t <= 0.1:
                    apply_jitter = True
                    break

            dx, dy = 0, 0
            if apply_jitter:
                dx = random.choice([-4, -3, -2, 2, 3, 4])
                dy = random.choice([-4, -3, -2, 2, 3, 4])

            effective_scale = max(scale_t, 1.01 if apply_jitter else 1.0)
            if effective_scale <= 1.0:
                return frame

            try:
                resample_filter = Image.Resampling.LANCZOS
            except AttributeError:
                resample_filter = Image.LANCZOS

            pil_img = Image.fromarray(frame)
            new_w = int(w * effective_scale)
            new_h = int(h * effective_scale)

            resized_img = pil_img.resize((new_w, new_h), resample_filter)
            left = (new_w - w) // 2 + dx
            top = (new_h - h) // 2 + dy

            left = max(0, min(new_w - w, left))
            top = max(0, min(new_h - h, top))

            right = left + w
            bottom = top + h

            cropped_img = resized_img.crop((left, top, right, bottom))
            return np.array(cropped_img)

        return clip.transform(dynamic_scale_filter)

    def _apply_composition_frame_effects(self, clip, frame_effects: list[str]):
        """Apply persisted Composition Studio effects with real frame transforms."""
        known = [effect for effect in frame_effects if effect in {"soft_glow", "motion_blur"}]
        if not known:
            return clip

        def render_effects(get_frame, time_seconds):
            frame = get_frame(time_seconds)
            rgb = frame[..., :3]
            if "motion_blur" in known:
                previous = get_frame(max(0, time_seconds - 1 / 24))[..., :3]
                earlier = get_frame(max(0, time_seconds - 2 / 24))[..., :3]
                if previous.shape == rgb.shape and earlier.shape == rgb.shape:
                    rgb = ((rgb.astype(np.float32) * 0.58) + (previous.astype(np.float32) * 0.28) + (earlier.astype(np.float32) * 0.14)).clip(0, 255).astype(np.uint8)
            if "soft_glow" in known:
                image = Image.fromarray(rgb)
                glow = image.filter(ImageFilter.GaussianBlur(radius=8))
                rgb = np.array(Image.blend(image, ImageChops.screen(image, glow), 0.22))
            if frame.shape[-1] == 4:
                return np.concatenate((rgb, frame[..., 3:4]), axis=-1)
            return rgb

        return clip.transform(render_effects)

    def _apply_composition_scale_keyframes(self, clip, keyframes: list[dict], clip_start_seconds: float):
        """Interpolate locked scale keyframes over a rendered scene clip."""
        points = []
        for item in keyframes:
            if not isinstance(item, dict):
                continue
            try:
                relative = float(item["time_ms"]) / 1000.0 - clip_start_seconds
                scale = float(item["value"])
            except (KeyError, TypeError, ValueError):
                continue
            if -0.05 <= relative <= float(clip.duration) + 0.05 and 0.5 <= scale <= 2.0:
                points.append((relative, scale))
        if not points:
            return clip
        points.sort()

        def scale_at(time_seconds):
            if time_seconds <= points[0][0]: return points[0][1]
            if time_seconds >= points[-1][0]: return points[-1][1]
            for (left_time, left_value), (right_time, right_value) in zip(points, points[1:]):
                if left_time <= time_seconds <= right_time:
                    progress = (time_seconds - left_time) / max(0.001, right_time - left_time)
                    return left_value + (right_value - left_value) * progress
            return 1.0

        def transform_frame(get_frame, time_seconds):
            frame = get_frame(time_seconds)
            scale = scale_at(time_seconds)
            if abs(scale - 1.0) < 0.002: return frame
            height, width = frame.shape[:2]
            resized = Image.fromarray(frame).resize((max(width, int(width * scale)), max(height, int(height * scale))), Image.Resampling.LANCZOS)
            left, top = max(0, (resized.width - width) // 2), max(0, (resized.height - height) // 2)
            return np.array(resized.crop((left, top, left + width, top + height)))
        return clip.transform(transform_frame)

    def _apply_composition_clip_transform(self, clip, transform: dict):
        """Apply the persisted base transform for one timeline clip."""
        if not isinstance(transform, dict):
            return clip
        try:
            scale = min(2.0, max(0.5, float(transform.get("scale", 1))))
            offset_x = min(1.0, max(-1.0, float(transform.get("x", 0))))
            offset_y = min(1.0, max(-1.0, float(transform.get("y", 0))))
            opacity = min(1.0, max(0.0, float(transform.get("opacity", 1))))
        except (TypeError, ValueError):
            return clip
        if scale == 1 and offset_x == 0 and offset_y == 0 and opacity == 1:
            return clip

        def transform_frame(get_frame, time_seconds):
            frame = get_frame(time_seconds)
            height, width = frame.shape[:2]
            image = Image.fromarray(frame)
            resized = image.resize((max(width, int(width * scale)), max(height, int(height * scale))), Image.Resampling.LANCZOS)
            max_left, max_top = max(0, resized.width - width), max(0, resized.height - height)
            left = min(max_left, max(0, int(max_left / 2 + offset_x * max_left / 2)))
            top = min(max_top, max(0, int(max_top / 2 + offset_y * max_top / 2)))
            output = np.array(resized.crop((left, top, left + width, top + height)))
            if opacity < 1:
                output = (output.astype(np.float32) * opacity).clip(0, 255).astype(np.uint8)
            return output
        return clip.transform(transform_frame)

    def render_final_video(
        self,
        scenes_layout: list,
        word_timestamps: list,
        voice_audio_path: str,
        background_video_paths: list,
        job_id: int | None = None,
        background_music_path: str = None,
        visual_style_plan: dict | None = None,
        full_voice_script: str = "",
        workspace_path: str | None = None,
    ) -> str:
        """
        Biên tập toàn bộ Video bằng MoviePy. Tái cấu trúc gọi các helper bên trong module hóa.
        """
        if job_id is None and not workspace_path:
            raise ValueError("job_id or workspace_path is required")
        workspace = Path(workspace_path) if workspace_path else None
        if workspace:
            workspace.mkdir(parents=True, exist_ok=True)
        print(f"[MediaService] Rendering video for {'VisionFlow workspace' if workspace else f'Job #{job_id}'}")
        visual_style_plan = self._apply_default_vietsub_policy(visual_style_plan)

        # 1. ĐỌC DỮ LIỆU ÂM TẦN CHỦ ĐỘNG
        audio_reactive_path = (workspace / "audio_reactive.json") if workspace else (Path(ASSETS_DIR) / f"audio_reactive_{job_id}.json")
        bass_data, mid_data, cut_events, drop_events = [], [], [], []
        if audio_reactive_path.exists():
            try:
                reactive_data = json.loads(audio_reactive_path.read_text(encoding="utf-8"))
                bass_data = reactive_data.get("bass", [])
                mid_data = reactive_data.get("mid", [])
                cut_events = reactive_data.get("cut_events", [])
                drop_events = reactive_data.get("drop_events", [])
            except Exception as e:
                print(f"[MediaService Warning] Failed to load audio reactive data: {e}")

        # Chuẩn hóa voice duration
        voice_audio = AudioFileClip(voice_audio_path)
        voice_duration = voice_audio.duration

        sum_scene_durations = sum([scene.get("duration", 5) for scene in scenes_layout])
        scale_factor = voice_duration / sum_scene_durations if sum_scene_durations > 0 else 1.0

        video_clips = []
        current_time = 0.0

        for idx, scene in enumerate(scenes_layout):
            duration = scene.get("duration", 5) * scale_factor
            if duration <= 0:
                duration = 1.0
            bg_path = background_video_paths[idx]
            bg_str = str(bg_path).lower()

            is_image = bg_str.endswith(('.png', '.jpg', '.jpeg', '.webp'))
            if not is_image:
                try:
                    from PIL import Image
                    with Image.open(bg_path) as img:
                        img.verify()
                    is_image = True
                except Exception:
                    is_image = False

            if is_image:
                from PIL import Image
                import numpy as np
                with Image.open(bg_path) as img:
                    img_np = np.array(img.convert("RGB"))
                clip = ImageClip(img_np).with_duration(duration).resized(height=1920)
                if clip.w > 1080:
                    clip = clip.cropped(x_center=clip.w / 2, width=1080)
            else:
                clip = VideoFileClip(bg_path).resized(height=1920)
                if clip.w > 1080:
                    clip = clip.cropped(x_center=clip.w / 2, width=1080)

                if clip.duration > duration:
                    start_trim = random.uniform(0, max(0.0, clip.duration - duration - 0.5))
                    clip = clip.subclipped(start_trim, start_trim + duration)
                else:
                    from moviepy import vfx
                    clip = clip.with_effects([vfx.Loop(duration=duration)])

            clip = self._apply_scene_motion(
                clip,
                visual_style_plan.get("scene_motion", "slow_zoom"),
                idx,
                bass_data=bass_data,
                fps=24,
                start_time=current_time,
                cut_events=cut_events,
                drop_events=drop_events,
            )
            clip_effects = [item.get("effect_key") for item in scene.get("composition_effects", []) if isinstance(item, dict)]
            clip = self._apply_composition_frame_effects(clip, clip_effects)
            clip = self._apply_composition_scale_keyframes(
                clip, visual_style_plan.get("composition_keyframes", []), current_time
            )
            clip = self._apply_composition_clip_transform(clip, scene.get("composition_transform", {}))
            video_clips.append(clip)
            current_time += duration

        final_bg = concatenate_videoclips(video_clips, method="compose")

        TOTAL_AUDIO_DURATION = voice_duration
        word_timestamps = self._ensure_vietsub_word_timestamps(
            word_timestamps=word_timestamps,
            full_voice_script=full_voice_script,
            voice_audio_path=voice_audio_path,
            total_duration=TOTAL_AUDIO_DURATION,
        )
        if final_bg.duration > TOTAL_AUDIO_DURATION:
            final_bg = final_bg.subclipped(0, TOTAL_AUDIO_DURATION)
        elif final_bg.duration < TOTAL_AUDIO_DURATION - 0.1:
            from moviepy import vfx as _vfx
            final_bg = final_bg.with_effects([_vfx.Loop(duration=TOTAL_AUDIO_DURATION)])
            final_bg = final_bg.subclipped(0, TOTAL_AUDIO_DURATION)

        # 2. Xử lý hòa âm phối khí qua AudioMixer
        cut_points = []
        c_time = 0.0
        for idx, scene in enumerate(scenes_layout):
            duration = scene.get("duration", 5) * scale_factor
            if idx > 0:
                sfx_type = scene.get("sfx_trigger", "none")
                if sfx_type and sfx_type != "none":
                    cut_points.append({"time": c_time, "type": sfx_type})
            c_time += duration

        final_audio = self.mixer.mix_audio_tracks(
            voice_audio_path=voice_audio_path,
            background_music_path=background_music_path or str(ASSETS_DIR / "lofi_ambient.mp3"),
            total_duration=TOTAL_AUDIO_DURATION,
            word_timestamps=word_timestamps,
            assets_dir=Path("worker/assets") if Path("worker/assets").exists() else Path("assets"),
            cut_points=cut_points
        )
        final_bg = final_bg.with_audio(final_audio)

        # 3. Phụ đề Động Alex Hormozi qua SubtitleRenderer
        subtitle_chunks = self.group_words_into_chunks(
            word_timestamps,
            max_words=int(visual_style_plan.get("caption_max_words", 4)),
            max_gap_ms=int(visual_style_plan.get("caption_max_gap_ms", 320)),
        )
        quality_report = self.quality_scorer.score_campaign_plan(
            visual_style_plan=visual_style_plan,
            retention_plan=visual_style_plan.get("retention_plan", {}),
            subtitle_chunks=subtitle_chunks,
            scenes_layout=scenes_layout,
            total_duration=TOTAL_AUDIO_DURATION,
            size=(1080, 1920),
        )
        visual_style_plan.update(quality_report)
        subtitle_clips = []

        sub_temp_dir = (workspace / "subtitles") if workspace else (ASSETS_DIR / f"subs_{job_id}")
        sub_temp_dir.mkdir(exist_ok=True)
        retention_plan = visual_style_plan.get("retention_plan") or {}
        hook_text = visual_style_plan.get("hook_text")
        hook_duration = float(retention_plan.get("hook_duration_s") or visual_style_plan.get("hook_duration_s") or 2.5)

        # Check if base word subtitles should be rendered (suppressed if FFmpeg caption compositor handles composition captions)
        render_word_subs = visual_style_plan.get("render_word_subtitles", True)
        if render_word_subs:
            subtitle_word_chunks = self.sub_renderer.group_words_into_chunks(
                word_timestamps,
                max_words=int(visual_style_plan.get("caption_max_words", 4)),
                max_gap_ms=int(visual_style_plan.get("caption_max_gap_ms", 320)),
            )

            sub_idx_global = 0
            for chunk in subtitle_word_chunks:
                for i, active_w in enumerate(chunk):
                    try:
                        active_word_str = active_w["word"]
                        start_s = max(float(active_w["start_ms"]) / 1000.0, hook_duration if hook_text else 0.0)

                        if i < len(chunk) - 1:
                            end_s = float(chunk[i+1]["start_ms"]) / 1000.0
                        else:
                            end_s = float(chunk[-1]["end_ms"]) / 1000.0

                        duration = end_s - start_s
                        if duration <= 0:
                            continue

                        png_normal_path = str(sub_temp_dir / f"sub_{sub_idx_global}_normal.png")
                        png_glow_path = str(sub_temp_dir / f"sub_{sub_idx_global}_glow.png")

                        self.sub_renderer._create_hormozi_subtitle_png(chunk, active_word_str, png_normal_path, visual_style_plan=visual_style_plan, glow=False)
                        self.sub_renderer._create_hormozi_subtitle_png(chunk, active_word_str, png_glow_path, visual_style_plan=visual_style_plan, glow=True)

                        sub_clip_normal = (
                            ImageClip(png_normal_path)
                            .with_start(start_s)
                            .with_duration(duration)
                            .with_position((0, 0))
                        )
                        subtitle_clips.append(sub_clip_normal)

                        sub_clip_glow = (
                            ImageClip(png_glow_path)
                            .with_start(start_s)
                            .with_duration(duration)
                            .with_position((0, 0))
                        )

                        if mid_data:
                            def make_mask_opacity_filter(start_s, mid_data, fps=24):
                                threshold = 0.45
                                def mask_filter(gf, t):
                                    mask_frame = gf(t)
                                    absolute_t = start_s + t
                                    frame_idx = min(len(mid_data) - 1, int(absolute_t * fps))
                                    mid_val = float(mid_data[frame_idx]) if mid_data else 0.0
                                    if mid_val <= threshold:
                                        return np.zeros_like(mask_frame)
                                    alpha = np.clip((mid_val - threshold) / (1.0 - threshold), 0.0, 1.0)
                                    return mask_frame * alpha
                                return mask_filter

                            sub_clip_glow = sub_clip_glow.with_mask(
                                sub_clip_glow.mask.transform(make_mask_opacity_filter(start_s, mid_data, fps=24))
                            )
                            subtitle_clips.append(sub_clip_glow)

                        sub_idx_global += 1
                    except Exception as sub_err:
                        print(f"[MediaService Error] Failed to process subtitle word chunk: {sub_err}")

        # Render Title Banner Header Overlay
        if hook_text and visual_style_plan.get("show_title_banner", True):
            try:
                hook_path = str(sub_temp_dir / "hook_overlay.png")
                self.sub_renderer._create_text_overlay_png(hook_text, hook_path, visual_style_plan, "hook")
                subtitle_clips.append(
                    ImageClip(hook_path)
                    .with_start(0)
                    .with_duration(min(hook_duration, TOTAL_AUDIO_DURATION))
                    .with_position((0, 0))
                )
            except Exception as e_hook:
                print(f"[MediaService Error] Failed to render Title Banner: {e_hook}")

        # Render Logo Watermark Overlay
        logo_handle = visual_style_plan.get("logo_handle") or visual_style_plan.get("logo_text") or "@GocChiemNghiemYuuBin"
        if logo_handle and visual_style_plan.get("show_logo", True):
            try:
                logo_path = str(sub_temp_dir / "logo_watermark.png")
                self.sub_renderer._create_logo_watermark_png(logo_handle, logo_path, visual_style_plan)
                subtitle_clips.append(
                    ImageClip(logo_path)
                    .with_start(0)
                    .with_duration(TOTAL_AUDIO_DURATION)
                    .with_position((0, 0))
                )
            except Exception as e_logo:
                print(f"[MediaService Error] Failed to render Logo Watermark: {e_logo}")

        cta_text = visual_style_plan.get("cta_text")
        if cta_text and TOTAL_AUDIO_DURATION > 5:
            cta_path = str(sub_temp_dir / "cta_overlay.png")
            self.sub_renderer._create_text_overlay_png(cta_text, cta_path, visual_style_plan, "cta")
            cta_start = max(0.0, TOTAL_AUDIO_DURATION - 3.0)
            cta_duration = min(3.0, TOTAL_AUDIO_DURATION - cta_start)
            subtitle_clips.append(
                ImageClip(cta_path)
                .with_start(cta_start)
                .with_duration(cta_duration)
                .with_position((0, 0))
            )

        # Thanh tiến trình giả Kinetic Progress Bar
        if visual_style_plan.get("enable_progress_bar", True):
            try:
                try:
                    from moviepy.editor import ColorClip
                except ImportError:
                    from moviepy import ColorClip

                progress_bar = ColorClip(size=(1080, 4), color=(0, 255, 102), duration=TOTAL_AUDIO_DURATION)
                mask_source = ColorClip(size=(1080, 4), color=(255, 255, 255), duration=TOTAL_AUDIO_DURATION)
                progress_bar = progress_bar.with_mask(mask_source.to_mask())

                def make_mask_progress_filter(total_duration, max_width=1080):
                    def mask_progress_filter(gf, t):
                        mask_frame = gf(t)
                        w_t = int((t / total_duration) * max_width)
                        w_t = max(0, min(max_width, w_t))
                        mask_frame = mask_frame.copy()
                        if w_t < max_width:
                            mask_frame[:, w_t:] = 0.0
                        return mask_frame
                    return mask_progress_filter

                progress_bar.mask = progress_bar.mask.transform(make_mask_progress_filter(TOTAL_AUDIO_DURATION, 1080))
                progress_bar = progress_bar.with_position((0, 1916))
                subtitle_clips.append(progress_bar)
            except Exception as e_pb:
                print(f"[MediaService Error] Failed to add Progress Bar: {e_pb}")

        final_video = CompositeVideoClip([final_bg] + subtitle_clips, size=(1080, 1920))
        final_video = final_video.with_duration(TOTAL_AUDIO_DURATION)

        # 4. Xuất Video qua FinalExporter
        output_file_path = str((workspace / "export.mp4") if workspace else (OUTPUT_DIR / f"tiktok_video_{job_id}.mp4"))
        temp_audio_path = str((workspace / "temp_audio.m4a") if workspace else (ASSETS_DIR / f"temp_audio_{job_id}.m4a"))

        if workspace:
            self.exporter.export_visionflow_video(final_video, output_file_path, temp_audio_path)
        else:
            self.exporter.export_video(final_video, output_file_path, job_id, temp_audio_path)

        final_video.close()
        final_bg.close()
        voice_audio.close()
        for clip in video_clips:
            clip.close()

        try:
            import shutil
            if sub_temp_dir.exists():
                shutil.rmtree(sub_temp_dir, ignore_errors=True)
        except Exception as e:
            print(f"[MediaService Warning] Failed to clean up temporary subtitle files: {e}")

        print(f"[MediaService Success] Render completed! File size: {os.path.getsize(output_file_path)} bytes")
        return output_file_path


    def render_split_screen_video(
        self,
        scenes_layout: list,
        word_timestamps: list,
        voice_audio_path: str,
        top_video_paths: list,
        bottom_video_paths: list,
        full_voice_script: str,
        job_id: int,
        background_music_path: str = None,
        visual_style_plan: dict | None = None,
        metadata: dict = None,
    ) -> str:
        """
        Sinh video dạng split-screen (nửa trên B-Roll, nửa dưới game/satisfying).
        Sử dụng FFmpeg để kết xuất tối ưu hiệu năng hoặc fallback về MoviePy nếu lỗi.
        """
        print(f"[MediaService] Rendering split-screen short for Job #{job_id}")
        visual_style_plan = self._apply_default_vietsub_policy(visual_style_plan)

        retention_plan = visual_style_plan.get("retention_plan") or {}
        hook_text = visual_style_plan.get("hook_text") or ""
        hook_duration = float(retention_plan.get("hook_duration_s") or visual_style_plan.get("hook_duration_s") or 1.5)

        cta_text = visual_style_plan.get("cta_text") or ""

        voice_dur = self.composer.get_video_duration(voice_audio_path)
        TOTAL_AUDIO_DURATION = voice_dur

        word_timestamps = self._ensure_vietsub_word_timestamps(
            word_timestamps=word_timestamps,
            full_voice_script=full_voice_script,
            voice_audio_path=voice_audio_path,
            total_duration=TOTAL_AUDIO_DURATION,
        )

        cta_start = max(0.0, TOTAL_AUDIO_DURATION - 3.0) if cta_text else None

        # Tạo thư mục temp xử lý ghép cảnh FFmpeg
        temp_proc_dir = ASSETS_DIR / f"split_proc_{job_id}"
        temp_proc_dir.mkdir(exist_ok=True)

        try:
            # 1. Tiền xử lý các video nền trên (Top scenes)
            top_segments = []
            sum_top_dur = sum([s.get("duration", 5) for s in scenes_layout])
            scale_top = TOTAL_AUDIO_DURATION / sum_top_dur if sum_top_dur > 0 else 1.0

            c_time = 0.0
            for idx, scene in enumerate(scenes_layout):
                dur = scene.get("duration", 5) * scale_top
                in_path = top_video_paths[idx]
                out_path = temp_proc_dir / f"top_segment_{idx}.mp4"

                # Biến đổi aspect ratio sang vertical nửa trên 1080x960
                size_filter = "scale=1080:960:force_original_aspect_ratio=increase,crop=1080:960"
                if visual_style_plan.get("top_darken", True):
                    size_filter += ",drawbox=color=black@0.22:t=fill"

                self.composer.preprocess_ffmpeg_loop_concat(in_path, dur, str(out_path), size_str=size_filter)
                top_segments.append(str(out_path))
                c_time += dur

            # Ghép concat các file top
            top_concat_txt = temp_proc_dir / "top_concat.txt"
            concat_lines = [f"file '{self.split_renderer._escape_ass_text(str(p))}'" for p in top_segments]
            top_concat_txt.write_text("\n".join(concat_lines), encoding="utf-8")

            top_merged_path = str(temp_proc_dir / "top_merged.mp4")
            cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(top_concat_txt), "-c", "copy", top_merged_path]
            subprocess.run(cmd, capture_output=True, check=True)

            # 2. Tiền xử lý các video nền dưới (Bottom scenes)
            bottom_segments = []
            sum_bot_dur = sum([s.get("duration", 5) for s in scenes_layout])
            scale_bot = TOTAL_AUDIO_DURATION / sum_bot_dur if sum_bot_dur > 0 else 1.0

            c_time = 0.0
            for idx, scene in enumerate(scenes_layout):
                dur = scene.get("duration", 5) * scale_bot
                in_path = bottom_video_paths[idx]
                out_path = temp_proc_dir / f"bot_segment_{idx}.mp4"

                size_filter = "scale=1080:960:force_original_aspect_ratio=increase,crop=1080:960"
                if visual_style_plan.get("bottom_darken", False):
                    size_filter += ",drawbox=color=black@0.15:t=fill"

                self.composer.preprocess_ffmpeg_loop_concat(in_path, dur, str(out_path), size_str=size_filter)
                bottom_segments.append(str(out_path))
                c_time += dur

            bottom_concat_txt = temp_proc_dir / "bot_concat.txt"
            concat_lines = [f"file '{self.split_renderer._escape_ass_text(str(p))}'" for p in bottom_segments]
            bottom_concat_txt.write_text("\n".join(concat_lines), encoding="utf-8")

            bottom_merged_path = str(temp_proc_dir / "bot_merged.mp4")
            cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(bottom_concat_txt), "-c", "copy", bottom_merged_path]
            subprocess.run(cmd, capture_output=True, check=True)

            # 3. Kéo dải âm sóng não 432Hz phụ vào giọng nói trước khi mix bằng FFmpeg
            mixed_voice_audio = voice_audio_path
            audio_432hz_path = Path("worker/assets/audio/432hz_focus.wav")
            if not audio_432hz_path.exists():
                audio_432hz_path = Path("assets/audio/432hz_focus.wav")

            if audio_432hz_path.exists():
                try:
                    out_mixed_audio = temp_proc_dir / "voice_mixed_432.wav"
                    cmd_audio = [
                        "ffmpeg", "-y",
                        "-i", voice_audio_path,
                        "-stream_loop", "-1", "-i", str(audio_432hz_path),
                        "-filter_complex", f"[1:a]volume=0.03[a432];[0:a][a432]amix=inputs=2:duration=first[a]",
                        "-map", "[a]",
                        str(out_mixed_audio)
                    ]
                    subprocess.run(cmd_audio, capture_output=True, check=True)
                    mixed_voice_audio = str(out_mixed_audio)
                except Exception as e432:
                    print(f"[MediaService Warning] Failed to mix 432Hz focus track: {e432}")

            # 4. Render ghép khung hình & vẽ chữ qua SplitScreenRenderer
            output_file_path = self.split_renderer.render_split_screen_video_ffmpeg(
                top_source=top_merged_path,
                bottom_source=bottom_merged_path,
                voice_audio_path=mixed_voice_audio,
                background_music_path=background_music_path,
                hook_text=hook_text,
                hook_duration=hook_duration,
                cta_text=cta_text,
                cta_start=cta_start,
                total_duration=TOTAL_AUDIO_DURATION,
                job_id=job_id,
                word_timestamps=word_timestamps,
                metadata=metadata,
                progress_callback=lambda pct: update_task_progress(str(job_id), "COMPOSITING", pct)
            )

            # Thay đổi mã băm MD5 để tránh nhận diện trùng lặp
            self.exporter.mutate_file_hash(output_file_path)

            # Dọn dẹp
            try:
                import shutil
                if temp_proc_dir.exists():
                    shutil.rmtree(temp_proc_dir, ignore_errors=True)
            except Exception:
                pass

            print(f"[MediaService Success] Split-screen render completed: {output_file_path}")
            return output_file_path

        except Exception as ffmpeg_error:
            print(f"[MediaService Warning] FFmpeg split-screen render failed: {ffmpeg_error}. Fallback to MoviePy...")
            try:
                import shutil
                if temp_proc_dir.exists():
                    shutil.rmtree(temp_proc_dir, ignore_errors=True)
            except Exception:
                pass
            return self._render_split_screen_video_moviepy_fallback(
                scenes_layout=scenes_layout,
                word_timestamps=word_timestamps,
                voice_audio_path=voice_audio_path,
                top_video_paths=top_video_paths,
                bottom_video_paths=bottom_video_paths,
                full_voice_script=full_voice_script,
                job_id=job_id,
                background_music_path=background_music_path,
                visual_style_plan=visual_style_plan,
                metadata=metadata,
                total_duration=TOTAL_AUDIO_DURATION,
                hook_text=hook_text,
                hook_duration=hook_duration,
                cta_text=cta_text,
                cta_start=cta_start
            )

    def _render_split_screen_video_moviepy_fallback(
        self,
        scenes_layout: list,
        word_timestamps: list,
        voice_audio_path: str,
        top_video_paths: list,
        bottom_video_paths: list,
        full_voice_script: str,
        job_id: int,
        background_music_path: str,
        visual_style_plan: dict,
        metadata: dict,
        total_duration: float,
        hook_text: str,
        hook_duration: float,
        cta_text: str,
        cta_start: float | None
    ) -> str:
        """
        MoviePy Fallback rendering for split-screen.
        """
        print("[MediaService] Running MoviePy split-screen fallback...")
        update_task_progress(str(job_id), "COMPOSITING", 0)

        sum_top_dur = sum([s.get("duration", 5) for s in scenes_layout])
        scale_top = total_duration / sum_top_dur if sum_top_dur > 0 else 1.0

        top_clips = []
        current_time = 0.0
        for idx, scene in enumerate(scenes_layout):
            dur = scene.get("duration", 5) * scale_top
            top_clip = self.composer.prepare_split_half_clip(
                source_path=top_video_paths[idx],
                total_duration=dur,
                y_position=0,
                darken=visual_style_plan.get("top_darken", True)
            )
            top_clips.append(top_clip)
            current_time += dur

        sum_bot_dur = sum([s.get("duration", 5) for s in scenes_layout])
        scale_bot = total_duration / sum_bot_dur if sum_bot_dur > 0 else 1.0

        bot_clips = []
        current_time = 0.0
        for idx, scene in enumerate(scenes_layout):
            dur = scene.get("duration", 5) * scale_bot
            bot_clip = self.composer.prepare_split_half_clip(
                source_path=bottom_video_paths[idx],
                total_duration=dur,
                y_position=960,
                darken=visual_style_plan.get("bottom_darken", False)
            )
            bot_clips.append(bot_clip)
            current_time += dur

        final_top = concatenate_videoclips(top_clips, method="compose")
        final_bot = concatenate_videoclips(bot_clips, method="compose")

        # Border divider configuration
        border_thick = 0
        border_color_code = "#000000"
        border_config_str = metadata.get("border_config") if metadata else None
        if border_config_str:
            try:
                parsed = json.loads(border_config_str)
                if isinstance(parsed, dict):
                    border_thick = int(parsed.get("thickness", 4))
                    border_color_code = parsed.get("color", "#000000")
            except Exception:
                pass

        bg_clips = [final_top, final_bot]
        if border_thick > 0:
            try:
                from moviepy.editor import ColorClip
            except ImportError:
                from moviepy import ColorClip

            rgb = self.sub_renderer._hex_or_rgba(border_color_code)[:3]
            divider = ColorClip(size=(1080, border_thick), color=rgb, duration=total_duration)
            divider = divider.with_position((0, 960 - border_thick // 2))
            bg_clips.append(divider)

        final_bg = CompositeVideoClip(bg_clips, size=(1080, 1920)).with_duration(total_duration)

        # Audio Mix
        final_audio = self.mixer.mix_audio_tracks(
            voice_audio_path=voice_audio_path,
            background_music_path=background_music_path,
            total_duration=total_duration,
            word_timestamps=word_timestamps,
            assets_dir=Path("worker/assets") if Path("worker/assets").exists() else Path("assets"),
            cut_points=None
        )
        final_bg = final_bg.with_audio(final_audio)

        # Subtitles overlays
        sub_temp_dir = ASSETS_DIR / f"split_subs_{job_id}"
        sub_temp_dir.mkdir(exist_ok=True)

        subtitle_clips = []
        subtitle_word_chunks = self.sub_renderer.group_words_into_chunks(
            word_timestamps,
            max_words=int(visual_style_plan.get("caption_max_words", 5)),
            max_gap_ms=int(visual_style_plan.get("caption_max_gap_ms", 520)),
        )

        sub_idx_global = 0
        for chunk in subtitle_word_chunks:
            for i, active_w in enumerate(chunk):
                try:
                    active_word_str = active_w["word"]
                    start_s = max(float(active_w["start_ms"]) / 1000.0, hook_duration)

                    if i < len(chunk) - 1:
                        end_s = float(chunk[i+1]["start_ms"]) / 1000.0
                    else:
                        end_s = float(chunk[-1]["end_ms"]) / 1000.0

                    duration = end_s - start_s
                    if duration <= 0:
                        continue

                    png_path = str(sub_temp_dir / f"sub_{sub_idx_global}.png")
                    self.sub_renderer._create_hormozi_subtitle_png(chunk, active_word_str, png_path, visual_style_plan=visual_style_plan, glow=False)

                    sub_clip = (
                        ImageClip(png_path)
                        .with_start(start_s)
                        .with_duration(duration)
                        .with_position((0, 0))
                    )
                    subtitle_clips.append(sub_clip)
                    sub_idx_global += 1
                except Exception as sub_err:
                    print(f"[MediaService Fallback Warning] Failed to render word chunk: {sub_err}")

        if hook_text:
            hook_path = str(sub_temp_dir / "hook_overlay.png")
            self.sub_renderer._create_text_overlay_png(hook_text, hook_path, visual_style_plan, "hook")
            subtitle_clips.append(
                ImageClip(hook_path)
                .with_start(0)
                .with_duration(min(hook_duration, total_duration))
                .with_position((0, 0))
            )

        if cta_text and total_duration > 5:
            cta_path = str(sub_temp_dir / "cta_overlay.png")
            self.sub_renderer._create_text_overlay_png(cta_text, cta_path, visual_style_plan, "cta")
            subtitle_clips.append(
                ImageClip(cta_path)
                .with_start(cta_start)
                .with_duration(min(3.0, total_duration - cta_start))
                .with_position((0, 0))
            )

        final_video = CompositeVideoClip([final_bg] + subtitle_clips, size=(1080, 1920)).with_duration(total_duration)
        output_file_path = str(OUTPUT_DIR / f"split_screen_short_{job_id}.mp4")
        temp_audio_path = str(ASSETS_DIR / f"temp_split_audio_{job_id}.m4a")

        self.exporter.export_video(
            final_video_clip=final_video,
            output_path=output_file_path,
            job_id=job_id,
            temp_audio_path=temp_audio_path
        )

        final_video.close()
        final_bg.close()
        final_top.close()
        final_bot.close()
        for c in top_clips + bot_clips:
            c.close()

        try:
            import shutil
            if sub_temp_dir.exists():
                shutil.rmtree(sub_temp_dir, ignore_errors=True)
        except Exception:
            pass

        return output_file_path
