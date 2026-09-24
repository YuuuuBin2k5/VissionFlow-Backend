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
    # The content package owns an explicit genre.  Keyword detection is only a
    # compatibility fallback and must not collapse new/unknown genres.
    if isinstance(explicit_genre, str) and explicit_genre.strip():
        return explicit_genre.strip()
    combined = f"{title} {script}".lower()
    
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

def _split_into_sentences(text: str) -> list[str]:
    """Tách câu thông minh, không ngắt quãng ở các số có dấu chấm như 5.000 hoặc 3.14."""
    cleaned = clean_system_tags(text)
    if not cleaned:
        return []
    raw_sentences = re.split(r'(?<=[!?])\s+|\.(?=\s+[A-ZÀ-ỸĐ0-9])|\n+', cleaned)
    return [s.strip() for s in raw_sentences if len(s.strip()) > 15]

def extract_entity_hashtags(title: str, script: str = "") -> list[str]:
    """Trích xuất thực thể chính xác làm Hashtags Cấp 1 (Entity) dùng regex word boundary."""
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
        "warren buffett": "#WarrenBuffett",
        "sao thổ": "#SaoTho",
        "hố đen": "#HoDen",
        "vũ trụ": "#VuTru",
        "ngôi mộ": "#NgoiMoCo",
        "răng": "#KhaoCoHoc",
        "hộp sọ": "#KhaoCoHoc",
        "khảo cổ": "#KhaoCoHoc",
        "gấu bắc cực": "#GauBacCuc",
        "meme 2026": "#Meme2026",
        "polar bear": "#PolarBear",
        "kim tự tháp": "#KimTuThap",
        "tam quốc": "#TamQuocDiNghia",
        "trí tuệ nhân tạo": "#TriTueNhanTao",
        "ai": "#AI"
    }
    
    for k, tag in entity_dict.items():
        if re.search(rf"(?:\b|_){re.escape(k)}(?:\b|_)", combined) and tag not in entities:
            entities.append(tag)
            
    return entities[:4]

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
    
    # Cấp 3: Kênh thương hiệu / Nhận diện
    branding_tag = ["#GocChiemNghiem"] if language == "vi" else ["#AsinMochiiBoni"]
    
    combined_tags = []
    seen = set()
    for t in tier1_tags + tier2_tags + branding_tag:
        clean = t.strip()
        if clean.lower() not in seen:
            combined_tags.append(clean)
            seen.add(clean.lower())
            
    return _normalize_hashtags(combined_tags[:8])

