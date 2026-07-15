"""
Render Use Case — Refactored với Strategy Pattern
==================================================
handle_render() từ 531 dòng → ~35 dòng nhờ Strategy Pattern.

Luồng chính:
  1. Đọc job từ DB (qua VideoJobRepository)
  2. Build RenderContract từ metadata
  3. Duyệt RENDER_STRATEGIES tìm strategy phù hợp
  4. Delegate toàn bộ logic render sang strategy.execute()
  5. Xử lý lỗi tập trung tại đây

Thêm render mode mới (AI Avatar, 3D Cinematic...):
  → Thêm vào RENDER_STRATEGIES trong strategy_registry.py
  → File này KHÔNG cần sửa (OCP compliant)
"""
from __future__ import annotations

import json

from worker.domain.job_metadata import parse_job_metadata
from worker.domain.render_contract import build_render_contract, RenderStopStage
from worker.infrastructure.database import log_realtime_progress
from worker.infrastructure.repositories import VideoJobRepository
from worker.application.render_strategies import get_render_strategies


# ── Helper functions được giữ lại để các Strategy class tái sử dụng ──────────

def resolve_script_background_music(job: dict, details: dict, music_mood: str, job_id: int) -> tuple:
    """
    Chọn nhạc nền theo đúng mood/kịch bản.
    Hàm này được giữ lại ở đây để StandardRenderStrategy import tái sử dụng.
    """
    title_idea = job.get("video_title_idea") or ""
    topic = job.get("topic") or ""
    hook = details.get("hook_text_3s") or ""
    script_mood = details.get("music_mood") or music_mood or "educational"
    music_description = details.get("music_description") or ""

    music_context = " | ".join(
        part for part in [
            topic, title_idea, hook,
            f"Mood kịch bản: {script_mood}", music_description,
        ] if part
    )

    from worker.services.trending_music_service import TrendingMusicService
    trending_music = TrendingMusicService()
    song_title, artist_name, resolved_mood = trending_music.resolve_trending_song_for_topic(
        music_context or topic or title_idea or "TikTok video", title_idea,
    )
    music_path = trending_music.download_mood_audio(resolved_mood, job_id)
    music_metadata = {
        "song_title": song_title,
        "artist_name": artist_name,
        "mood": resolved_mood,
        "script_music_mood": script_mood,
        "music_description": music_description,
        "audio_path": music_path,
        "require_tiktok_music": True,
        "tiktok_sound_volume_percent": 2,
        "original_video_volume_percent": 100,
        "tiktok_music_strategy": "add_exact_sound_at_publish",
    }
    return music_path, music_metadata


