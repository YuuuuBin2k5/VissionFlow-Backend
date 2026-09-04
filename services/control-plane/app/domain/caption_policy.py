import json
import re
import unicodedata

try:
    from app.domain.job_metadata import parse_job_metadata, is_music_reactive_job
except ImportError:
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

def clean_system_tags(text: str) -> str:
    """Loại bỏ 100% các nhãn tiền tố debug hoặc hệ thống rác."""
    if not text:
        return ""
    text = re.sub(r'\[(OpenCut|Studio|Prompt|Debug|AI Director|Scene|Hook|Voice|Karaoke|Step|B2|B6|B7).*?\]', '', str(text), flags=re.IGNORECASE)
    text = re.sub(r'\[.*?\]', '', text)
    text = re.sub(r'#+\s*', '', text)
    return re.sub(r'\s+', ' ', text).strip()

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

def detect_video_genre(title: str, script: str = "", explicit_genre: str = "") -> str:
    """Tự động phân loại thể loại video dựa trên nội dung kịch bản & tiêu đề."""
    if isinstance(explicit_genre, str) and explicit_genre.strip():
        return explicit_genre.strip()
    combined = f"{title} {script}".lower()
    
    mystery_keywords = [
        "mary celeste", "flannan", "bí ẩn", "mất tích", "hải đăng", "tàu ma", "bốc hơi", "rùng rợn", 
        "hồ sơ", "vụ án", "đại dương", "quái vật", "tam giác bermuda", "chết chóc", "thảm họa",
        "paranormal", "mystery", "unsolved", "ghost ship", "horror", "eerie", "investigation"
    ]
    if any(kw in combined for kw in mystery_keywords):
        return "MYSTERY_PARANORMAL_HISTORY"

    wealth_keywords = [
        "làm giàu", "tài chính", "tiền bạc", "đầu tư", "kinh doanh", "tư duy triệu phú", "thành công", 
        "wealth", "finance", "money", "investing", "business", "rich", "millionaire"
    ]
    if any(kw in combined for kw in wealth_keywords):
        return "WEALTH_FINANCE_MINDSET"

    tactics_keywords = [
        "sun bin", "tôn tẫn", "bàng quyên", "tam quốc", "tào tháo", "khổng minh", "binh pháp",
        "chiến thuật", "chiến tranh", "mã lăng", "tướng quân", "ancient tactics", "war", "battle"
    ]
    if any(kw in combined for kw in tactics_keywords):
        return "ANCIENT_STRATEGY_WAR"

    tech_keywords = [
        "khoa học", "vũ trụ", "công nghệ", "ai", "trí tuệ nhân tạo", "robot", "hố đen", "tương lai",
        "science", "universe", "technology", "artificial intelligence", "quantum", "future"
    ]
    if any(kw in combined for kw in tech_keywords):
        return "SCIENCE_TECH_FUTURE"

    philosophy_keywords = [
        "bài học", "triết lý", "nhân sinh", "kinh nghiệm sống", "thức tỉnh", "tâm hồn", "lời người xưa",
        "thời xưa", "nhân quả", "đạo làm người", "quà tặng cuộc sống", "goc chiem nghiem", "cuộc sống",
        "wisdom", "life lesson", "philosophy", "stoic", "mindset"
    ]
    if any(kw in combined for kw in philosophy_keywords):
        return "PHILOSOPHY_LIFE_LESSON"

    return "GENERAL_DISCOVERY"

def extract_entity_hashtags(title: str, script: str = "") -> list[str]:
    """Trích xuất thực thể chính xác làm Hashtags Cấp 1 (Entity)."""
    combined = f"{title} {script}".lower()
    entities = []
    
    entity_dict = {
        "mary celeste": "#MaryCeleste",
        "flannan": "#HaiDangFlannan",
        "titanic": "#Titanic",
        "bermuda": "#TamGiacBermuda",
        "dei gratia": "#DeiGratia",
        "sun bin": "#SunBin",
        "tôn tẫn": "#TonTan",
        "tào tháo": "#TaoThao",
        "khổng minh": "#KhongMinh",
        "gia cát lượng": "#GiaCatLuong",
        "khổng tử": "#KhongTu",
        "napoleon": "#Napoleon",
        "alexander": "#AlexanderTheGreat",
        "albert einstein": "#Einstein",
        "newton": "#IsaacNewton",
        "elon musk": "#ElonMusk",
        "warren buffett": "#WarrenBuffett"
    }
    
    for k, tag in entity_dict.items():
        if k in combined:
            entities.append(tag)
            
    return entities[:3]

