"""
Publish Use Case — Refactored với Adapter + Factory Pattern
============================================================
Luồng chính:
  1. Đọc job và publish target từ DB (qua Repository)
  2. Xây dựng PublishPayload chuẩn
  3. Gọi get_publisher(platform) → delegate toàn bộ logic nền tảng
  4. Lưu kết quả về DB (qua Repository)

Thêm nền tảng mới (Instagram, Snapchat...):
  → Chỉ cần thêm vào PLATFORM_REGISTRY trong publisher_factory.py
  → File này KHÔNG cần sửa (OCP compliant)
"""
from __future__ import annotations

import json
import os

from worker.domain.caption_policy import extract_publish_music_metadata, build_high_converting_description, build_publish_caption_and_hashtags, build_topic_hashtags
from worker.domain.publish_metadata import append_required_attribution, resolve_publish_metadata
from worker.domain.job_metadata import parse_job_metadata
from worker.infrastructure.database import log_realtime_progress
from worker.infrastructure.repositories import VideoJobRepository, PublishTargetRepository
from worker.services.publishers import get_publisher, resolve_profile_dir, PublishPayload


def handle_publish(
    job_id: int,
    publish_target_id: int = None,
    proxy_ip: str = None,
    proxy_port: int = None,
    proxy_user: str = None,
    proxy_pass: str = None,
    lang_token: str = None,
):
    """
    Tác vụ PUBLISH — điều phối quá trình đăng tải video lên mạng xã hội.

    1. Đọc thông tin video đã được duyệt từ DB.
    2. Xác định nền tảng (TikTok / YouTube / ...) và xây dựng payload chuẩn.
    3. Gọi đúng Publisher thông qua Factory — không if/else theo platform.
    4. Cập nhật trạng thái publish về DB.
    """
    log_realtime_progress(job_id, "UPLOAD_ENGINE", "INFO",
                          f"Khởi động trình duyệt Playwright Stealth để đăng tải video Job #{job_id}...")

    job_repo = VideoJobRepository()
    target_repo = PublishTargetRepository()

    # ── 1. Đọc job và publish target ─────────────────────────────────────────
    job = job_repo.find_by_id(job_id)
    if not job:
        raise Exception(f"Không tìm thấy Video Job với ID #{job_id}")

    video_path = job.get("video_output_path")
    if not video_path or not os.path.exists(video_path):
        raise Exception(f"Không tìm thấy file video đầu ra để đăng: {video_path}")

    # Xác định platform và connection ID
    platform = "tiktok"
    platform_connection_id = None

    target_row = (
        target_repo.find_by_id(publish_target_id)
        if publish_target_id
        else target_repo.find_by_job_id(job_id)
    )
    if target_row:
        platform = target_row.get("platform") or platform
        platform_connection_id = target_row.get("platform_connection_id")

    # ── 2. Xây dựng PublishPayload ────────────────────────────────────────────
    metadata = parse_job_metadata(job)
    seo_data: dict = {}
    if job.get("seo_tags_metadata"):
        try:
            raw = job["seo_tags_metadata"]
            seo_data = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            seo_data = {}

    music_metadata = extract_publish_music_metadata(job)
    legacy_title, legacy_hashtags = build_publish_caption_and_hashtags(job, metadata, seo_data, music_metadata)

    # publish_targets are operator-edited final values, therefore they are
    # canonical user metadata rather than another generator input.
    user_metadata: dict = {}

    if publish_target_id:
        detail = target_repo.find_detail_by_id(publish_target_id)
        if detail:
            user_platform = {"title": detail.get("title"), "description": detail.get("description")}
            tags_raw = detail.get("tags")
            if tags_raw:
                try:
                    user_platform["tags"] = json.loads(tags_raw) if isinstance(tags_raw, str) else tags_raw
                except Exception:
                    user_platform["tags"] = []
            user_metadata = {platform: user_platform}

    content_metadata = metadata.get("publish_metadata") or seo_data.get("publish_metadata")
    fallback_title = job.get("video_title_idea") or legacy_title or "Video mới"
    fallback = {platform: {"title": fallback_title, "hashtags": legacy_hashtags}}
    resolved = resolve_publish_metadata(
        content_metadata=content_metadata,
        user_metadata=user_metadata,
        fallback=fallback,
        platform=platform,
    )
    description_or_caption = resolved.description if platform == "youtube" else resolved.caption
    if description_or_caption is None:
        fallback_text = build_high_converting_description(
            title=fallback_title,
            script=job.get("script") or job.get("full_voice_script") or "",
            seo_data=seo_data,
            language="en" if str(job.get("video_language") or "vi").lower().startswith("en") else "vi",
        ) if platform == "youtube" else legacy_title
        resolved = resolve_publish_metadata(
            content_metadata=content_metadata,
            user_metadata=user_metadata,
            fallback={platform: {"title": fallback_title, "description" if platform == "youtube" else "caption": fallback_text, "hashtags": build_topic_hashtags(fallback_title, "", seo_data)}},
            platform=platform,
        )
        description_or_caption = resolved.description if platform == "youtube" else resolved.caption
    target_title = resolved.title.value if resolved.title else fallback_title
    target_description = description_or_caption.value if description_or_caption else ""
    target_description, _ = append_required_attribution(target_description, seo_data.get("music_attribution") or seo_data.get("bgm_info") or seo_data.get("selected_music"))
    hashtags = resolved.hashtags.value if resolved.hashtags else []
    target_tags = resolved.tags.value if resolved.tags else []

    # Sinh bình luận ghim nếu thiếu (TikTok)
    comment_text = _resolve_comment_text(job, seo_data, metadata, job_id)

    payload = PublishPayload(
        title=target_title,
        description=target_description,
        hashtags=hashtags,
        tags=target_tags,
        comment_text=comment_text,
        music_metadata=music_metadata,
        proxy_ip=proxy_ip,
        proxy_port=proxy_port,
        proxy_user=proxy_user,
        proxy_pass=proxy_pass,
        force_headful=True,
        headless=False,
    )

    if music_metadata and platform == "tiktok":
        log_realtime_progress(job_id, "UPLOAD_ENGINE", "INFO",
                              f"Sẽ chọn nhạc TikTok: {music_metadata.get('song_title')} - {music_metadata.get('artist_name')}")
    log_realtime_progress(job_id, "UPLOAD_ENGINE", "INFO", f"Caption đã tối ưu: {target_title[:120]}")

    # ── 3. Đánh dấu PUBLISHING và gọi Publisher qua Factory ─────────────────
    if publish_target_id:
        target_repo.mark_publishing(publish_target_id)

    worker_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "worker")
    profile_path = resolve_profile_dir(platform, platform_connection_id, worker_dir)

    try:
        publisher = get_publisher(platform, profile_path)
        log_realtime_progress(job_id, "UPLOAD_ENGINE", "INFO",
                              f"Bắt đầu xuất bản lên {platform.upper()}: {target_title[:100]}")

        result = publisher.publish(video_path, payload)

        # ── 4. Lưu kết quả về DB ─────────────────────────────────────────────
        if not result.success:
            raise Exception(result.error_message or f"Publisher {platform} thất bại không rõ nguyên nhân.")

        job_repo.save_published(job_id)

        if publish_target_id:
            target_repo.mark_published(
                target_id=publish_target_id,
                external_url=result.external_url,
                external_video_id=result.external_video_id,
            )
        elif platform_connection_id:
            target_repo.mark_published_by_job(
                job_id=job_id,
                platform=platform,
                platform_connection_id=platform_connection_id,
                external_url=result.external_url,
                external_video_id=result.external_video_id,
            )

        success_msg = f"Đã đăng tải thành công lên {platform.upper()}!"
        if result.external_url:
            success_msg += f" URL: {result.external_url}"
        log_realtime_progress(job_id, "UPLOAD_ENGINE", "SUCCESS", success_msg)

    except Exception as e:
        # Ghi lỗi về DB
        target_repo.mark_failed(
            error_message=str(e),
            target_id=publish_target_id,
            job_id=job_id,
            platform=platform,
            platform_connection_id=platform_connection_id,
        )
        raise


