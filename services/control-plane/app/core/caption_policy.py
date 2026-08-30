import json
import re
import unicodedata

def clean_system_tags(text: str) -> str:
    """Loại bỏ 100% các nhãn tiền tố debug hoặc hệ thống rác."""
    if not text:
        return ""
    text = re.sub(r'\[(OpenCut|Studio|Prompt|Debug|AI Director|Scene|Hook|Voice|Karaoke|Step|B2|B6|B7).*?\]', '', str(text), flags=re.IGNORECASE)
    text = re.sub(r'\[.*?\]', '', text)
    text = re.sub(r'#+\s*', '', text)
    return re.sub(r'\s+', ' ', text).strip()

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
    combined = f"{explicit_genre} {title} {script}".lower()
    
    # 1. Bí ẩn / Lịch sử / Rùng rợn / Vụ án
    mystery_keywords = [
        "mary celeste", "flannan", "bí ẩn", "mất tích", "hải đăng", "tàu ma", "bốc hơi", "rùng rợn", 
        "hồ sơ", "vụ án", "đại dương", "quái vật", "tam giác bermuda", "chết chóc", "thảm họa",
        "paranormal", "mystery", "unsolved", "ghost ship", "horror", "eerie", "investigation"
    ]
    if any(kw in combined for kw in mystery_keywords):
        return "MYSTERY_PARANORMAL_HISTORY"

    # 2. Tài chính / Làm giàu / Tư duy kinh doanh
    wealth_keywords = [
        "làm giàu", "tài chính", "tiền bạc", "đầu tư", "kinh doanh", "tư duy triệu phú", "thành công", 
        "wealth", "finance", "money", "investing", "business", "rich", "millionaire"
    ]
    if any(kw in combined for kw in wealth_keywords):
        return "WEALTH_FINANCE_MINDSET"

    # 3. Chiến thuật cổ xưa / Binh pháp / Lịch sử chiến tranh
    tactics_keywords = [
        "sun bin", "tôn tẫn", "bàng quyên", "tam quốc", "tào tháo", "khổng minh", "binh pháp",
        "chiến thuật", "chiến tranh", "mã lăng", "tướng quân", "ancient tactics", "war", "battle"
    ]
    if any(kw in combined for kw in tactics_keywords):
        return "ANCIENT_STRATEGY_WAR"

    # 4. Khoa học / Vũ trụ / Công nghệ tương lai / AI
    tech_keywords = [
        "khoa học", "vũ trụ", "công nghệ", "ai", "trí tuệ nhân tạo", "robot", "hố đen", "tương lai",
        "science", "universe", "technology", "artificial intelligence", "quantum", "future"
    ]
    if any(kw in combined for kw in tech_keywords):
        return "SCIENCE_TECH_FUTURE"

    # 5. Triết lý / Bài học cuộc sống / Đạo làm người
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
    
    # Cấp 1: Thực thể cụ thể (Entities)
    tier1_tags = extract_entity_hashtags(clean_title, script)
    
    # Cấp 2: Chủ đề ngách chuẩn xác (Niche Topic)
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
    
    # Cấp 3: Từ khóa phân phối diện rộng (Discovery / Platform)
    tier3_tags = ["#KhamPha", "#Shorts", "#Trending", "#Xuhuong"] if language == "vi" else ["#Shorts", "#Storytelling", "#ViralShorts", "#Trending"]
    
    combined_tags = []
    seen = set()
    for t in tier1_tags + tier2_tags + tier3_tags:
        clean = t.strip()
        if clean.lower() not in seen:
            combined_tags.append(clean)
            seen.add(clean.lower())
            
    return _normalize_hashtags(combined_tags[:10])

