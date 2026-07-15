import json
import re
import unicodedata

from worker.domain.job_metadata import parse_job_metadata, is_music_reactive_job


def extract_publish_music_metadata(job: dict) -> dict:
    """
    Lấy thông tin bài nhạc cần chọn trực tiếp trên TikTok Studio khi đăng.
    Ưu tiên metadata của video music_reactive, sau đó fallback selected_music trong SEO.
    Chỉ áp dụng với loại đăng video âm nhạc (music reactive).
    """
    metadata = parse_job_metadata(job)
    if not is_music_reactive_job(job, metadata):
        return {}

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
    seo_data = seo_data if isinstance(seo_data, dict) else {}
    metadata = metadata if isinstance(metadata, dict) else {}
    language = "en" if str(job.get("video_language") or metadata.get("video_language") or "vi").lower().startswith("en") else "vi"
    fallback_title = job.get("video_title_idea") or ("New video" if language == "en" else "Video mới")

    if music_metadata:
        song_title = music_metadata.get("song_title") or metadata.get("song_title") or fallback_title
        artist_name = music_metadata.get("artist_name") or metadata.get("artist_name") or ""
        emotional_caption = (
            metadata.get("publish_caption")
            or metadata.get("caption")
            or seo_data.get("title")
            or ("Some melodies understand the mood before words do." if language == "en" else "Có những giai điệu chỉ cần vang lên là chạm đúng tâm trạng.")
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
            or (["music", "tiktokmusic", "mood", "viral", "trending"] if language == "en" else ["nhacviet", "tiktokmusic", "tamtrang", "viral", "xuhuong"])
        )
        return caption, _normalize_hashtags(hashtag_candidates)

    title = seo_data.get("tiktok_microblog_caption") or seo_data.get("title") or metadata.get("seo_title") or fallback_title
    hashtags = seo_data.get("hashtags", [])
    if not hashtags:
        hashtags = ["learnontiktok", "automation", "tiktokagent"]
    return title, _normalize_hashtags(hashtags)
