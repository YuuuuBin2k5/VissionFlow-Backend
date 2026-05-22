import os
import sys
import argparse
import json
import asyncio
import datetime
import re
import unicodedata
import pymysql
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pymysql.cursors import DictCursor

# Reconfigure stdout and stderr to use UTF-8 to prevent Unicode crashes on Windows console
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass
if sys.stderr.encoding != 'utf-8':
    try:
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

# Thêm thư mục gốc vào path để có thể import từ worker.*
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from worker.config import (
    DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME,
    ASSETS_DIR, OUTPUT_DIR,
    SCHEDULE_TIMEZONE, POSTING_SCHEDULE_PRESET, POSTING_SCHEDULE_PRESETS,
    MIN_HOURS_BETWEEN_POSTS
)
from worker.services.llm_service import LLMService
from worker.services.tts_service import TTSService
from worker.services.asset_service import AssetService
from worker.services.media_service import MediaService
from worker.services.music_reactive_service import MusicReactiveService
from worker.services.publisher_service import PublisherService
from worker.services.trending_music_service import TrendingMusicService

# Hàm kết nối Database MySQL
def get_db_connection():
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset='utf8mb4',
        cursorclass=DictCursor,
        autocommit=True
    )

def log_realtime_progress(job_id, step, level, message):
    """Ghi nhận tiến trình thời gian thực vào bảng process_realtime_logs"""
    print(f"[{level}] {step}: {message}")
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            sql = """
            INSERT INTO process_realtime_logs (job_id, execution_step, status_level, log_message)
            VALUES (%s, %s, %s, %s)
            """
            cursor.execute(sql, (job_id, step, level, message))
        conn.close()
    except Exception as e:
        print(f"[DB Log Error] Failed to write log: {e}")

def _parse_slot(slot: str):
    hour_str, minute_str = slot.split(":", 1)
    return int(hour_str), int(minute_str)

def get_daily_posting_slots():
    return POSTING_SCHEDULE_PRESETS.get(
        POSTING_SCHEDULE_PRESET,
        POSTING_SCHEDULE_PRESETS["office_student"],
    )

def get_schedule_timezone():
    try:
        return ZoneInfo(SCHEDULE_TIMEZONE)
    except ZoneInfoNotFoundError:
        if SCHEDULE_TIMEZONE == "Asia/Bangkok":
            return datetime.timezone(datetime.timedelta(hours=7), name="Asia/Bangkok")
        raise

def build_safe_campaign_schedule(total_videos: int, start_from=None):
    """
    Build a two-posts-per-day schedule with a hard minimum gap.
    Naive datetimes are returned because the current MySQL schema stores DATETIME.
    """
    timezone = get_schedule_timezone()
    now = start_from or datetime.datetime.now(timezone)
    first_day = now.date() + datetime.timedelta(days=1)
    slots = get_daily_posting_slots()
    min_gap = datetime.timedelta(hours=MIN_HOURS_BETWEEN_POSTS)

    schedule = []
    last_time = None
    for idx in range(total_videos):
        slot = slots[idx % len(slots)]
        day_offset = idx // len(slots)
        hour, minute = _parse_slot(slot)
        scheduled_time = datetime.datetime.combine(
            first_day + datetime.timedelta(days=day_offset),
            datetime.time(hour=hour, minute=minute),
            tzinfo=timezone,
        )

        if last_time and scheduled_time < last_time + min_gap:
            scheduled_time = last_time + min_gap

        schedule.append(scheduled_time.replace(tzinfo=None))
        last_time = scheduled_time

    return schedule

def parse_job_metadata(job: dict) -> dict:
    raw = job.get("scenes_layout_json")
    if not raw:
        return {}
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}

def is_music_reactive_job(job: dict, metadata: dict) -> bool:
    """
    Chỉ đưa job sang nhánh music reactive khi chính metadata của job yêu cầu.
    Không dùng RENDER_ENGINE global để phân loại mọi job, vì /startcampaign
    cần luôn đi qua luồng TTS classic để có giọng đọc lồng tiếng.
    """
    return (
        metadata.get("render_mode") in ("music_reactive", "music_remix_reactive")
        or metadata.get("is_standalone_music_video") is True
        or metadata.get("requires_user_audio") is True
    )

