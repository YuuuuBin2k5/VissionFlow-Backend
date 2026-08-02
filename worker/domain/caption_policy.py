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

def build_topic_hashtags(title: str, script: str = "", seo_data: dict = None, language: str = "en") -> list[str]:
    """
    Trích xuất và tự động tạo hashtags phù hợp 100% với chủ đề video.
    """
    seo_data = seo_data if isinstance(seo_data, dict) else {}
    ai_tags = seo_data.get("hashtags") or []
    
    tags = []
    seen = set()
    
    for tag in ai_tags:
        clean = str(tag).strip().lstrip("#")
        if clean and clean.lower() not in seen and clean.lower() not in ["shorts", "ai", "visionflow"]:
            tags.append(f"#{clean}")
            seen.add(clean.lower())
            
    text = f"{title} {script}".lower()
    
    keyword_map = {
        "sun bin": ["#SunBin", "#Strategy", "#AncientWisdom"],
        "maling": ["#BattleOfMaling", "#HistoryShorts"],
        "cortes": ["#HernanCortes", "#BurnTheShips", "#Mindset"],
        "history": ["#History", "#HistoryShorts"],
        "wisdom": ["#AncientWisdom", "#LifeLessons"],
        "mindset": ["#Mindset", "#SuccessMindset"],
        "triet ly": ["#TrietLyCuocSong", "#GocChiemNghiem"],
        "bai hoc": ["#BaiHocCuocSong", "#GocChiemNghiem"],
        "cuoc song": ["#LoiKhuyenCuocSong", "#GocChiemNghiem"]
    }
    
    for kw, kw_tags in keyword_map.items():
        if kw in text:
            for t in kw_tags:
                if t.lower() not in seen:
                    tags.append(t)
                    seen.add(t.lower())
                    
    defaults = (
        ["#Shorts", "#Storytelling", "#LifeLessons", "#Mindset", "#AncientWisdom", "#Strategy", "#AsinMochiiBoni"]
        if language == "en"
        else ["#BàiHọcCuộcSống", "#ChuyệnThờiXưa", "#KinhNghiệmSống", "#KểChuyện", "#TriếtLýCuộcSống", "#GócChiêmNghiệm", "#Shorts"]
    )
    
    for d in defaults:
        if d.lower() not in seen:
            tags.append(d)
            seen.add(d.lower())
            
    return _normalize_hashtags(tags[:15])

def build_high_converting_description(title: str, script: str = "", seo_data: dict = None, language: str = "en") -> str:
    """
    Dựng phần Mô tả (Description) đạt chuẩn SEO YouTube Shorts & TikTok chuyên nghiệp.
    - Kênh Tiếng Anh: Dành riêng cho AsinMochii💕Boni (100% English content & branding).
    - Kênh Tiếng Việt: Dành cho Góc Chiêm Nghiệm / Chuyện Thời Xưa (100% Vietnamese content & branding).
    """
    seo_data = seo_data if isinstance(seo_data, dict) else {}
    clean_title = str(title or "").strip()
    
    # 1. Tóm tắt nội dung & bài học
    ai_desc = seo_data.get("youtube_scannable_description") or seo_data.get("description")
    if ai_desc and len(str(ai_desc).strip()) > 60:
        summary_text = str(ai_desc).strip()
    elif script and len(script) > 30:
        summary = script.strip().replace("\n", " ")
        if len(summary) > 350:
            summary = summary[:347] + "..."
        summary_text = summary
    else:
        summary_text = clean_title

    # 2. Định dạng mô tả chuẩn phân tách riêng cho Kênh Tiếng Anh (AsinMochii Boni) và Kênh Tiếng Việt
    if language == "en":
        desc_body = (
            f"{clean_title}\n\n"
            f"📖 STORY SUMMARY & STRATEGIC INSIGHTS:\n"
            f"{summary_text}\n\n"
            f"📌 ABOUT ASINMOCHII💕BONI:\n"
            f"Inspiring short stories, ancient strategic wisdom, life lessons, mindset mastery & timeless historical narratives.\n\n"
            f"🔔 Subscribe to AsinMochii💕Boni for daily wisdom, life lessons & powerful story Shorts!"
        )
    else:
        desc_body = (
            f"{clean_title}\n\n"
            f"📖 TÓM TẮT NỘI DUNG & BÀI HỌC CỐT LÕI:\n"
            f"{summary_text}\n\n"
            f"📌 GIỚI THIỆU KÊNH GÓC CHIÊM NGHIỆM:\n"
            f"Chuyên chia sẻ bài học cuộc sống, kinh nghiệm sống, triết lý nhân sinh, câu chuyện truyền cảm hứng và ký ức thời xưa đắt giá.\n\n"
            f"🔔 Đăng ký kênh Góc Chiêm Nghiệm ngay hôm nay để thức tỉnh tâm hồn và đón xem những câu chuyện chiêm nghiệm mới nhất mỗi ngày!"
        )

    # 3. Hệ thống từ khóa Hashtags đầy đủ phân loại chuẩn SEO
    hashtags = build_topic_hashtags(title, script, seo_data, language)
    hashtag_str = " ".join(hashtags)
    
    return f"{desc_body}\n\n------------------------------------\n{hashtag_str}".strip()

def build_publish_caption_and_hashtags(job: dict, metadata: dict, seo_data: dict, music_metadata: dict) -> tuple:
    """
    Dựng caption và hashtags đăng TikTok / YouTube.
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

        hashtag_candidates = build_topic_hashtags(fallback_title, "", seo_data, language)
        return caption, hashtag_candidates

    title = seo_data.get("tiktok_microblog_caption") or seo_data.get("title") or metadata.get("seo_title") or fallback_title
    hashtags = build_topic_hashtags(title, job.get("script") or "", seo_data, language)
    return title, hashtags
