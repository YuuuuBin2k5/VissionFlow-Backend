import json
from pathlib import Path

from worker.config import REACTIVE_RENDER_FPS
from worker.services.asset_service import AssetService
from worker.services.audio_signal_service import AudioSignalService
from worker.services.browser_render_service import BrowserRenderService
from worker.services.quality_gate_service import QualityGateService
from worker.services.reactive_template_service import ReactiveTemplateService
from worker.services.remix_service import RemixService
from worker.services.llm_service import LLMService
from worker.services.lyric_transcription_service import LyricTranscriptionService
from worker.services.music_viral_segment_advisor import MusicViralSegmentAdvisor
from worker.services.music_visual_planner_service import MusicVisualPlannerService
from worker.services.gemini_scenic_director_service import GeminiScenicDirectorService
from worker.services.scenic_beat_composer_service import ScenicBeatComposerService
from worker.services.trending_music_service import TrendingMusicService


class MusicReactiveService:
    def __init__(self):
        self.audio_signal = AudioSignalService()
        self.template = ReactiveTemplateService()
        self.browser_render = BrowserRenderService()
        self.quality_gate = QualityGateService()
        self.assets = AssetService()
        self.trending_music = TrendingMusicService()
        self.llm = LLMService()
        self.lyrics = LyricTranscriptionService()
        self.segment_advisor = MusicViralSegmentAdvisor()
        self.visual_planner = MusicVisualPlannerService()
        self.scenic_director = GeminiScenicDirectorService()
        self.scenic_composer = ScenicBeatComposerService()

    def render_music_reactive_video(self, job: dict, metadata: dict, job_id: int, progress=None) -> dict:
        # 1. Dọn dẹp bộ nhớ đệm (Cache Purge) của các file kết xuất cũ thuộc Job ID này
        import glob
        from worker.config import ASSETS_DIR
        
        # Xóa file HTML Canvas template cũ
        old_html = ASSETS_DIR / f"reactive_render_{job_id}.html"
        if old_html.exists():
            try:
                old_html.unlink()
                print(f"[MusicReactiveService] Purged old HTML template: {old_html}")
            except Exception as e:
                print(f"[MusicReactiveService Warning] Failed to purge HTML template: {e}")
                
        # Xóa dữ liệu FFT audio phân tích cũ
        old_json = ASSETS_DIR / f"audio_reactive_{job_id}.json"
        if old_json.exists():
            try:
                old_json.unlink()
                print(f"[MusicReactiveService] Purged old FFT data: {old_json}")
            except Exception as e:
                print(f"[MusicReactiveService Warning] Failed to purge FFT data: {e}")
                
        # Xóa toàn bộ tệp video nền cũ của cùng job_id này để giải phóng ổ đĩa và tránh cache cũ
        old_scenes = str(ASSETS_DIR / f"scene_{job_id}_*.mp4")
        for old_scene in glob.glob(old_scenes):
            try:
                Path(old_scene).unlink()
                print(f"[MusicReactiveService] Purged old background scene: {old_scene}")
            except Exception as e:
                print(f"[MusicReactiveService Warning] Failed to purge scene: {e}")

        old_portraits = str(ASSETS_DIR / f"portrait_{job_id}_*.jpg")
        for old_portrait in glob.glob(old_portraits):
            try:
                Path(old_portrait).unlink()
                print(f"[MusicReactiveService] Purged old portrait asset: {old_portrait}")
            except Exception as e:
                print(f"[MusicReactiveService Warning] Failed to purge portrait: {e}")

        # Xóa tệp remix âm thanh cũ nếu có
        old_remix = ASSETS_DIR / f"remix_{job_id}.wav"
        if old_remix.exists():
            try:
                old_remix.unlink()
                print(f"[MusicReactiveService] Purged old remix audio: {old_remix}")
            except Exception as e:
                print(f"[MusicReactiveService Warning] Failed to purge remix audio: {e}")

        requested_render_mode = metadata.get("render_mode") or "music_reactive"
        provided_audio_path = metadata.get("audio_path") or job.get("audio_file_path")
        has_provided_audio = bool(provided_audio_path and Path(str(provided_audio_path)).exists())
        is_standalone = (metadata.get("is_standalone_music_video") and not has_provided_audio) or (
            requested_render_mode == "music_reactive" and not has_provided_audio
        )
        metadata.setdefault("require_tiktok_music", True)
        metadata.setdefault("tiktok_sound_volume_percent", 2)
        metadata.setdefault("original_video_volume_percent", 100)
        metadata.setdefault("lyric_captions_required", bool(metadata.get("requires_user_audio")))

        if metadata.get("requires_user_audio") and not has_provided_audio:
            raise RuntimeError("Video âm nhạc này đang chờ file audio thật từ người dùng trước khi render.")

        if is_standalone:
            song_title = metadata.get("song_title") or "HOT TRENDING"
            artist_name = metadata.get("artist_name") or "AUTO DETECT"

            if song_title == "HOT TRENDING" or artist_name == "AUTO DETECT":
                if progress:
                    progress("BOT_RECEIVE", "Đang kết nối hệ thống cào và truy tìm bài hát xu hướng thịnh hành...")
                resolved_title, resolved_artist, resolved_mood = self.trending_music.resolve_trending_song_for_topic(
                    job.get("topic") or "Nhạc Việt Hot Trend TikTok",
                    None if song_title == "HOT TRENDING" else song_title
                )
                song_title = resolved_title
                artist_name = resolved_artist
                metadata["song_title"] = song_title
                metadata["artist_name"] = artist_name
                metadata["mood"] = resolved_mood

            if progress:
                progress("AI_CREATIVE", f"Gemini đang phân tích sắc thái cảm nhận cho bài hát: '{song_title}'...")

            mood_analysis = self.llm.analyze_music_mood(song_title, artist_name)
            mood = mood_analysis.get("mood", "COZY_CHILL")
            caption = mood_analysis.get("caption", f"Lắng nghe những giai điệu từ {song_title}...")
            visual_keywords = mood_analysis.get("visual_keywords", "aesthetic background vertical")

            metadata["mood"] = mood
            metadata["caption"] = caption
            metadata["visual_keywords"] = visual_keywords

            if progress:
                progress("SIGNAL_PROCESSING", f"Tải tệp âm thanh Premium chuẩn cho mood: '{mood}'...")

            resolved_audio_path = self.trending_music.download_mood_audio(mood, job_id)
            metadata["audio_path"] = resolved_audio_path
            metadata["render_audio_source"] = "safe_placeholder"
            metadata["tiktok_music_strategy"] = "add_exact_sound_at_publish"
            audio_path = resolved_audio_path
        else:
            audio_path = provided_audio_path
            if not audio_path or not Path(audio_path).exists():
                raise RuntimeError(
                    "Music reactive render requires an existing audio file. Set audio_file_path or scenes_layout_json.audio_path first."
                )
            metadata["audio_path"] = str(audio_path)
            metadata["render_audio_source"] = "provided_audio"

            # Tự động khớp nhạc thực tế nếu thông tin bài hát đang bị mock hoặc lấy từ video_title_idea
            temp_title = metadata.get("song_title") or job.get("video_title_idea") or f"Music Reactive #{job_id}"
            temp_artist = metadata.get("artist_name") or "AgentTiktok"

            is_mocked = (
                temp_title == job.get("video_title_idea") or
                temp_title == "HOT TRENDING" or
                temp_artist in ("AgentTiktok", "AgentTiktok Remix", "AUTO DETECT")
            )

            if is_mocked and not metadata.get("song_resolved"):
                if progress:
                    progress("AI_CREATIVE", "Tự động phân tích chủ đề video để khớp với bài hát TikTok Trend phù hợp...")
                topic = job.get("topic") or job.get("video_title_idea") or "Lofi chill"
                resolved_song, resolved_artist, resolved_mood = self.trending_music.resolve_trending_song_for_topic(topic, temp_title)
                
                metadata["song_title"] = resolved_song
                metadata["artist_name"] = resolved_artist
                metadata["mood"] = resolved_mood
                metadata["song_resolved"] = True

        if requested_render_mode == "music_remix_reactive":
            if not metadata.get("rights_confirmed"):
                raise RuntimeError(
                    "Music remix requires rights_confirmed=true in metadata. The user must confirm they can use/remix this audio."
                )
            if progress:
                progress("REMIX_AUDIO", "Phân tích tempo và tạo bản remix thêm bass/drum an toàn...")
            source_audio_path = metadata.get("source_audio_path") or job.get("audio_file_path") or audio_path
            if Path(str(source_audio_path)).name.startswith("remix_") and job.get("audio_file_path"):
                source_audio_path = job.get("audio_file_path")
            remix_result = RemixService().create_remix(source_audio_path, job_id, metadata)
            metadata.update(remix_result)
            audio_path = remix_result["remix_audio_path"]

        mood = metadata.get("mood") or metadata.get("music_mood") or "FOCUS_LOFI"
        song_title = metadata.get("song_title") or job.get("video_title_idea") or f"Music Reactive #{job_id}"
        artist_name = metadata.get("artist_name") or "AgentTiktok"
        caption = metadata.get("caption") or job.get("hook_text_3s") or "Chill audio-reactive visual"

        caption_timeline = metadata.get("caption_timeline")
        selected_viral_segment = metadata.get("selected_viral_segment")
        if metadata.get("auto_select_viral_segment") and metadata.get("render_audio_source") == "provided_audio":
            if progress:
                progress("SIGNAL_PROCESSING", "Gemini đang nghe nhạc và gợi ý đoạn hook/điệp khúc viral...")
            gemini_segment_hint = metadata.get("gemini_viral_segment_hint")
            if not gemini_segment_hint:
                try:
                    gemini_segment_hint = self.segment_advisor.suggest_segment(audio_path, song_title, artist_name)
                except Exception as advisor_error:
                    print(f"[MusicReactiveService Warning] Gemini viral segment hint failed: {advisor_error}")

            if progress:
                progress("SIGNAL_PROCESSING", "Phân tích năng lượng audio và chốt đoạn viral không cắt cụt cao trào...")
            selected_viral_segment = self.audio_signal.select_viral_segment(
                audio_path,
                advisor_hint=gemini_segment_hint,
            )
            audio_path = self.audio_signal.trim_audio_segment(audio_path, job_id, selected_viral_segment)
            if progress:
                progress("SIGNAL_PROCESSING", "Nhận diện lời hát và tạo lyric caption đồng bộ theo giọng ca...")
            try:
                caption_timeline = self.lyrics.transcribe_lyrics(audio_path)
            except Exception:
                if metadata.get("lyric_captions_required"):
                    raise
                caption_timeline = self.audio_signal.build_caption_timeline(caption, selected_viral_segment)
            metadata["selected_viral_segment"] = selected_viral_segment
            metadata["gemini_viral_segment_hint"] = gemini_segment_hint
            metadata["caption_timeline"] = caption_timeline
            metadata["viral_segment_audio_path"] = audio_path
            metadata["caption_mode"] = "synced_lyrics"

        if progress:
            progress("SIGNAL_PROCESSING", "Trích xuất bass/mid/treble energy từ audio...")
        audio_data_path = self.audio_signal.extract_to_json(audio_path, job_id, fps=REACTIVE_RENDER_FPS)
        audio_data = json.loads(Path(audio_data_path).read_text(encoding="utf-8"))

        visual_plan = metadata.get("visual_plan") or self.visual_planner.build_plan(
            metadata=metadata,
            mood=mood,
            song_title=song_title,
            artist_name=artist_name,
            audio_data=audio_data,
        )
        if visual_plan.get("visual_mode") == "scenic_beat_cut" and not visual_plan.get("scenic_keywords"):
            scenic_plan = self.scenic_director.suggest_scenic_plan(
                song_title=song_title,
                artist_name=artist_name,
                caption_timeline=caption_timeline,
                selected_viral_segment=selected_viral_segment or {},
                mood=mood,
            )
            visual_plan["scenic_keywords"] = scenic_plan.get("scenic_keywords", [])
            visual_plan["visual_story"] = scenic_plan.get("visual_story", "")
            visual_plan["color_grade"] = scenic_plan.get("color_grade") or visual_plan.get("color_grade")
            visual_plan["render_strategy"] = "ffmpeg_scenic_overlay"
            visual_plan["scenic_director"] = scenic_plan
        if progress:
            progress("ASSET_DOWNLOAD", f"Tải visual assets cho mode {visual_plan.get('visual_mode')}...")
        visual_assets = self._prepare_visual_assets(job_id, metadata, visual_plan)
        background_path = visual_assets.get("background_video_path")

        if visual_plan.get("visual_mode") == "scenic_beat_cut":
            if progress:
                progress("WEB_DOM_BUILD", "Dựng nền phong cảnh theo beat bằng FFmpeg và render lyric overlay trong suốt...")
            scenic_result = self._render_scenic_beat_cut(
                job_id=job_id,
                audio_path=audio_path,
                audio_data=audio_data,
                caption_timeline=caption_timeline,
                selected_viral_segment=selected_viral_segment,
                mood=mood,
                song_title=song_title,
                artist_name=artist_name,
                caption=caption,
                visual_plan=visual_plan,
                visual_assets=visual_assets,
                progress=progress,
            )
            metadata.update({
                "render_mode": requested_render_mode,
                "mood": mood,
                "audio_path": audio_path,
                "selected_viral_segment": selected_viral_segment,
                "caption_timeline": caption_timeline,
                "require_tiktok_music": metadata.get("require_tiktok_music", True),
                "tiktok_sound_volume_percent": metadata.get("tiktok_sound_volume_percent", 2),
                "original_video_volume_percent": metadata.get("original_video_volume_percent", 100),
                "audio_reactive_data_path": audio_data_path,
                "visual_mode": visual_plan.get("visual_mode"),
                "effect_intensity": visual_plan.get("effect_intensity"),
                "color_grade": visual_plan.get("color_grade"),
                "visual_plan": visual_plan,
                "visual_assets": visual_assets,
                "beat_events": audio_data.get("beat_events", []),
                "cut_events": audio_data.get("cut_events", []),
                "drop_events": audio_data.get("drop_events", []),
                **scenic_result["metadata"],
            })
            return {
                "video_path": scenic_result["video_path"],
                "metadata": metadata,
            }

        if progress:
            progress("WEB_DOM_BUILD", "Tạo HTML Canvas/WebGL template cho music reactive render...")
        html_path = self.template.create_template(
            job_id=job_id,
            song_title=song_title,
            artist_name=artist_name,
            caption=caption,
            mood=mood,
            background_video_path=background_path,
            audio_data=audio_data,
            caption_timeline=caption_timeline,
            visual_plan=visual_plan,
            visual_assets=visual_assets,
        )
        if progress:
            progress("STREAM_RENDERING", "Chụp frame bằng Playwright và encode sang MP4 bằng FFmpeg...")
        video_path = self.browser_render.render_html_to_video(
            html_path=html_path,
            audio_path=audio_path,
            audio_data=audio_data,
            job_id=job_id,
            fps=REACTIVE_RENDER_FPS,
        )
        if progress:
            progress("QUALITY_CHECK", "Kiểm tra dung lượng, duration sync và blackout frame...")
        self.quality_gate.validate_video(video_path, audio_path, job_id)

        metadata.update({
            "render_mode": requested_render_mode,
            "mood": mood,
            "audio_path": audio_path,
            "selected_viral_segment": selected_viral_segment,
            "caption_timeline": caption_timeline,
            "require_tiktok_music": metadata.get("require_tiktok_music", True),
            "tiktok_sound_volume_percent": metadata.get("tiktok_sound_volume_percent", 2),
            "original_video_volume_percent": metadata.get("original_video_volume_percent", 100),
            "audio_reactive_data_path": audio_data_path,
            "background_video_path": background_path,
            "visual_mode": visual_plan.get("visual_mode"),
            "effect_intensity": visual_plan.get("effect_intensity"),
            "color_grade": visual_plan.get("color_grade"),
            "visual_plan": visual_plan,
            "visual_assets": visual_assets,
            "beat_events": audio_data.get("beat_events", []),
            "cut_events": audio_data.get("cut_events", []),
            "drop_events": audio_data.get("drop_events", []),
            "reactive_template_path": html_path,
        })

        return {
            "video_path": video_path,
            "metadata": metadata,
        }

    def _prepare_visual_assets(self, job_id: int, metadata: dict, visual_plan: dict) -> dict:
        existing_assets = metadata.get("visual_assets")
        if isinstance(existing_assets, dict):
            if self._visual_assets_exist(existing_assets, visual_plan.get("visual_mode")):
                return existing_assets

        visual_mode = visual_plan.get("visual_mode") or "portrait_lyric"
        keywords = visual_plan.get("asset_keywords") or metadata.get("visual_keywords") or "aesthetic vertical"

        if visual_mode == "scenic_beat_cut":
            scenic_keywords = visual_plan.get("scenic_keywords") or visual_plan.get("asset_keywords") or keywords
            video_paths = self.assets.search_and_download_scenic_videos(scenic_keywords, job_id, target_count=6)
            return {
                "background_video_path": video_paths[0],
                "background_video_paths": video_paths,
            }

        if visual_mode == "beat_cut_video":
            video_paths = self.assets.search_and_download_videos(keywords, job_id, count=5)
            return {
                "background_video_path": video_paths[0],
                "background_video_paths": video_paths,
            }

        try:
            portrait_path = self.assets.search_and_download_image(
                visual_plan.get("portrait_keywords") or keywords,
                job_id,
            )
            background_video_path = self.assets.search_and_download_video(keywords, job_id)
            return {
                "portrait_image_path": portrait_path,
                "background_video_path": background_video_path,
                "background_video_paths": [background_video_path],
            }
        except Exception as portrait_error:
            print(f"[MusicReactiveService Warning] Portrait visual failed, falling back to beat-cut video: {portrait_error}")
            visual_plan["visual_mode"] = "beat_cut_video"
            video_paths = self.assets.search_and_download_videos(keywords, job_id, count=5)
            return {
                "background_video_path": video_paths[0],
                "background_video_paths": video_paths,
                "portrait_fallback_reason": str(portrait_error),
            }

    def _visual_assets_exist(self, assets: dict, visual_mode: str | None = None) -> bool:
        if visual_mode == "portrait_lyric" and assets.get("portrait_image_path"):
            return Path(str(assets["portrait_image_path"])).exists()

        paths = []
        if assets.get("portrait_image_path"):
            paths.append(assets["portrait_image_path"])
        if assets.get("background_video_path"):
            paths.append(assets["background_video_path"])
        paths.extend(assets.get("background_video_paths") or [])
        return bool(paths) and all(Path(str(path)).exists() for path in paths if path)

    def _render_scenic_beat_cut(
        self,
        job_id: int,
        audio_path: str,
        audio_data: dict,
        caption_timeline: list,
        selected_viral_segment: dict,
        mood: str,
        song_title: str,
        artist_name: str,
        caption: str,
        visual_plan: dict,
        visual_assets: dict,
        progress=None,
    ) -> dict:
        scenic_plan = visual_plan.get("scenic_director") or {
            "scenic_keywords": visual_plan.get("scenic_keywords", []),
            "visual_story": visual_plan.get("visual_story", ""),
            "color_grade": visual_plan.get("color_grade"),
            "scenic_director_source": "metadata",
        }

        if not visual_assets.get("background_video_paths"):
            visual_assets.update(self._prepare_visual_assets(job_id, {"visual_assets": {}}, visual_plan))

        duration = float(audio_data.get("duration") or len(audio_data.get("bass", [])) / max(1, audio_data.get("fps", REACTIVE_RENDER_FPS)))
        if progress:
            progress("STREAM_RENDERING", "FFmpeg đang nối video phong cảnh theo beat/cut-points...")
        background_result = self.scenic_composer.compose_background(
            background_video_paths=visual_assets.get("background_video_paths", []),
            cut_events=audio_data.get("cut_events", []),
            duration=duration,
            job_id=job_id,
            effect_intensity=visual_plan.get("effect_intensity", "soft"),
            color_grade=visual_plan.get("color_grade", "soft_lofi"),
        )

        if progress:
            progress("STREAM_RENDERING", "Playwright đang render lyric/effect overlay trong suốt...")
        html_path = self.template.create_template(
            job_id=job_id,
            song_title=song_title,
            artist_name=artist_name,
            caption=caption,
            mood=mood,
            background_video_path=visual_assets.get("background_video_path", ""),
            audio_data=audio_data,
            caption_timeline=caption_timeline,
            visual_plan=visual_plan,
            visual_assets=visual_assets,
            template_mode="transparent_overlay",
        )
        overlay_path = self.browser_render.render_html_to_transparent_overlay(
            html_path=html_path,
            audio_data=audio_data,
            job_id=job_id,
            fps=REACTIVE_RENDER_FPS,
        )

        if progress:
            progress("STREAM_RENDERING", "FFmpeg đang overlay lyric trong suốt lên nền phong cảnh...")
        video_path = self.scenic_composer.overlay_with_audio(
            background_path=background_result["background_composite_path"],
            overlay_path=overlay_path,
            audio_path=audio_path,
            job_id=job_id,
            duration=duration,
        )
        if progress:
            progress("QUALITY_CHECK", "Kiểm tra scenic beat-cut output...")
        self.quality_gate.validate_video(video_path, audio_path, job_id)

        return {
            "video_path": video_path,
            "metadata": {
                "reactive_template_path": html_path,
                "overlay_path": overlay_path,
                "background_composite_path": background_result["background_composite_path"],
                "scene_timeline": background_result["scene_timeline"],
                "scenic_keywords": scenic_plan.get("scenic_keywords", []),
                "scenic_director": scenic_plan,
                "render_strategy": "ffmpeg_scenic_overlay",
            },
        }