async def _resolve_split_screen_assets(
    job_id, existing_metadata, details, scenes_layout,
    asset_downloader, local_lib, seo_tags
) -> tuple[list, list]:
    """
    Helper tải asset cho split-screen pipeline.
    Tách ra đây để StandardRenderStrategy có thể gọi lại.
    """
    from worker.infrastructure.database import log_realtime_progress
    from worker.services.cockpit_bridge import update_task_progress

    split_mode = existing_metadata.get("split_mode", "FULLY_GENERATIVE")
    top_video_filename = existing_metadata.get("top_video_path")
    bottom_video_filename = existing_metadata.get("bottom_video_path")
    bg_video_paths = []
    bottom_video_paths = []

    import os

    def resolve_split_asset_path(filename: str, layer: str) -> str:
        if not filename:
            return ""
        docker_path = os.path.join("/app/shared_media/split_assets", f"{layer}_layers", filename)
        if os.path.exists(docker_path):
            return docker_path
        local_path = os.path.join(os.getcwd(), "shared_media", "split_assets", f"{layer}_layers", filename)
        if os.path.exists(local_path):
            return local_path
        return docker_path

    # Bottom half
    if split_mode in ("MANUAL_BOTTOM", "MANUAL_BOTH") and bottom_video_filename:
        bottom_video_paths = [resolve_split_asset_path(bottom_video_filename, "bottom")]
        log_realtime_progress(job_id, "ASSET_DOWNLOAD", "SUCCESS",
                              f"Sử dụng custom bottom video: {bottom_video_filename}")
    elif split_mode == "LONG_CHILL_MULTI_ACTION":
        lifestyle_query = (
            details.get("lifestyle_search_query")
            or existing_metadata.get("lifestyle_search_query")
            or "cooking satisfying vertical"
        )
        requirements = (
            details.get("bottom_asset_requirements")
            or existing_metadata.get("bottom_asset_requirements") or {}
        )
        log_realtime_progress(job_id, "ASSET_DOWNLOAD", "INFO",
                              f"[LONG_CHILL] Tìm kiếm video nền: '{lifestyle_query}'")

        best_asset = None
        fallback_queries = [
            lifestyle_query,
            "cooking preparation vertical",
            "organizing desk satisfying vertical",
        ]
        for q in fallback_queries:
            try:
                candidate = asset_downloader.search_and_download_best_bottom_asset(q, job_id, requirements)
                if candidate and candidate.get("duration", 0) >= 30:
                    best_asset = candidate
                    break
                log_realtime_progress(job_id, "ASSET_DOWNLOAD", "WARN",
                                      f"Asset từ '{q}' dưới 30s. Thử fallback...")
            except Exception as e:
                log_realtime_progress(job_id, "ASSET_DOWNLOAD", "WARN", f"'{q}' thất bại: {e}")

        if not best_asset:
            for cat in ["cooking_long", "satisfying", "daily_life_bottom"]:
                res = local_lib.find_video(category=cat, keywords=lifestyle_query, min_duration_seconds=30)
                if res and res.get("duration", 0) >= 30:
                    best_asset = {"path": res["path"], "duration": res["duration"],
                                  "width": res.get("width"), "height": res.get("height"),
                                  "source": "local", "source_url": res["path"], "score": res.get("score", 0)}
                    break

        if best_asset:
            bottom_video_paths = [best_asset["path"]]
            seo_tags["bottom_asset_metadata"] = best_asset
        else:
            log_realtime_progress(job_id, "ASSET_DOWNLOAD", "WARN", "Không tìm được bottom video.")
    else:
        lifestyle_query = (
            details.get("lifestyle_search_query")
            or existing_metadata.get("lifestyle_search_query")
            or "cooking chicken curry vertical"
        )
        try:
            bottom_video_paths = asset_downloader.search_and_download_videos(lifestyle_query, job_id, count=5)
        except Exception:
            try:
                bottom_video_paths = [asset_downloader.search_and_download_video("cooking chicken curry vertical", job_id)]
            except Exception:
                bottom_video_paths = []

    # Top half
    if split_mode in ("MANUAL_TOP", "MANUAL_BOTH") and top_video_filename:
        bg_video_paths = [resolve_split_asset_path(top_video_filename, "top")]
    else:
        total = len(scenes_layout)
        for idx, scene in enumerate(scenes_layout):
            scene_id = scene.get("scene_id", 1)
            keywords = scene.get("visual_search_keywords", "man looking at starry sky vertical")
            try:
                path = asset_downloader.search_and_download_video(keywords, scene_id)
                bg_video_paths.append(path)
            except Exception as ae:
                log_realtime_progress(job_id, "ASSET_DOWNLOAD", "WARN",
                                      f"Lỗi tải scene {scene_id}: {ae}")
                try:
                    path = asset_downloader.search_and_download_video("abstract vertical", scene_id)
                    bg_video_paths.append(path)
                except Exception as ae2:
                    if bg_video_paths:
                        bg_video_paths.append(bg_video_paths[-1])
                    elif bottom_video_paths:
                        bg_video_paths.append(bottom_video_paths[0])
                    else:
                        raise ae2
            try:
                update_task_progress(str(job_id), "ASSET", int(((idx + 1) / total) * 100))
            except Exception:
                pass

    return bg_video_paths, bottom_video_paths


# ──────────────────────────────────────────────────────────────────────────────
# Main Use Case Entry Point
# ──────────────────────────────────────────────────────────────────────────────

async def handle_render(job_id: int):
    """
    Tác vụ RENDER — Điều phối pipeline render video.

    Hàm này chỉ chịu trách nhiệm:
    1. Đọc job từ DB
    2. Xây dựng RenderContract
    3. Tìm và gọi đúng Strategy
    4. Ghi lỗi về DB nếu thất bại

    Mọi logic render cụ thể nằm trong các Strategy class.
    """
    log_realtime_progress(job_id, "LLM_SCRIPT", "INFO",
                          f"Khởi động pipeline render cho Job #{job_id}...")

    repo = VideoJobRepository()

    # 1. Đọc job từ DB
    job = repo.find_by_id(job_id)
    if not job:
        raise Exception(f"Không tìm thấy Video Job với ID #{job_id}")

    # 2. Reset trạng thái và xoá lỗi cũ
    repo.clear_error_and_set_state(job_id, "AI_PROCESSING")

    # 3. Build RenderContract từ metadata
    metadata = parse_job_metadata(job)
    contract = build_render_contract(
        job=job,
        metadata=metadata,
        topic=job.get("topic") or "",
        audience=job.get("target_audience") or "Mọi đối tượng",
        voice_code=metadata.get("voice_code") or "edge-nam-minh",
    )

    # 4. Tìm Strategy phù hợp và execute (Strategy Pattern)
    strategy = next(
        (s for s in get_render_strategies() if s.can_handle(contract)),
        None,
    )
    if strategy is None:
        raise RuntimeError(
            f"Không tìm thấy render strategy nào phù hợp cho contract: {contract.mode}"
        )

    log_realtime_progress(job_id, "AI_PROCESSING", "INFO",
                          f"Chọn strategy: {strategy.__class__.__name__} (mode: {contract.mode})")

    try:
        await strategy.execute(job, contract)
    except Exception as render_error:
        repo.update_state(job_id, "QUALITY_FAILED", error_trace=str(render_error))
        log_realtime_progress(job_id, "QUALITY_FAILED", "ERROR",
                              f"Render thất bại: {render_error}")
        raise