def extract_publish_music_metadata(job: dict) -> dict:
    """
    Lấy thông tin bài nhạc cần chọn trực tiếp trên TikTok Studio khi đăng.
    Ưu tiên metadata của video music_reactive, sau đó fallback selected_music trong SEO.
    """
    metadata = parse_job_metadata(job)
    music_metadata = {}

    if metadata.get("song_title"):
        music_metadata = {
            "song_title": metadata.get("song_title"),
            "artist_name": metadata.get("artist_name"),
            "mood": metadata.get("mood") or metadata.get("music_mood"),
            "require_tiktok_music": metadata.get("require_tiktok_music", True),
            "tiktok_sound_volume_percent": metadata.get("tiktok_sound_volume_percent", 2),
            "original_video_volume_percent": metadata.get("original_video_volume_percent", 100),
        }

    if not music_metadata and job.get("seo_tags_metadata"):
        try:
            seo_data = json.loads(job["seo_tags_metadata"]) if isinstance(job["seo_tags_metadata"], str) else job["seo_tags_metadata"]
            selected_music = seo_data.get("selected_music", {}) if isinstance(seo_data, dict) else {}
            if selected_music.get("song_title"):
                music_metadata = {
                    "song_title": selected_music.get("song_title"),
                    "artist_name": selected_music.get("artist_name"),
                    "mood": selected_music.get("mood"),
                    "require_tiktok_music": selected_music.get("require_tiktok_music", True),
                    "tiktok_sound_volume_percent": selected_music.get("tiktok_sound_volume_percent", 2),
                    "original_video_volume_percent": selected_music.get("original_video_volume_percent", 100),
                }
        except Exception:
            pass

    return music_metadata

def _hashtagify(text: str) -> str:
    no_accents = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^\w]+", "", no_accents, flags=re.UNICODE).strip()
    return cleaned.lower()

def _normalize_hashtags(hashtags: list) -> list:
    normalized = []
    seen = set()
    for tag in hashtags or []:
        if not tag:
            continue
        value = str(tag).strip()
        if not value:
            continue
        value = value if value.startswith("#") else f"#{value}"
        key = value.lower()
        if key not in seen:
            normalized.append(value)
            seen.add(key)
    return normalized

def build_publish_caption_and_hashtags(job: dict, metadata: dict, seo_data: dict, music_metadata: dict) -> tuple:
    """
    Dựng caption đăng TikTok. Video âm nhạc ưu tiên caption cảm xúc sau render,
    không dùng tiêu đề thô kiểu "Tên bài - Ca sĩ".
    """
    fallback_title = job.get("video_title_idea") or "Video mới"
    seo_data = seo_data if isinstance(seo_data, dict) else {}
    metadata = metadata if isinstance(metadata, dict) else {}

    if music_metadata:
        song_title = music_metadata.get("song_title") or metadata.get("song_title") or fallback_title
        artist_name = music_metadata.get("artist_name") or metadata.get("artist_name") or ""
        emotional_caption = (
            metadata.get("publish_caption")
            or metadata.get("caption")
            or seo_data.get("title")
            or f"Có những giai điệu chỉ cần vang lên là chạm đúng tâm trạng."
        )
        artist_part = f" - {artist_name}" if artist_name else ""
        caption = f"{emotional_caption} {song_title}{artist_part}".strip()

        hashtag_candidates = []
        for value in [song_title, artist_name]:
            tag = _hashtagify(value)
            if tag:
                hashtag_candidates.append(tag)
        hashtag_candidates.extend(
            metadata.get("music_hashtags")
            or seo_data.get("hashtags")
            or ["nhacviet", "tiktokmusic", "tamtrang", "viral", "xuhuong"]
        )
        return caption, _normalize_hashtags(hashtag_candidates)

    title = seo_data.get("title") or metadata.get("seo_title") or fallback_title
    hashtags = seo_data.get("hashtags", [])
    if not hashtags:
        hashtags = ["learnontiktok", "automation", "tiktokagent"]
    return title, _normalize_hashtags(hashtags)