def build_high_converting_description(title: str, script: str = "", seo_data: dict = None, language: str = "en") -> str:
    """
    Dựng phần Mô tả (Description) đạt chuẩn SEO YouTube Shorts & TikTok chuyên nghiệp theo kiến trúc Kim Tự Tháp 4 Tầng.
    """
    seo_data = seo_data if isinstance(seo_data, dict) else {}
    clean_title = clean_system_tags(title)
    genre = detect_video_genre(clean_title, script, seo_data.get("video_genre", ""))
    
    # 1. Tóm tắt nội dung cốt lõi (Core Hook)
    ai_desc = clean_system_tags(str(seo_data.get("youtube_scannable_description") or seo_data.get("description") or ""))
    if ai_desc and len(ai_desc) > 50 and clean_title.lower() not in ai_desc.lower():
        summary_hook = ai_desc
    elif script and len(script) > 30:
        cleaned_script = clean_system_tags(script)
        sentences = [s.strip() for s in re.split(r'[.!?\n]+', cleaned_script) if len(s.strip()) > 15]
        summary_hook = ". ".join(sentences[:2]) + "." if len(sentences) >= 2 else (cleaned_script[:240] + "...")
    else:
        summary_hook = clean_title

    # 2. Xây dựng Khung mô tả theo từng Thể loại chuyên sâu
    if language == "vi":
        if genre == "MYSTERY_PARANORMAL_HISTORY":
            header_block = "📜 HỒ SƠ GIẢI MÃ BÍ ẨN LỊCH SỬ:"
            clues_block = (
                "🔍 NHỮNG ĐIỂM BẤT THƯỜNG TRONG VỤ ÁN:\n"
                "• Hiện trường còn nguyên vẹn, lương thực và vật dụng không hề suy suyển.\n"
                "• Nhật ký dừng lại đột ngột không lời giải thích trước khi thảm kịch xảy ra.\n"
                "• Toàn bộ nhân chứng biến mất vào hư vô giữa đại dương bao la."
            )
            debate_block = (
                "💬 GÓC TRANH LUẬN:\n"
                "Theo bạn, điều gì thực sự đã xảy ra?\n"
                "1. Sự cố tự nhiên / Khí độc bất ngờ?\n"
                "2. Cướp biển hoặc một cuộc nổi loạn nội bộ?\n"
                "3. Một bí ẩn siêu nhiên chưa có lời giải?\n"
                "👉 Hãy để lại giả thuyết của bạn dưới phần bình luận!"
            )
            branding_block = "🔔 Đăng ký kênh để đón xem những hồ sơ bí ẩn và câu chuyện ly kỳ nhất lịch sử mỗi ngày!"
        elif genre == "WEALTH_FINANCE_MINDSET":
            header_block = "💡 TƯ DUY TÀI CHÍNH & BÀI HỌC THÀNH CÔNG:"
            clues_block = (
                "📈 3 NGUYÊN TẮC CỐT LÕI:\n"
                "• Tư duy quản trị vốn và kiểm soát rủi ro trong mọi biến động.\n"
                "• Lựa chọn cơ hội dựa trên giá trị nội tại thay vì tâm lý đám đông.\n"
                "• Kỷ luật sắt đá là chìa khóa duy nhất tạo nên sự thịnh vượng bền vững."
            )
            debate_block = (
                "💬 THẢO LUẬN:\n"
                "Bạn tâm đắc nhất nguyên tắc nào trong video hôm nay? Hãy chia sẻ góc nhìn của bạn nhé!"
            )
            branding_block = "🔔 Đăng ký kênh Góc Chiêm Nghiệm để nâng tầm tư duy và làm chủ cuộc sống mỗi ngày!"
        else: # PHILOSOPHY / LIFE LESSON / GENERAL
            header_block = "📖 TÓM TẮT NỘI DUNG & BÀI HỌC CỐT LÕI:"
            clues_block = (
                "🌿 BÀI HỌC NHÂN SINH ĐẮT GIÁ:\n"
                "• Nhìn thấu bản chất con người qua từng biến cố thăng trầm.\n"
                "• Sống bao dung, giữ tâm an yên trước sóng gió cuộc đời.\n"
                "• Lời dạy của cổ nhân luôn là kim chỉ nam vượt thời gian."
            )
            debate_block = (
                "💬 GÓC CHIÊM NGHIỆM:\n"
                "Câu chuyện hôm nay để lại cho bạn suy nghĩ gì? Hãy cùng để lại bình luận phía dưới nhé!"
            )
            branding_block = "🔔 Đăng ký kênh Góc Chiêm Nghiệm ngay hôm nay để thức tỉnh tâm hồn và đón nhận năng lượng tích cực mỗi ngày!"

        desc_body = (
            f"{clean_title}\n\n"
            f"{header_block}\n"
            f"{summary_hook}\n\n"
            f"{clues_block}\n\n"
            f"{debate_block}\n\n"
            f"{branding_block}"
        )
    else: # ENGLISH
        if genre == "MYSTERY_PARANORMAL_HISTORY":
            desc_body = (
                f"{clean_title}\n\n"
                f"📜 HISTORICAL MYSTERY DOSSIER:\n"
                f"{summary_hook}\n\n"
                f"🔍 CHILLING INVESTIGATION CLUES:\n"
                f"• The ship was found fully seaworthy with untouched provisions.\n"
                f"• The logbook abruptly stopped with no sign of distress.\n"
                f"• All crew members vanished without leaving a trace into the ocean.\n\n"
                f"💬 THE DEBATE:\n"
                f"What do you believe truly happened? An unexpected hazard, foul play, or an unsolved maritime mystery?\n"
                f"👉 Drop your theory in the comments below!\n\n"
                f"🔔 Subscribe to AsinMochii💕Boni for daily captivating mysteries, ancient wisdom & strategic shorts!"
            )
        else:
            desc_body = (
                f"{clean_title}\n\n"
                f"📖 STORY SUMMARY & STRATEGIC INSIGHTS:\n"
                f"{summary_hook}\n\n"
                f"📌 ABOUT ASINMOCHII💕BONI:\n"
                f"Inspiring short stories, ancient strategic wisdom, life lessons, mindset mastery & timeless historical narratives.\n\n"
                f"🔔 Subscribe to AsinMochii💕Boni for daily wisdom, life lessons & powerful story Shorts!"
            )

    hashtags = build_topic_hashtags(clean_title, script, seo_data, language)
    hashtag_str = " ".join(hashtags)
    
    return f"{desc_body}\n\n------------------------------------\n{hashtag_str}".strip()