def build_topic_hashtags(title: str, script: str = "", seo_data: dict = None, language: str = "en") -> list[str]:
    """
    Tạo Ma trận Hashtag 3 Cấp độ (Entity + Niche + Broad Discovery) chuẩn thuật toán đề xuất 2026.
    """
    seo_data = seo_data if isinstance(seo_data, dict) else {}
    clean_title = clean_system_tags(title)
    genre = detect_video_genre(clean_title, script, seo_data.get("video_genre", ""))
    
    tier1_tags = extract_entity_hashtags(clean_title, script)
    
    niche_map_vi = {
        "MYSTERY_PARANORMAL_HISTORY": ["#BiAnLichSu", "#TauMa", "#ChuyenLaTheGioi", "#HoSoBiAn", "#BiAnHangHai"],
        "PHILOSOPHY_LIFE_LESSON": ["#BaiHocCuocSong", "#TrietLyNhanSinh", "#KinhNghiemSong", "#LoiNguoiXuaDan", "#GocChiemNghiem"],
        "WEALTH_FINANCE_MINDSET": ["#TuDuyLamGiau", "#PhatTrienBanThan", "#KienThucTaiChinh", "#TuDuyKinhDoanh"],
        "ANCIENT_STRATEGY_WAR": ["#BinhPhap", "#NgheThuatQuanSu", "#ChienThuatDinhCao", "#LichSuTheGioi"],
        "SCIENCE_TECH_FUTURE": ["#KhoaHocVuTru", "#CongNgheTuongLai", "#KienThucThuVi", "#BiAnKhoaHoc"],
        "GENERAL_DISCOVERY": ["#KhamPha", "#KienThucThuVi", "#ChuyenLa", "#GocChiemNghiem"]
    }
    
    niche_map_en = {
        "MYSTERY_PARANORMAL_HISTORY": ["#UnsolvedMystery", "#GhostShip", "#HistoryMysteries", "#ParanormalShorts", "#TrueStory"],
        "PHILOSOPHY_LIFE_LESSON": ["#LifeLessons", "#AncientWisdom", "#MindsetMatters", "#PersonalGrowth", "#AsinMochiiBoni"],
        "WEALTH_FINANCE_MINDSET": ["#WealthMindset", "#FinancialWisdom", "#SuccessHabits", "#MillionaireMindset"],
        "ANCIENT_STRATEGY_WAR": ["#AncientStrategy", "#ArtOfWar", "#MilitaryHistory", "#TacticsAndStrategy"],
        "SCIENCE_TECH_FUTURE": ["#SpaceScience", "#FutureTech", "#UniverseMysteries", "#ScienceFacts"],
        "GENERAL_DISCOVERY": ["#Storytelling", "#DidYouKnow", "#CuriousFacts", "#AsinMochiiBoni"]
    }
    
    tier2_tags = niche_map_vi.get(genre, niche_map_vi["GENERAL_DISCOVERY"]) if language == "vi" else niche_map_en.get(genre, niche_map_en["GENERAL_DISCOVERY"])
    tier3_tags = []
    
    combined_tags = []
    seen = set()
    for t in tier1_tags + tier2_tags + tier3_tags:
        clean = t.strip()
        if clean.lower() not in seen:
            combined_tags.append(clean)
            seen.add(clean.lower())
            
    return _normalize_hashtags(combined_tags[:5])

def build_high_converting_description(title: str, script: str = "", seo_data: dict = None, language: str = "en") -> str:
    """
    Dựng phần Mô tả (Description) đạt chuẩn SEO YouTube Shorts & TikTok chuyên nghiệp theo kiến trúc Kim Tự Tháp 4 Tầng.
    """
    seo_data = seo_data if isinstance(seo_data, dict) else {}
    clean_title = clean_system_tags(title)
    genre = detect_video_genre(clean_title, script, seo_data.get("video_genre", ""))
    
    ai_desc = clean_system_tags(str(seo_data.get("youtube_scannable_description") or seo_data.get("description") or ""))
    if ai_desc and len(ai_desc) > 50 and clean_title.lower() not in ai_desc.lower():
        summary_hook = ai_desc
    elif script and len(script) > 30:
        cleaned_script = clean_system_tags(script)
        sentences = [s.strip() for s in re.split(r'[.!?\n]+', cleaned_script) if len(s.strip()) > 15]
        summary_hook = ". ".join(sentences[:2]) + "." if len(sentences) >= 2 else (cleaned_script[:240] + "...")
    else:
        summary_hook = clean_title

    sections = [summary_hook]
    context = clean_system_tags(str(seo_data.get("description_context") or ""))
    cta = clean_system_tags(str(seo_data.get("publishing_cta") or ""))
    if context:
        sections.append(context)
    if cta:
        sections.append(cta)
    desc_body = "\n\n".join(sections)

    bgm_credit_block = ""
    bgm_info = seo_data.get("music_attribution") or seo_data.get("bgm_info") or seo_data.get("selected_music") or {}
    if isinstance(bgm_info, dict) and bgm_info.get("attribution_required") is True:
        credit_txt = str(bgm_info.get("attribution_text") or "").strip()
        if credit_txt:
            bgm_credit_block = f"\n\n{credit_txt}"

    hashtags = build_topic_hashtags(clean_title, script, seo_data, language)
    hashtag_str = " ".join(hashtags)
    
    hashtag_block = f"\n\n{hashtag_str}" if hashtag_str else ""
    return f"{desc_body}{bgm_credit_block}{hashtag_block}".strip()

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