def resolve_script_background_music(job: dict, details: dict, music_mood: str, job_id: int) -> tuple:
    """
    Chọn nhạc nền theo đúng mood/kịch bản thay vì luôn dùng lofi mặc định.
    Trả về đường dẫn audio đã tải và metadata để lưu vết bài/mood đã chọn.
    """
    title_idea = job.get("video_title_idea") or ""
    topic = job.get("topic") or ""
    hook = details.get("hook_text_3s") or ""
    script_mood = details.get("music_mood") or music_mood or "educational"
    music_description = details.get("music_description") or ""

    music_context = " | ".join(
        part for part in [
            topic,
            title_idea,
            hook,
            f"Mood kịch bản: {script_mood}",
            music_description,
        ] if part
    )

    trending_music = TrendingMusicService()
    song_title, artist_name, resolved_mood = trending_music.resolve_trending_song_for_topic(
        music_context or topic or title_idea or "TikTok video",
        title_idea,
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

def handle_music_reactive_render(job: dict):
    job_id = job["id"]
    metadata = parse_job_metadata(job)

    def progress(state: str, message: str):
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("UPDATE video_pipeline_jobs SET pipeline_state = %s WHERE id = %s", (state, job_id))
        conn.close()
        log_realtime_progress(job_id, state, "INFO", message)

    progress("SIGNAL_PROCESSING", "Bắt đầu phân tích FFT/audio-reactive data cho video music reactive...")

    service = MusicReactiveService()
    try:
        try:
            result = service.render_music_reactive_video(job=job, metadata=metadata, job_id=job_id, progress=progress)
        except RuntimeError as first_error:
            if "blackout frame" not in str(first_error).lower():
                raise

            log_realtime_progress(job_id, "QUALITY_CHECK", "WARN", f"Phát hiện blackout frame: {first_error}. Thử lại với background fallback...")
            metadata.pop("background_video_path", None)
            result = service.render_music_reactive_video(job=job, metadata=metadata, job_id=job_id, progress=progress)
    except Exception as render_error:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("UPDATE video_pipeline_jobs SET pipeline_state = 'QUALITY_FAILED', error_log_trace = %s WHERE id = %s", (str(render_error), job_id))
        conn.close()
        log_realtime_progress(job_id, "QUALITY_FAILED", "ERROR", f"Music reactive render thất bại: {render_error}")
        raise

    conn = get_db_connection()
    with conn.cursor() as cursor:
        sql = """
        UPDATE video_pipeline_jobs
        SET video_output_path = %s, scenes_layout_json = %s, pipeline_state = 'RENDERED_SUBTITLED', error_log_trace = NULL
        WHERE id = %s
        """
        cursor.execute(sql, (result["video_path"], json.dumps(result["metadata"], ensure_ascii=False), job_id))
    conn.close()

    log_realtime_progress(job_id, "QUALITY_CHECK", "SUCCESS", f"Music reactive video đã qua quality gate: {result['video_path']}")

async def handle_planning(campaign_id: int):
    """
    Tác vụ PLANNING:
    1. Đọc thông tin chiến dịch.
    2. Gọi LLM lên kế hoạch 30 ngày.
    3. Thêm 30 dòng công việc (Jobs) vào MySQL ở trạng thái QUEUED.
    """
    log_realtime_progress(None, "LLM_PLANNING", "INFO", f"Bắt đầu phân tích chủ đề chiến dịch Campaign #{campaign_id}...")
    
    conn = get_db_connection()
    campaign = None
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM channels_campaign WHERE id = %s", (campaign_id,))
            campaign = cursor.fetchone()
    finally:
        conn.close()

    if not campaign:
        raise Exception(f"Không tìm thấy chiến dịch Campaign #{campaign_id}")

    topic = campaign["topic"]
    audience = campaign["target_audience"] or "Mọi đối tượng"

    # Gọi LLM sinh 30 ngày
    llm = LLMService()
    plan = llm.generate_30_day_plan(topic, audience)
    
    log_realtime_progress(None, "LLM_PLANNING", "INFO", f"Đã sinh thành công kế hoạch 30 ngày cho chiến dịch. Đang nạp vào database...")

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # Cập nhật chiến dịch sang trạng thái RUNNING
            cursor.execute("UPDATE channels_campaign SET status = 'RUNNING' WHERE id = %s", (campaign_id,))
            
            # Thêm 30 Jobs vào bảng video_pipeline_jobs
            safe_schedule = build_safe_campaign_schedule(len(plan))
            slots_text = ", ".join(get_daily_posting_slots())
            log_realtime_progress(
                None,
                "SCHEDULER",
                "INFO",
                f"Áp dụng lịch đăng {POSTING_SCHEDULE_PRESET} ({slots_text}), timezone {SCHEDULE_TIMEZONE}, giãn cách tối thiểu {MIN_HOURS_BETWEEN_POSTS} giờ."
            )
            for idx, day_plan in enumerate(plan):
                day_num = day_plan.get("day_number", idx + 1)
                title = day_plan.get("video_title_idea", f"Ý tưởng ngày {day_num}")
                
                # Lập lịch đăng bài: tối đa 2 video/ngày, mặc định 11:30 và 19:30.
                scheduled_time = safe_schedule[idx]
                
                # Ghi nhận các cấu hình được LLM sinh ra từ bước Planning vào scenes_layout_json làm metadata
                metadata = {
                    "music_mood": day_plan.get("music_mood", "educational"),
                    "content_category": day_plan.get("content_category", ""),
                    "primary_goal": day_plan.get("primary_goal", "VIEWS"),
                    "concept_description": day_plan.get("concept_description", "")
                }
                
                sql = """
                INSERT INTO video_pipeline_jobs (campaign_id, day_number, scheduled_post_time, video_title_idea, scenes_layout_json, pipeline_state)
                VALUES (%s, %s, %s, %s, %s, 'QUEUED')
                """
                cursor.execute(sql, (campaign_id, day_num, scheduled_time, title, json.dumps(metadata, ensure_ascii=False)))
                
        log_realtime_progress(None, "LLM_PLANNING", "SUCCESS", f"Hoàn thành khởi tạo chuỗi 30 video cho Campaign #{campaign_id}! 🚀")
    finally:
        conn.close()

async def handle_render(job_id: int):
    """
    Tác vụ RENDER:
    1. Lấy thông tin chi tiết Job.
    2. Gọi LLM sinh kịch bản văn bản, phân cảnh và từ khóa visual.
    3. Sinh file nói TTS và timestamps.
    4. Tải video nền từ Pexels.
    5. MoviePy render video hoàn chỉnh kèm phụ đề.
    """
    log_realtime_progress(job_id, "LLM_SCRIPT", "INFO", f"Bắt đầu biên soạn kịch bản chi tiết cho video Job #{job_id}...")
    
    conn = get_db_connection()
    job = None
    try:
        with conn.cursor() as cursor:
            sql = """
            SELECT j.*, c.topic, c.target_audience 
            FROM video_pipeline_jobs j
            JOIN channels_campaign c ON j.campaign_id = c.id
            WHERE j.id = %s
            """
            cursor.execute(sql, (job_id,))
            job = cursor.fetchone()
    finally:
        conn.close()

    if not job:
        raise Exception(f"Không tìm thấy Video Job với ID #{job_id}")

    metadata = parse_job_metadata(job)
    if is_music_reactive_job(job, metadata):
        await asyncio.to_thread(handle_music_reactive_render, job)
        return

    # Cập nhật trạng thái bắt đầu xử lý AI
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("UPDATE video_pipeline_jobs SET pipeline_state = 'AI_PROCESSING' WHERE id = %s", (job_id,))
    conn.close()

    topic = job["topic"]
    audience = job["target_audience"] or "Mọi đối tượng"
    title_idea = job["video_title_idea"]

    # Gọi LLM sinh Script & Phân cảnh (truyền thêm music_mood và content_category từ kế hoạch 30 ngày)
    llm = LLMService()
    
    # Đọc thêm metadata từ scenes_layout_json (nếu có ghi music_mood từ bước planning)
    music_mood = "educational"
    content_category = ""
    if job.get("scenes_layout_json"):
        try:
            existing = json.loads(job["scenes_layout_json"]) if isinstance(job["scenes_layout_json"], str) else job["scenes_layout_json"]
            if isinstance(existing, dict):
                music_mood = existing.get("music_mood", "educational")
                content_category = existing.get("content_category", "")
        except Exception:
            pass

    details = llm.generate_video_details(
        day_number=job["day_number"],
        topic=topic,
        title_idea=title_idea,
        audience=audience,
        music_mood=music_mood,
        content_category=content_category
    )

    
    hook = details.get("hook_text_3s", "")
    full_script = details.get("full_voice_script", "")
    scenes_layout = details.get("scenes_layout_json", [])
    seo_tags = details.get("seo_tags_metadata", {})
    background_music_path = None
    selected_music_metadata = {}

    log_realtime_progress(job_id, "LLM_SCRIPT", "INFO", f"Kịch bản hoàn thành! Hook: '{hook[:40]}...'. Đang sinh giọng đọc...")

    try:
        log_realtime_progress(job_id, "MUSIC_MATCH", "INFO", "Đang chọn nhạc nền khớp với mood và nội dung kịch bản...")
        background_music_path, selected_music_metadata = resolve_script_background_music(job, details, music_mood, job_id)
        if isinstance(seo_tags, dict):
            seo_tags["selected_music"] = selected_music_metadata
        log_realtime_progress(
            job_id,
            "MUSIC_MATCH",
            "SUCCESS",
            f"Đã chọn nhạc: {selected_music_metadata.get('song_title')} - {selected_music_metadata.get('artist_name')} ({selected_music_metadata.get('mood')})"
        )
    except Exception as music_error:
        log_realtime_progress(job_id, "MUSIC_MATCH", "WARN", f"Không chọn được nhạc theo kịch bản, dùng fallback nội bộ: {music_error}")

    # Cập nhật kết quả kịch bản vào database
    conn = get_db_connection()
    with conn.cursor() as cursor:
        sql = """
        UPDATE video_pipeline_jobs 
        SET hook_text_3s = %s, full_voice_script = %s, scenes_layout_json = %s, seo_tags_metadata = %s, pipeline_state = 'AI_PARSED'
        WHERE id = %s
        """
        cursor.execute(sql, (hook, full_script, json.dumps(scenes_layout, ensure_ascii=False), json.dumps(seo_tags, ensure_ascii=False), job_id))
    conn.close()

    # 2. Sinh giọng đọc Edge-TTS
    log_realtime_progress(job_id, "AUDIO_SYNTH", "INFO", "Bắt đầu stream giọng nói và trích xuất word timestamps...")
    audio_path = str(ASSETS_DIR / f"voice_{job_id}.mp3")
    
    tts = TTSService()
    word_timestamps = await tts.generate_speech_with_timestamps(full_script, audio_path)
    
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("UPDATE video_pipeline_jobs SET audio_file_path = %s, pipeline_state = 'AUDIO_COMPOSED' WHERE id = %s", (audio_path, job_id))
    conn.close()

    # 3. Quét & Tải video nền tự động
    log_realtime_progress(job_id, "ASSET_DOWNLOAD", "INFO", f"Bắt đầu tìm kiếm và tải {len(scenes_layout)} phân cảnh video nền dọc...")
    
    asset_downloader = AssetService()
    bg_video_paths = []
    
    for scene in scenes_layout:
        scene_id = scene.get("scene_id", 1)
        keywords = scene.get("visual_search_keywords", "vertical background")
        
        try:
            path = asset_downloader.search_and_download_video(keywords, scene_id)
            bg_video_paths.append(path)
        except Exception as ae:
            log_realtime_progress(job_id, "ASSET_DOWNLOAD", "WARN", f"Lỗi tải scene {scene_id}: {ae}. Đang sử dụng phương án fallback...")
            # Fallback nếu lỗi
            path = asset_downloader.search_and_download_video("abstract vertical", scene_id)
            bg_video_paths.append(path)

    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("UPDATE video_pipeline_jobs SET pipeline_state = 'ASSETS_READY' WHERE id = %s", (job_id,))
    conn.close()

    # 4. MoviePy Biên tập, hòa âm & Overlay Subtitles
    log_realtime_progress(job_id, "VIDEO_RENDER", "INFO", "Khởi động Graphic & Subtitle Engine. Tiến hành render phụ đề Karaoke và ghép nhạc nền...")
    
    media_engine = MediaService()
    
    # Render video
    try:
        final_video_path = media_engine.render_final_video(
            scenes_layout=scenes_layout,
            word_timestamps=word_timestamps,
            voice_audio_path=audio_path,
            background_video_paths=bg_video_paths,
            job_id=job_id,
            background_music_path=background_music_path
        )
        
        # Cập nhật kết quả xuất bản thành công của render
        conn = get_db_connection()
        with conn.cursor() as cursor:
            sql = """
            UPDATE video_pipeline_jobs 
            SET video_output_path = %s, pipeline_state = 'RENDERED_SUBTITLED'
            WHERE id = %s
            """
            cursor.execute(sql, (final_video_path, job_id))
        conn.close()
        
        log_realtime_progress(job_id, "VIDEO_RENDER", "SUCCESS", f"Video đã được render và chèn phụ đề thành công! Đường dẫn: {final_video_path}")
        
    except Exception as re:
        # Giải phóng tài nguyên và ném lỗi để tự phục hồi
        import gc
        gc.collect()
        log_realtime_progress(job_id, "VIDEO_RENDER", "ERROR", f"Tràn bộ nhớ hoặc lỗi render MoviePy: {re}. Tiến hành hạ độ phân giải / giải phóng RAM...")
        raise re

def handle_publish(job_id: int):
    """
    Tác vụ PUBLISH:
    1. Đọc thông tin video đã được duyệt.
    2. Mở trình duyệt Playwright Stealth (Headful cho lần đầu tiên).
    3. Đăng bài lên TikTok Studio.
    """
    log_realtime_progress(job_id, "UPLOAD_ENGINE", "INFO", f"Khởi động trình duyệt Playwright Stealth để đăng tải video Job #{job_id}...")
    
    conn = get_db_connection()
    job = None
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM video_pipeline_jobs WHERE id = %s", (job_id,))
            job = cursor.fetchone()
    finally:
        conn.close()

    if not job:
        raise Exception(f"Không tìm thấy Video Job với ID #{job_id}")

    video_path = job["video_output_path"]
    if not video_path or not os.path.exists(video_path):
        raise Exception(f"Không tìm thấy file video đầu ra để đăng: {video_path}")

    metadata = parse_job_metadata(job)
    seo_data = {}

    # Parse SEO Tags
    if job["seo_tags_metadata"]:
        try:
            seo_data = json.loads(job["seo_tags_metadata"]) if isinstance(job["seo_tags_metadata"], str) else job["seo_tags_metadata"]
        except Exception:
            seo_data = {}

    music_metadata = extract_publish_music_metadata(job)
    title, hashtags = build_publish_caption_and_hashtags(job, metadata, seo_data, music_metadata)
    if music_metadata:
        log_realtime_progress(
            job_id,
            "UPLOAD_ENGINE",
            "INFO",
            f"Sẽ chọn nhạc TikTok trước khi đăng: {music_metadata.get('song_title')} - {music_metadata.get('artist_name')} "
            f"(sound TikTok {music_metadata.get('tiktok_sound_volume_percent', 2)}%, âm gốc {music_metadata.get('original_video_volume_percent', 100)}%)"
        )
    log_realtime_progress(job_id, "UPLOAD_ENGINE", "INFO", f"Caption TikTok đã tối ưu: {title[:120]}")

    # Kiểm tra xem có cấu hình profile chrome chưa, nếu chưa thì bắt buộc chạy Headful
    profile_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "worker", "chrome_profile")
    is_new_profile = not os.path.exists(profile_path) or len(os.listdir(profile_path)) == 0
    
    force_headful = True
    if not is_new_profile:
        # Nếu đã có profile (đã đăng nhập), ta có thể cân nhắc chạy headless, nhưng người dùng yêu cầu:
        # "Bắt buộc phải chạy có giao diện (Headful mode) ở lần đầu tiên"
        # Ta sẽ chạy headful để người dùng theo dõi trực quan cho an tâm!
        force_headful = True

    publisher = PublisherService()
    
    # Thực hiện đăng bài
    success = publisher.publish_video_to_tiktok(
        video_path=video_path,
        caption=title,
        hashtags=hashtags,
        force_headful=force_headful,
        music_metadata=music_metadata
    )

    if success:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("UPDATE video_pipeline_jobs SET pipeline_state = 'PUBLISHED' WHERE id = %s", (job_id,))
        conn.close()
        log_realtime_progress(job_id, "UPLOAD_ENGINE", "SUCCESS", f"Đã đăng tải video thành công lên TikTok Studio! Trạng thái: PUBLISHED")
    else:
        raise Exception("Playwright tự động đăng video không thành công.")

def main():
    parser = argparse.ArgumentParser(description="Core Worker Python for Chat-Driven TikTok Automation")
    parser.add_argument("--job-id", type=int, required=True, help="ID của bản ghi trong database")
    parser.add_argument("--type", type=str, required=True, choices=["PLANNING", "RENDER", "PUBLISH"], help="Loại tác vụ xử lý")
    
    args = parser.parse_args()
    
    print(f"[Python Main] Running job #{args.job_id} of type {args.type}...")
    
    try:
        if args.type == "PLANNING":
            asyncio.run(handle_planning(args.job_id))
        elif args.type == "RENDER":
            asyncio.run(handle_render(args.job_id))
        elif args.type == "PUBLISH":
            handle_publish(args.job_id)
        
        sys.exit(0)
        
    except Exception as e:
        print(f"[Python Main Error] Process crashed: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
