import json
import re
import unicodedata

from worker.services.tts_engine import VOICE_REGISTRY


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
        tone = "stoic"
    if any(token in normalized for token in ["dong luc", "truyen cam hung", "vuot len"]):
        tone = "motivational"
    if any(token in normalized for token in ["tinh yeu", "moi quan he", "chia tay"]):
        tone = "relationship"

    format_preset = {
        "cooking": "cooking_philosophy",
        "daily_life": "daily_life_healing",
        "satisfying": "satisfying_stoic",
    }[top_visual_type]
    return {
        "render_mode": "split_screen_short",
        "content_format": "split_screen_life_philosophy",
        "format_preset": format_preset,
        "top_visual_type": top_visual_type,
        "top_asset_strategy": "local_first_long_process",
        "top_min_duration_seconds": 60 if top_visual_type == "cooking" else 0,
        "bottom_visual_type": "daily_life",
        "bottom_asset_strategy": "local_first_motion_background",
        "bottom_content_type": "philosophy_voiceover",
        "subtitle_strategy": "tts_timestamp_with_estimated_fallback",
        "tone": tone,
        "platform_targets": ["tiktok", "youtube"],
    }

def parse_voice_flag(topic_str: str) -> tuple[str, str]:
    """
    Bóc tách tham số --voice từ chuỗi topic.
    Trả về: (clean_topic, voice_code)
    """
    import re
    from worker.services.tts_engine import VOICE_REGISTRY

    voice_code = "edge-nam-minh"  # mặc định
    if not topic_str:
        return "", voice_code

    # Tìm kiếm flag --voice [mã_giọng]
    match = re.search(r'--voice\s+([a-zA-Z0-9-]+)', topic_str)
    if match:
        extracted_code = match.group(1).strip()
        if extracted_code in VOICE_REGISTRY:
            voice_code = extracted_code
        # Loại bỏ flag ra khỏi topic
        clean_topic = re.sub(r'--voice\s+[a-zA-Z0-9-]+', '', topic_str).strip()
        return clean_topic, voice_code

    return topic_str.strip(), voice_code
