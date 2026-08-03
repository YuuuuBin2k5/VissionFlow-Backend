"""
Dubbing / Translation Render Strategy
=======================================
Xử lý render video lồng tiếng tự động (AI Dubbing).
Di chuyển từ handle_translate_dub_render() trong render_use_case.py cũ.
"""
from __future__ import annotations

import asyncio
import json
import os

from worker.application.render_strategies.base import RenderStrategy
from worker.domain.render_contract import RenderContract, RenderMode
from worker.infrastructure.database import log_realtime_progress
from worker.infrastructure.repositories import VideoJobRepository
from worker.config import OUTPUT_DIR
from worker.infrastructure.douyin_client import download_video_link


class DubbingStrategy(RenderStrategy):
    """
    Strategy cho pipeline lồng tiếng AI tự động.
    Áp dụng khi: render_mode = TRANSLATE_DUB hoặc title bắt đầu bằng [DUB].
    """

    def can_handle(self, contract: RenderContract) -> bool:
        return contract.is_translate_dub

    async def execute(self, job: dict, contract: RenderContract) -> str:
        from worker.services.dubbing_service import DubbingService
        from worker.services.llm_service import LLMService
        from worker.domain.job_metadata import parse_job_metadata

        job_id = contract.job_id
        metadata = parse_job_metadata(job)
        repo = VideoJobRepository()

        log_realtime_progress(job_id, "DUBBING_PIPELINE", "INFO",
                              "Bắt đầu khởi chạy bộ xử lý lồng tiếng AI...")

        source_path = metadata.get("dub_source_path")
        source_url = metadata.get("dub_source_url")
        original_video_title = metadata.get("original_video_title")

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        output_filename = f"dubbed_{job_id}_{int(asyncio.get_event_loop().time())}.mp4"
        output_path = os.path.join(OUTPUT_DIR, output_filename)

        # Tải video nếu người dùng gửi link
        if source_url and not source_path:
            log_realtime_progress(job_id, "DUBBING_PIPELINE", "INFO",
                                  f"Phát hiện link video. Đang tải từ: {source_url}...")
            try:
                source_path, original_video_title = await download_video_link(job_id, source_url, OUTPUT_DIR)
                metadata["dub_source_path"] = source_path
                if original_video_title:
                    metadata["original_video_title"] = original_video_title
            except Exception as err:
                log_realtime_progress(job_id, "DUBBING_PIPELINE", "ERROR",
                                      f"Không thể tải video từ link: {err}")
                raise

        if not source_path or not os.path.exists(source_path):
            raise FileNotFoundError(
                f"Không tìm thấy file video nguồn để lồng tiếng: {source_path}"
            )

        voice_gender = metadata.get("voice_gender") or "female"
        source_language = "auto"
        if source_url and "douyin.com" in (source_url or ""):
            source_language = "zh"

        aspect_ratio = metadata.get("aspect_ratio") or "original"
        burn_subtitles = metadata.get("burn_subtitles", True)
        mute_original_audio = metadata.get("mute_original_audio", False)
        blur_original_subtitles = metadata.get("blur_original_subtitles", True)
        blur_region_height_ratio = metadata.get("blur_region_height_ratio", 0.20)
        logo_handle = metadata.get("logo_handle") or "@GocChiemNghiemYuuBin"
        caption_preset = metadata.get("caption_preset") or "montserrat"

        dubber = DubbingService()
        success, timeline = await dubber.execute_dubbing_pipeline(
            video_path=source_path,
            output_path=output_path,
            voice_gender=voice_gender,
            source_language=source_language,
            progress_callback=lambda msg: log_realtime_progress(job_id, "DUBBING_PIPELINE", "INFO", msg),
            aspect_ratio=aspect_ratio,
            burn_subtitles=burn_subtitles,
            mute_original_audio=mute_original_audio,
            blur_original_subtitles=blur_original_subtitles,
            blur_region_height_ratio=blur_region_height_ratio,
            logo_handle=logo_handle,
            caption_preset=caption_preset,
        )

        if not success or not os.path.exists(output_path):
            raise RuntimeError("Lỗi trong quá trình chạy lồng tiếng tự động.")

        # Tối ưu SEO từ transcript lồng tiếng
        log_realtime_progress(job_id, "DUBBING_PIPELINE", "INFO",
                              "Đang phân tích lời thoại để tối ưu SEO...")
        seo_tags: dict = {}
        title_idea = job.get("video_title_idea") or "Video lồng tiếng mới"
        hook_text = ""
        try:
            vietnamese_transcript = " ".join(
                seg.get("translated_text", "") for seg in timeline if seg.get("translated_text")
            )
            llm = LLMService()
            seo_tags = llm.generate_seo_metadata_for_dub(vietnamese_transcript, original_video_title)
            title_idea = (
                seo_tags.get("title")
                or (seo_tags.get("youtube_title_options") or [None])[0]
                or title_idea
            )
            hook_text = seo_tags.get("hook_text_3s") or seo_tags.get("hook") or ""
            log_realtime_progress(job_id, "DUBBING_PIPELINE", "SUCCESS",
                                  f"Đã sinh SEO tags thành công! Tiêu đề mới: {title_idea}")
        except Exception as seo_err:
            print(f"[DubbingStrategy] SEO generation failed: {seo_err}")

        # Lưu về DB
        from worker.infrastructure.database import get_db_connection
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE video_pipeline_jobs
                    SET video_output_path = %s, seo_tags_metadata = %s,
                        video_title_idea = %s, hook_text_3s = %s,
                        scenes_layout_json = %s, pipeline_state = 'RENDERED_SUBTITLED'
                    WHERE id = %s
                    """,
                    (
                        output_path,
                        json.dumps(seo_tags, ensure_ascii=False),
                        title_idea,
                        hook_text,
                        json.dumps(metadata, ensure_ascii=False),
                        job_id,
                    ),
                )
        finally:
            conn.close()

        log_realtime_progress(job_id, "DUBBING_PIPELINE", "SUCCESS",
                              f"Dịch thuật & Lồng tiếng thành công! Đầu ra: {output_path}")
        return output_path
