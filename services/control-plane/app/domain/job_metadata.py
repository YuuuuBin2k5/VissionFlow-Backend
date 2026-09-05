import json
import re
import unicodedata


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

def is_translate_dub_job(job: dict, metadata: dict) -> bool:
    """
    Kiểm tra xem Job có phải là tác vụ Dịch & Lồng tiếng video tự động hay không.
    """
    return (
        metadata.get("render_mode") == "translate_dub"
        or str(job.get("video_title_idea") or "").lower().startswith("[dub]")
    )

def is_split_screen_short_job(metadata: dict) -> bool:
    return metadata.get("render_mode") == "split_screen_short"

def infer_split_screen_metadata_from_text(text: str) -> dict:
    normalized = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode("ascii").lower()
    mentions_split = any(token in normalized for token in [
        "nua tren", "phia tren", "tren la", "nua duoi", "phia duoi", "duoi la", "split screen", "shorts"
    ])
    mentions_philosophy = any(token in normalized for token in [
        "triet ly", "triet hoc", "cau noi", "cham ngon", "chua lanh", "truong thanh", "suy ngam", "bai hoc cuoc song"
    ])
    if not (mentions_split and mentions_philosophy):
        return {}

    top_visual_type = "daily_life"
    if any(token in normalized for token in ["nau an", "nau mon", "che bien", "cooking", "mon an", "pha ca phe"]):
        top_visual_type = "cooking"
    elif any(token in normalized for token in ["satisfying", "lau don", "gap quan ao", "rua xe", "sap xep", "dong goi"]):
        top_visual_type = "satisfying"

    tone = "healing"
    if any(token in normalized for token in ["ky luat", "stoic", "khac nghiet", "manh me", "ban linh"]):
        tone = "discipline"
    elif any(token in normalized for token in ["binh yen", "cham lai", "nhe nhang", "chua lanh", "an nhien"]):
        tone = "healing"

    return {
        "is_split_screen": True,
        "split_ratio": "50_50",
        "top_visual_type": top_visual_type,
        "philosophy_tone": tone,
        "auto_sfx_transition": True,
        "video_genre": "PHILOSOPHY_LIFE_LESSON",
    }

def infer_genre_from_metadata(metadata: dict) -> str:
    explicit = str(metadata.get("video_genre") or "").strip()
    if explicit:
        return explicit
    if is_split_screen_short_job(metadata):
        return "PHILOSOPHY_LIFE_LESSON"
    if metadata.get("is_paranormal") or metadata.get("theme") == "mystery":
        return "MYSTERY_PARANORMAL_HISTORY"
    if metadata.get("theme") in ("money", "wealth", "business"):
        return "WEALTH_FINANCE_MINDSET"
    if metadata.get("theme") in ("strategy", "ancient_war"):
        return "ANCIENT_STRATEGY_WAR"
    if metadata.get("theme") in ("tech", "science", "future"):
        return "SCIENCE_TECH_FUTURE"
    return "PHILOSOPHY_LIFE_LESSON"

