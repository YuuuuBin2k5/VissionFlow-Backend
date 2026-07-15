"""
Standard Render Strategy
=========================
Pipeline render video tiêu chuẩn (Standard + Split Screen).
Di chuyển từ phần còn lại của handle_render() trong render_use_case.py cũ.
Tách thành các method nhỏ theo từng giai đoạn để dễ đọc và bảo trì.
"""
from __future__ import annotations

import json
import os

from worker.application.render_strategies.base import RenderStrategy
from worker.config import ASSETS_DIR, OUTPUT_DIR
from worker.domain.job_metadata import parse_job_metadata, parse_voice_flag
from worker.domain.render_contract import RenderContract
from worker.infrastructure.database import log_realtime_progress
from worker.infrastructure.repositories import VideoJobRepository
from worker.services.cockpit_bridge import update_task_progress


class StandardRenderStrategy(RenderStrategy):
    """
    Strategy mặc định cho pipeline Standard và Split Screen Shorts.
    Được chọn khi không có strategy nào khớp trước đó (fallback cuối cùng).
    """

    def can_handle(self, contract: RenderContract) -> bool:
        # Fallback — luôn xử lý được (phải đặt cuối trong registry)
        return True

    async def execute(self, job: dict, contract: RenderContract) -> str:
        job_id = contract.job_id
        repo = VideoJobRepository()
        metadata = parse_job_metadata(job)
        split_screen_mode = contract.is_split_screen

        # ── B2: LLM Script Generation ─────────────────────────────────────────
        details, hook, full_script, scenes_layout, seo_tags, voice_code = await self._run_llm(
            job, metadata, contract, repo
        )

        # ── B4: TTS Audio Synthesis ───────────────────────────────────────────
        audio_path = await self._run_tts(job_id, full_script, voice_code, seo_tags, repo)

        # ── B5: Asset Download ────────────────────────────────────────────────
        bg_video_paths, bottom_video_paths = await self._download_assets(
            job_id, job, details, metadata, scenes_layout, split_screen_mode, seo_tags, repo
        )

        # ── B6-B7: Video Render + Export ──────────────────────────────────────
        final_path = self._render_video(
            job_id, split_screen_mode, scenes_layout, details,
            hook, full_script, audio_path,
            bg_video_paths, bottom_video_paths,
            metadata, seo_tags
        )

        # ── Lưu kết quả ──────────────────────────────────────────────────────
        repo.save_render_result(job_id, final_path, seo_tags)
        log_realtime_progress(job_id, "VIDEO_RENDER", "SUCCESS",
                              f"Video đã render thành công! Đường dẫn: {final_path}")
        return final_path

    # ──────────────────────────────────────────────────────────────────────────
    # Private stage methods
    # ──────────────────────────────────────────────────────────────────────────

    async def _run_llm(self, job: dict, metadata: dict, contract: RenderContract, repo: VideoJobRepository):
        """Giai đoạn B2: Sinh kịch bản từ LLM."""
        job_id = contract.job_id
        split_screen_mode = contract.is_split_screen

        topic = job.get("topic") or ""
        audience = job.get("target_audience") or "Mọi đối tượng"
        title_idea = job.get("video_title_idea") or ""

        music_mood = "educational"
        content_category = ""
        is_long_philosophy = False
        existing_metadata: dict = {}
        video_language = "en" if str(job.get("video_language") or "vi").lower().startswith("en") else "vi"
        voice_code = job.get("voice_profile") or ("edge-en-guy" if video_language == "en" else "edge-nam-minh")

        if job.get("scenes_layout_json"):
            try:
                existing = job["scenes_layout_json"]
                existing = json.loads(existing) if isinstance(existing, str) else existing
                if isinstance(existing, dict):
                    existing_metadata = existing
                    music_mood = existing.get("music_mood", "educational")
                    content_category = existing.get("content_category", "")
                    is_long_philosophy = existing.get("is_long_philosophy", False)
                    voice_code = job.get("voice_profile") or existing.get("voice_code") or voice_code
                    if existing.get("original_philosophy"):
                        topic = existing["original_philosophy"]
            except Exception:
                pass

        topic, topic_voice_code = parse_voice_flag(topic)
        if "voice_code" not in existing_metadata and not job.get("voice_profile"):
            voice_code = topic_voice_code

        existing_metadata["video_language"] = video_language
        existing_metadata["subtitle_language"] = video_language

        log_realtime_progress(job_id, "LLM_SCRIPT", "INFO",
                              f"Bắt đầu biên soạn kịch bản cho Job #{job_id}...")

        if split_screen_mode:
            from worker.services.model_router import ModelRouter
            log_realtime_progress(job_id, "MODEL_ROUTER", "INFO", "Kích hoạt ModelRouter cho split-screen...")
            details = ModelRouter().generate_split_screen_details(
                topic=topic, title_idea=title_idea,
                audience=audience, metadata=existing_metadata,
            )
        else:
            from worker.services.llm_service import LLMService
            details = LLMService().generate_video_details(
                day_number=job.get("day_number"),
                topic=topic, title_idea=title_idea, audience=audience,
                music_mood=music_mood, content_category=content_category,
                is_long_philosophy=is_long_philosophy, video_language=video_language,
            )

        try:
            update_task_progress(str(job_id), "SCRIPT", 100)
        except Exception:
            pass

        hook = details.get("hook_text_3s", "")
        full_script = details.get("full_voice_script", "")
        scenes_layout = details.get("scenes_layout_json", [])
        seo_tags: dict = details.get("seo_tags_metadata", {}) or {}

        # Copy YouTube-specific fields
        for yt_key in ["youtube_title_options", "youtube_scannable_description",
                       "youtube_hashtags", "youtube_api_tags"]:
            if yt_key in details:
                seo_tags[yt_key] = details[yt_key]

        pinned_comment = details.get("pinned_comment", "")
        caption_seo = details.get("caption_seo", "")
        if pinned_comment:
            seo_tags["pinned_comment"] = pinned_comment
        if caption_seo:
            seo_tags["caption_seo"] = caption_seo

        hashtags: list = seo_tags.get("hashtags", [])
        if isinstance(hashtags, list) and "#YuuBin" not in hashtags and "YuuBin" not in hashtags:
            hashtags.append("#YuuBin")
            seo_tags["hashtags"] = hashtags

        # Visual style + Retention planning
        from worker.services.video_style_director_service import VideoStyleDirectorService
        from worker.services.retention_director_service import RetentionDirectorService
        style_director = VideoStyleDirectorService()
        retention_director = RetentionDirectorService()
        visual_style_plan = style_director.build_campaign_plan(existing_metadata, details, job)
        visual_style_plan["video_language"] = video_language
        visual_style_plan["subtitle_language"] = video_language
        retention_plan = retention_director.build_campaign_plan(existing_metadata, details, job, visual_style_plan)
        visual_style_plan["retention_plan"] = retention_plan
        visual_style_plan["hook_text"] = retention_plan["selected_hook"]
        hook = retention_plan["selected_hook"]
        seo_tags["visual_style_plan"] = visual_style_plan
        seo_tags["retention_plan"] = retention_plan

        # Chọn nhạc nền
        background_music_path = None
        selected_music_metadata: dict = {}
        try:
            log_realtime_progress(job_id, "MUSIC_MATCH", "INFO", "Đang chọn nhạc nền khớp với mood kịch bản...")
            from worker.application.render_use_case import resolve_script_background_music
            background_music_path, selected_music_metadata = resolve_script_background_music(
                job, details, music_mood, job_id
            )
            seo_tags["selected_music"] = selected_music_metadata
            log_realtime_progress(job_id, "MUSIC_MATCH", "SUCCESS",
                                  f"Nhạc: {selected_music_metadata.get('song_title')} - {selected_music_metadata.get('artist_name')}")
        except Exception as music_error:
            log_realtime_progress(job_id, "MUSIC_MATCH", "WARN",
                                  f"Không chọn được nhạc theo kịch bản: {music_error}")

        seo_tags["voice_code"] = voice_code
        seo_tags["background_music_path"] = background_music_path
        seo_tags["selected_music_metadata"] = selected_music_metadata
        seo_tags["existing_metadata"] = existing_metadata
        seo_tags["visual_style_plan_full"] = visual_style_plan

        # Lưu kịch bản vào DB
        scenes_payload_for_db = scenes_layout
        if split_screen_mode:
            scenes_payload_for_db = {
                **existing_metadata,
                "top_asset_strategy": existing_metadata.get("top_asset_strategy", "local_first_long_process"),
                "top_min_duration_seconds": existing_metadata.get("top_min_duration_seconds", 60),
                "bottom_visual_type": existing_metadata.get("bottom_visual_type", "daily_life"),
                "bottom_asset_strategy": existing_metadata.get("bottom_asset_strategy", "local_first_motion_background"),
                "subtitle_strategy": existing_metadata.get("subtitle_strategy", "tts_timestamp_with_estimated_fallback"),
                "hook_text_3s": hook,
                "cta_text": details.get("cta_text", ""),
                "scenes_layout": scenes_layout,
            }

        repo.save_script_result(job_id, hook, full_script, scenes_payload_for_db, seo_tags)
        log_realtime_progress(job_id, "LLM_SCRIPT", "INFO",
                              f"Kịch bản hoàn thành! Hook: '{hook[:40]}...'")
        return details, hook, full_script, scenes_layout, seo_tags, voice_code

    async def _run_tts(
        self, job_id: int, full_script: str, voice_code: str, seo_tags: dict, repo: VideoJobRepository
    ) -> str:
        """Giai đoạn B4: Sinh file âm thanh TTS."""
        log_realtime_progress(job_id, "AUDIO_SYNTH", "INFO",
                              f"Khởi chạy Voice Profile Engine với giọng '{voice_code}'...")
        audio_path = str(ASSETS_DIR / f"voice_{job_id}.mp3")

        from worker.services.media_service import MediaService
        media_svc = MediaService()
        word_timestamps = await media_svc.generate_tts(full_script, audio_path, voice_code)

        try:
            update_task_progress(str(job_id), "AUDIO", 100)
        except Exception:
            pass

        repo.save_audio_path(job_id, audio_path)
        # Lưu timestamps vào seo_tags để _render_video dùng
        seo_tags["_word_timestamps"] = word_timestamps
        return audio_path

    async def _download_assets(
        self, job_id, job, details, metadata, scenes_layout, split_screen_mode, seo_tags, repo
    ):
        """Giai đoạn B5: Tải video nền (top + bottom cho split screen)."""
        existing_metadata: dict = seo_tags.get("existing_metadata", metadata)
        asset_count_text = (
            f"{len(scenes_layout)} phân cảnh split-screen"
            if split_screen_mode
            else f"{len(scenes_layout)} phân cảnh video nền"
        )
        log_realtime_progress(job_id, "ASSET_DOWNLOAD", "INFO",
                              f"Bắt đầu tải {asset_count_text}...")

        from worker.services.asset_service import AssetService
        from worker.services.local_asset_library_service import LocalAssetLibraryService
        asset_downloader = AssetService()
        bg_video_paths = []
        bottom_video_paths = []

        if split_screen_mode:
            bg_video_paths, bottom_video_paths = await self._download_split_screen_assets(
                job_id, existing_metadata, details, scenes_layout,
                asset_downloader, LocalAssetLibraryService, seo_tags
            )
        else:
            bg_video_paths = self._download_standard_assets(
                job_id, scenes_layout, asset_downloader
            )

        repo.mark_assets_ready(job_id)
        return bg_video_paths, bottom_video_paths

    def _download_standard_assets(self, job_id, scenes_layout, asset_downloader) -> list:
        """Tải asset cho pipeline standard (1 layer)."""
        bg_video_paths = []
        total = len(scenes_layout)
        for idx, scene in enumerate(scenes_layout):
            scene_id = scene.get("scene_id", 1)
            keywords = scene.get("visual_search_keywords", "vertical background")
            try:
                path = asset_downloader.search_and_download_video(keywords, scene_id)
                bg_video_paths.append(path)
            except Exception as ae:
                log_realtime_progress(job_id, "ASSET_DOWNLOAD", "WARN",
                                      f"Lỗi tải scene {scene_id}: {ae}. Dùng fallback...")
                try:
                    path = asset_downloader.search_and_download_video("abstract vertical", scene_id)
                    bg_video_paths.append(path)
                except Exception as ae2:
                    if bg_video_paths:
                        bg_video_paths.append(bg_video_paths[-1])
                    else:
                        raise ae2
            try:
                update_task_progress(str(job_id), "ASSET", int(((idx + 1) / total) * 100))
            except Exception:
                pass
        return bg_video_paths

    async def _download_split_screen_assets(
        self, job_id, existing_metadata, details, scenes_layout,
        asset_downloader, LocalAssetLibraryService, seo_tags
    ):
        """Tải asset cho pipeline split screen (top + bottom layers)."""
        # Import helper từ render_use_case cũ để tái sử dụng
        from worker.application.render_use_case import _resolve_split_screen_assets
        return await _resolve_split_screen_assets(
            job_id, existing_metadata, details, scenes_layout,
            asset_downloader, LocalAssetLibraryService(), seo_tags
        )

    def _render_video(
        self, job_id, split_screen_mode, scenes_layout, details,
        hook, full_script, audio_path,
        bg_video_paths, bottom_video_paths,
        metadata, seo_tags
    ) -> str:
        """Giai đoạn B6-B7: Render video cuối cùng với MoviePy."""
        log_realtime_progress(job_id, "VIDEO_RENDER", "INFO",
                              "Khởi động Graphic & Subtitle Engine...")

        from worker.services.media_service import MediaService
        media_engine = MediaService()
        visual_style_plan: dict = seo_tags.get("visual_style_plan_full", {})
        existing_metadata: dict = seo_tags.get("existing_metadata", metadata)
        background_music_path = seo_tags.get("background_music_path")
        word_timestamps = seo_tags.pop("_word_timestamps", [])

        import gc
        try:
            if split_screen_mode:
                final_path = media_engine.render_split_screen_video(
                    scenes_layout=scenes_layout,
                    word_timestamps=word_timestamps,
                    voice_audio_path=audio_path,
                    top_video_paths=bg_video_paths,
                    bottom_video_paths=bottom_video_paths,
                    full_voice_script=full_script,
                    job_id=job_id,
                    background_music_path=background_music_path,
                    visual_style_plan=visual_style_plan,
                    metadata={
                        **existing_metadata,
                        "hook_text_3s": hook,
                        "cta_text": details.get("cta_text", ""),
                        "top_asset_strategy": existing_metadata.get("top_asset_strategy", "local_first_long_process"),
                        "top_min_duration_seconds": existing_metadata.get("top_min_duration_seconds", 60),
                        "bottom_visual_type": existing_metadata.get("bottom_visual_type", "daily_life"),
                        "bottom_asset_strategy": existing_metadata.get("bottom_asset_strategy", "local_first_motion_background"),
                        "subtitle_strategy": existing_metadata.get("subtitle_strategy", "tts_timestamp_with_estimated_fallback"),
                    },
                )
            else:
                final_path = media_engine.render_final_video(
                    scenes_layout=scenes_layout,
                    word_timestamps=word_timestamps,
                    voice_audio_path=audio_path,
                    background_video_paths=bg_video_paths,
                    job_id=job_id,
                    background_music_path=background_music_path,
                    visual_style_plan=visual_style_plan,
                    full_voice_script=full_script,
                )

            # Cập nhật quality scores vào seo_tags
            seo_tags["quality_score"] = visual_style_plan.get("quality_score")
            seo_tags["quality_warnings"] = visual_style_plan.get("quality_warnings", [])
            seo_tags["quality_passed"] = visual_style_plan.get("quality_passed")
            return final_path

        except Exception as render_err:
            gc.collect()
            log_realtime_progress(job_id, "VIDEO_RENDER", "ERROR",
                                  f"Lỗi render MoviePy: {render_err}. Giải phóng RAM...")
            raise