def build_high_converting_description(
    title: str,
    script: str = "",
    seo_data: dict = None,
    language: str = "en",
    scenes: list = None,
    brief: str = "",
    channel_handle: str = "",
) -> str:
    """
    Dựng phần Mô tả (Description) đạt chuẩn SEO YouTube Shorts & TikTok chuyên nghiệp
    theo kiến trúc Kim Tự Tháp 5 Tầng Chuyển Đổi.
    """
    seo_data = seo_data if isinstance(seo_data, dict) else {}
    scenes = scenes or seo_data.get("scenes")
    brief = brief or seo_data.get("brief") or ""
    channel_handle = channel_handle or seo_data.get("channel_handle") or "@GocChiemNghiem"

    clean_title = clean_system_tags(title)
    genre = detect_video_genre(clean_title, script, seo_data.get("video_genre", ""))
    
    # Ưu tiên mô tả do AI bên ngoài chủ động soạn thảo (>50 ký tự)
    ai_desc = clean_system_tags(str(seo_data.get("youtube_scannable_description") or seo_data.get("description") or ""))
    if ai_desc and len(ai_desc) > 50 and clean_title.lower() not in ai_desc.lower():
        desc_body = ai_desc
    else:
        # ── TẦNG 1: THE VIRAL HOOK (Câu mở đầu lôi cuốn) ─────────────────
        sentences = _split_into_sentences(script)
        
        if brief and len(brief.strip()) > 20:
            summary_hook = clean_system_tags(brief.strip())
        elif sentences:
            summary_hook = ". ".join(sentences[:2]) + "."
        else:
            summary_hook = clean_title

        # Gắn emoji chủ đề phù hợp
        genre_emojis = {
            "MYSTERY_PARANORMAL_HISTORY": " 📜🔍💀",
            "PHILOSOPHY_LIFE_LESSON": " 🌿💭✨",
            "WEALTH_FINANCE_MINDSET": " 💡📈🔥",
            "ANCIENT_STRATEGY_WAR": " ⚔️🛡️📜",
            "SCIENCE_TECH_FUTURE": " 🌌🚀🔬",
            "GENERAL_DISCOVERY": " ✨👀🔥"
        }
        if not re.search(r'[\U00010000-\U0010ffff]', summary_hook):
            summary_hook = f"{summary_hook}{genre_emojis.get(genre, ' ✨')}"

        sections = [summary_hook]

        # ── TẦNG 2: 3 SHOCKING HIGHLIGHTS (Tóm tắt 3 chi tiết từ Scenes / Script) ───
        context = clean_system_tags(str(seo_data.get("description_context") or ""))
        if context:
            sections.append(context)
        else:
            highlight_points = []
            if scenes and isinstance(scenes, list) and len(scenes) >= 3:
                sample_scenes = scenes[1:-1] if len(scenes) >= 4 else scenes
                step = max(1, len(sample_scenes) // 3)
                picked = sample_scenes[::step][:3]
                for idx, sc in enumerate(picked):
                    narr = clean_system_tags(sc.get("narration") or sc.get("text") or "")
                    overlay = clean_system_tags(sc.get("overlay_text") or "")
                    first_sent = re.split(r'[.!?\n]+', narr)[0].strip() if narr else overlay
                    if first_sent:
                        emojis = ["🔍", "⚡", "📜"]
                        labels_vi = ["Chi tiết bí ẩn", "Tình tiết cao trào", "Sự thật bất ngờ"]
                        labels_en = ["Key Mystery", "Climax Twist", "Shocking Truth"]
                        lbl = labels_vi[idx % 3] if language == "vi" else labels_en[idx % 3]
                        highlight_points.append(f"• {emojis[idx % 3]} {lbl}: {first_sent[:120]}")
            elif len(sentences) >= 4:
                mid_sentences = sentences[1:4]
                for idx, sent in enumerate(mid_sentences):
                    emojis = ["🔍", "⚡", "📜"]
                    labels_vi = ["Chi tiết bất ngờ", "Diễn biến chính", "Góc nhìn sâu sắc"]
                    labels_en = ["Key Highlight", "Core Event", "Deep Insight"]
                    lbl = labels_vi[idx % 3] if language == "vi" else labels_en[idx % 3]
                    highlight_points.append(f"• {emojis[idx % 3]} {lbl}: {sent[:120]}")

            if highlight_points:
                hl_header = "🔍 ĐIỂM NHẤN TRONG VIDEO:" if language == "vi" else "🔍 KEY STORY HIGHLIGHTS:"
                sections.append(f"{hl_header}\n" + "\n".join(highlight_points))

        # ── TẦNG 3: DEBATE / COMMENT TRIGGER (Câu hỏi kích bão bình luận) ──
        debate_questions_vi = {
            "MYSTERY_PARANORMAL_HISTORY": "💬 THEO BẠN:\nLiệu đây là một sự trùng hợp kỳ lạ, một nghi lễ cổ xưa hay bí ẩn chưa có lời giải? Bạn nghiêng về giả thuyết nào? Hãy để lại suy đoán của bạn ở phần bình luận bên dưới nhé! 👇",
            "PHILOSOPHY_LIFE_LESSON": "💬 GÓC NHÌN CỦA BẠN:\nBạn đã từng trải qua khoảnh khắc nào tương tự như câu chuyện trên chưa? Bài học lớn nhất bạn rút ra được là gì? Hãy chia sẻ câu chuyện của bạn bên dưới nhé! 👇",
            "WEALTH_FINANCE_MINDSET": "💬 BẠN NGHĨ SAO:\nNếu rơi vào hoàn cảnh này, bạn sẽ lựa chọn tiếp tục an toàn hay sẵn sàng mạo hiểm để bứt phá? Hãy để lại góc nhìn của bạn bên dưới! 👇",
            "ANCIENT_STRATEGY_WAR": "💬 BÌNH LUẬN:\nTheo bạn, mưu kế này thành công là nhờ sự may mắn hay tài thao lược đỉnh cao của người cầm quân? Để lại quan điểm của bạn nhé! 👇",
            "SCIENCE_TECH_FUTURE": "💬 THEO BẠN:\nLiệu hiện tượng hoặc công nghệ này sẽ thay đổi tương lai nhân loại như thế nào trong 10 năm tới? Để lại suy nghĩ của bạn bên dưới! 👇",
            "GENERAL_DISCOVERY": "💬 THEO BẠN:\nĐiều gì trong câu chuyện này khiến bạn bất ngờ nhất? Hãy để lại cảm nhận của bạn ở phần bình luận nhé! 👇"
        }
        debate_questions_en = {
            "MYSTERY_PARANORMAL_HISTORY": "💬 WHAT DO YOU THINK:\nWas this a bizarre coincidence, an ancient ritual, or an unsolved mystery? Drop your theories in the comments below! 👇",
            "PHILOSOPHY_LIFE_LESSON": "💬 YOUR PERSPECTIVE:\nHave you ever faced a moment like this in your own life? What was your biggest takeaway? Share your thoughts below! 👇",
            "WEALTH_FINANCE_MINDSET": "💬 WHAT WOULD YOU DO:\nIf you were in this position, would you play it safe or take the leap? Let us know in the comments! 👇",
            "ANCIENT_STRATEGY_WAR": "💬 STRATEGY DEBATE:\nWas this tactical victory pure genius or sheer luck? Share your take in the comments below! 👇",
            "SCIENCE_TECH_FUTURE": "💬 FUTURE PREDICTION:\nHow do you think this discovery or technology will reshape our world in the next decade? Drop your thoughts below! 👇",
            "GENERAL_DISCOVERY": "💬 WHAT SURPRISED YOU MOST:\nWhat part of this story caught you most off guard? Let us know in the comments below! 👇"
        }
        debate_block = (debate_questions_vi if language == "vi" else debate_questions_en).get(genre, debate_questions_vi["GENERAL_DISCOVERY"])
        sections.append(debate_block)

        # ── TẦNG 4: CALL TO ACTION (Kêu gọi Follow/Đăng ký) ───────────────
        cta = clean_system_tags(str(seo_data.get("publishing_cta") or ""))
        if cta:
            sections.append(cta)
        else:
            handle = channel_handle if channel_handle.startswith("@") else f"@{channel_handle}"
            cta_block = (
                f"👉 Đừng quên bấm THEO DÕI / ĐĂNG KÝ KÊNH {handle} để đón xem những video hấp dẫn tiếp theo mỗi ngày! ❤️"
                if language == "vi" else
                f"👉 Don't forget to LIKE, SUBSCRIBE and FOLLOW {handle} for more mind-blowing stories every day! ❤️"
            )
            sections.append(cta_block)

        desc_body = "\n\n".join(sections)

    # ── TẦNG 5: MUSIC ATTRIBUTION & DYNAMIC HASHTAG MATRIX ────────────
    bgm_credit_block = ""
    bgm_info = seo_data.get("music_attribution") or seo_data.get("bgm_info") or seo_data.get("selected_music") or {}
    if isinstance(bgm_info, dict) and bgm_info.get("attribution_required") is True:
        credit_txt = str(bgm_info.get("attribution_text") or "").strip()
        if credit_txt:
            bgm_credit_block = f"\n\n{credit_txt}"

    hashtags = build_topic_hashtags(clean_title, script, seo_data, language)
    hashtag_str = " ".join(hashtags)
    hashtag_block = f"\n\n───────────────────\n{hashtag_str}" if hashtag_str else ""

    return f"{desc_body}{bgm_credit_block}{hashtag_block}".strip()

def build_high_converting_tiktok_caption(title: str, script: str = "", seo_data: dict = None, language: str = "en") -> str:
    """
    Sinh caption TikTok dạng Micro-blogging giật gân, cách dòng thân thiện kèm câu hỏi tương tác.
    """
    seo_data = seo_data if isinstance(seo_data, dict) else {}
    clean_title = clean_system_tags(title)
    
    sentences = _split_into_sentences(script)
    
    hook = sentences[0] if sentences else clean_title
    intrigue = sentences[1] if len(sentences) > 1 else ""
    
    q = "Bạn nghĩ sao về điều này? Comment bên dưới nhé! 👇" if language == "vi" else "What are your thoughts on this? Comment below! 👇"
    
    parts = [f"{clean_title} 📜👀", hook]
    if intrigue and intrigue != hook:
        parts.append(intrigue)
    parts.append(q)
    
    hashtags = build_topic_hashtags(clean_title, script, seo_data, language)
    hashtag_str = " ".join(hashtags)
    
    return "\n\n".join(parts) + f"\n\n{hashtag_str}"

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

    title = (
        seo_data.get("tiktok_microblog_caption")
        or build_high_converting_tiktok_caption(fallback_title, job.get("script") or "", seo_data, language)
    )
    hashtags = build_topic_hashtags(fallback_title, job.get("script") or "", seo_data, language)
    return title, hashtags
