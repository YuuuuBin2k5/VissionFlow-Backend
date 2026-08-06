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
        voice_code = metadata.get("voice_code") or "edge-nam-minh"
        target_language = metadata.get("target_language") or "auto"

        # Tự động chuyển target_language sang 'en' nếu chọn giọng lồng tiếng Anh (Adam, Christopher, etc.)
        english_voices = ["adam", "eleven-adam", "edge-en-christopher", "edge-en-adam"]
        if voice_code.lower() in english_voices or voice_code.lower().startswith("en-"):
            if target_language in ["auto", "vi"]:
                target_language = "en"

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
        bgm_preset = metadata.get("bgm_preset")
        bgm_custom_url = metadata.get("bgm_custom_url")
        bgm_volume = float(metadata.get("bgm_volume") or 0.18)

        dubber = DubbingService()
        success, timeline = await dubber.execute_dubbing_pipeline(
            video_path=source_path,
            output_path=output_path,
            voice_gender=voice_gender,
            voice_code=voice_code,
            target_language=target_language,
            source_language=source_language,
            progress_callback=lambda msg: log_realtime_progress(job_id, "DUBBING_PIPELINE", "INFO", msg),
            aspect_ratio=aspect_ratio,
            burn_subtitles=burn_subtitles,
            mute_original_audio=mute_original_audio,
            blur_original_subtitles=blur_original_subtitles,
            blur_region_height_ratio=blur_region_height_ratio,
            logo_handle=logo_handle,
            caption_preset=caption_preset,
            bgm_preset=bgm_preset,
            bgm_custom_url=bgm_custom_url,
            bgm_volume=bgm_volume,
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
            from worker.services.unified_metadata_service import UnifiedVideoMetadataService
            meta_service = UnifiedVideoMetadataService(target_language=target_language, voice_code=voice_code)
            storytelling_framework = metadata.get("storytelling_framework") or "mid_action_open"
            seo_tags = meta_service.generate_seo_metadata(vietnamese_transcript, original_video_title, storytelling_framework=storytelling_framework).to_dict()
            title_idea = (
                seo_tags.get("title")
                or meta_service.sanitize_and_translate_title(original_video_title)
                or title_idea
            )
            hook_text = seo_tags.get("hook_text_3s") or seo_tags.get("hook") or ""
            log_realtime_progress(job_id, "DUBBING_PIPELINE", "SUCCESS",
                                  f"Đã sinh SEO tags thành công! Tiêu đề mới: {title_idea}")
        except Exception as seo_err:
            print(f"[DubbingStrategy] SEO generation failed: {seo_err}")

        # Lưu về DB MySQL (legacy, non-critical)
        try:
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
        except Exception as mysql_err:
            print(f"[DubbingStrategy] MySQL legacy update skipped or failed (non-critical): {mysql_err}")


        # Upload MP4 lên Cloudflare R2 & đồng bộ sang Control Plane PostgreSQL
        # để video xuất hiện trong Review Queue / Publication Queue / Control Tower
        r2_object_key = None
        byte_size = 0
        try:
            from worker.services.visionflow_object_storage import S3CompatibleObjectStorage, VisionFlowObjectStorageSettings
            storage = S3CompatibleObjectStorage(VisionFlowObjectStorageSettings.from_env())
            r2_object_key = f"visionflow/dub-{job_id}/exports/final.mp4"
            byte_size = os.path.getsize(output_path)
            log_realtime_progress(job_id, "DUBBING_PIPELINE", "INFO",
                                  f"Đang tải MP4 lên Cloudflare R2: {r2_object_key}...")
            with open(output_path, "rb") as f:
                storage._client.upload_fileobj(
                    f, storage._settings.bucket, r2_object_key,
                    ExtraArgs={"ContentType": "video/mp4"}
                )
            log_realtime_progress(job_id, "DUBBING_PIPELINE", "SUCCESS",
                                  f"Đã tải lên R2 thành công: {r2_object_key}")
        except Exception as r2_err:
            print(f"[DubbingStrategy] R2 upload failed (non-critical): {r2_err}")

        try:
            import sys as _sys
            _cp_dir = None
            for p in _sys.path:
                import pathlib
                candidate = pathlib.Path(p) / "app" / "core" / "dubbing_bridge.py"
                if candidate.exists():
                    _cp_dir = str(pathlib.Path(p))
                    break
            if not _cp_dir:
                # Thử đường dẫn tương đối từ project root
                import pathlib
                _root = pathlib.Path(__file__).resolve().parents[4]
                _candidate = _root / "services" / "control-plane"
                if (_candidate / "app" / "core" / "dubbing_bridge.py").exists():
                    _cp_dir = str(_candidate)

            if _cp_dir and _cp_dir not in _sys.path:
                _sys.path.insert(0, _cp_dir)

            from app.core.dubbing_bridge import sync_dubbing_job_to_control_plane
            raw_wf_id = getattr(contract, "workflow_run_id", None) or metadata.get("workflow_run_id") or job.get("workflow_run_id") or job.get("id")
            wf_id = sync_dubbing_job_to_control_plane(
                job_id=job_id,
                title=title_idea,
                metadata={**metadata, "seo": seo_tags, "hook": hook_text},
                state="APPROVAL_PENDING",
                r2_object_key=r2_object_key,
                byte_size=byte_size,
                workflow_run_id=str(raw_wf_id) if raw_wf_id else None,
            )
            log_realtime_progress(job_id, "DUBBING_PIPELINE", "INFO",
                                  f"Đã đồng bộ sang Control Plane (WorkflowRun ID: {wf_id})")
        except Exception as cp_err:
            print(f"[DubbingStrategy] Control Plane sync failed (non-critical): {cp_err}")

        log_realtime_progress(job_id, "DUBBING_PIPELINE", "SUCCESS",
                              f"Dịch thuật & Lồng tiếng thành công! Đầu ra: {output_path}")
        return output_path