# ──────────────────────────────────────────────────────────────────────────────
# Private helpers
# ──────────────────────────────────────────────────────────────────────────────

def _resolve_comment_text(job: dict, seo_data: dict, metadata: dict, job_id: int) -> str | None:
    """
    Lấy bình luận ghim từ nhiều nguồn theo thứ tự ưu tiên.
    Tự động sinh bằng LLM nếu tất cả nguồn trống hoặc quá ngắn.
    """
    comment_text = (
        seo_data.get("pinned_comment")
        or seo_data.get("philosophical_comment")
        or seo_data.get("tiktok_pinned_comment")
        or job.get("pinned_comment")
    )

    if not comment_text or len(str(comment_text).strip()) < 80:
        try:
            from worker.services.llm_service import LLMService
            topic = job.get("video_title_idea") or job.get("raw_topic") or "Bình yên từ lòng biết ơn"
            script = job.get("full_voice_script") or (seo_data.get("video_script") if seo_data else "") or ""
            video_language = (
                "en"
                if str(job.get("video_language") or metadata.get("video_language") or "vi").lower().startswith("en")
                else "vi"
            )
            log_realtime_progress(job_id, "UPLOAD_ENGINE", "INFO",
                                  "Bình luận ghim bị thiếu. Đang tự động sinh bằng LLM...")
            comment_text = LLMService().generate_philosophical_comment(topic, script, video_language)
            log_realtime_progress(job_id, "UPLOAD_ENGINE", "INFO",
                                  f"Đã sinh bình luận tự động ({len(comment_text)} ký tự).")
        except Exception as llm_err:
            log_realtime_progress(job_id, "UPLOAD_ENGINE", "WARNING",
                                  f"Không thể sinh bình luận LLM: {llm_err}. Bỏ qua.")
            comment_text = None

    return comment_text
