import json
import re
import unicodedata

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

    # 2. Định dạng mô tả chuẩn phân tách riêng cho Kênh Tiếng Anh và Kênh Tiếng Việt
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
