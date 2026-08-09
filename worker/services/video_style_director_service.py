class VideoStyleDirectorService:
    """
    Chọn gói giao diện cho từng loại video.
    Service này chỉ tạo plan dữ liệu; render vẫn nằm trong worker media/template services.
    """

    CAMPAIGN_PACKS = {
        "clean_authority": {
            "subtitle_style": "clean_authority",
            "caption_style": "clean_authority",
            "caption_max_words": 5,
            "hook_style": "headline_panel",
            "hook_duration_s": 1.5,
            "cta_style": "soft_badge",
            "color_grade": "clean_contrast",
            "scene_motion": "slow_zoom",
            "visual_beat_interval_s": 2.4,
            "grain_overlay": 0.08,
            "bloom": 0.0,
            "blur": 0.0,
            "accent": "#38bdf8",
            "safe_zone": {"x": 92, "top": 180, "bottom": 360},
        },
        "news_explainer": {
            "subtitle_style": "news_explainer",
            "caption_style": "word_highlight",
            "caption_max_words": 5,
            "hook_style": "top_headline",
            "hook_duration_s": 1.35,
            "cta_style": "lower_third",
            "color_grade": "editorial",
            "scene_motion": "push_in",
            "visual_beat_interval_s": 2.0,
            "grain_overlay": 0.12,
            "bloom": 0.0,
            "blur": 0.0,
            "accent": "#facc15",
            "safe_zone": {"x": 86, "top": 150, "bottom": 380},
        },
        "tiktok_punchy": {
            "subtitle_style": "bold_punchy",
            "caption_style": "bold_punchy",
            "caption_max_words": 4,
            "hook_style": "center_hook",
            "hook_duration_s": 1.25,
            "cta_style": "sticker_badge",
            "color_grade": "high_energy",
            "scene_motion": "beat_push",
            "visual_beat_interval_s": 1.7,
            "grain_overlay": 0.1,
            "bloom": 0.12,
            "blur": 0.0,
            "accent": "#ff3df2",
            "safe_zone": {"x": 96, "top": 190, "bottom": 390},
        },
        "warm_story": {
            "subtitle_style": "warm_story",
            "caption_style": "warm_story",
            "caption_max_words": 5,
            "hook_style": "center_hook",
            "hook_duration_s": 1.6,
            "cta_style": "soft_badge",
            "color_grade": "warm_soft",
            "scene_motion": "slow_zoom",
            "visual_beat_interval_s": 2.8,
            "grain_overlay": 0.14,
            "bloom": 0.04,
            "blur": 0.0,
            "accent": "#f59e0b",
            "safe_zone": {"x": 96, "top": 190, "bottom": 370},
        },
        "cinematic_minimal": {
            "subtitle_style": "clean_authority",
            "caption_style": "clean_authority",
            "caption_max_words": 5,
            "hook_style": "headline_panel",
            "hook_duration_s": 1.55,
            "cta_style": "lower_third",
            "color_grade": "cinematic_minimal",
            "scene_motion": "slow_zoom",
            "visual_beat_interval_s": 2.7,
            "grain_overlay": 0.18,
            "bloom": 0.03,
            "blur": 0.0,
            "accent": "#e5e7eb",
            "safe_zone": {"x": 110, "top": 210, "bottom": 410},
        },
    }

    MUSIC_PACKS = {
        "glass_club": {
            "typography_style": "glass_chrome",
            "typography_sequence": ["glass_chrome", "neon_kinetic", "sticker_pop", "chrome_noir"],
            "layout_sequence": ["bottom_center", "center_burst", "top_stamp", "split_caption"],
            "text_reveal_style": "strobe_cut",
            "caption_style": "lyric_glass",
            "hook_duration_s": 1.5,
            "grain_overlay": 0.1,
            "bloom": 0.2,
            "blur": 0.0,
        },
        "dream_lyric": {
            "typography_style": "liquid_glass",
            "typography_sequence": ["liquid_glass", "pearl_minimal", "glass_chrome"],
            "layout_sequence": ["bottom_center", "center_title", "side_stack"],
            "text_reveal_style": "float_blur",
            "caption_style": "lyric_glass",
            "hook_duration_s": 1.6,
            "grain_overlay": 0.16,
            "bloom": 0.08,
            "blur": 0.0,
        },
        "viral_pop": {
            "typography_style": "sticker_pop",
            "typography_sequence": ["sticker_pop", "glass_chrome", "neon_kinetic"],
            "layout_sequence": ["center_burst", "top_stamp", "bottom_center"],
            "text_reveal_style": "wipe_reveal",
            "caption_style": "karaoke_sweep",
            "hook_duration_s": 1.25,
            "grain_overlay": 0.08,
            "bloom": 0.15,
            "blur": 0.0,
        },
        "chrome_noir": {
            "typography_style": "chrome_noir",
            "typography_sequence": ["chrome_noir", "glass_chrome", "pearl_minimal"],
            "layout_sequence": ["center_title", "bottom_center", "side_stack"],
            "text_reveal_style": "wipe_reveal",
            "caption_style": "lyric_glass",
            "hook_duration_s": 1.45,
            "grain_overlay": 0.2,
            "bloom": 0.06,
            "blur": 0.0,
        },
        "neon_chaos": {
            "typography_style": "neon_kinetic",
            "typography_sequence": ["neon_kinetic", "glass_chrome", "sticker_pop", "chrome_noir"],
            "layout_sequence": ["center_burst", "split_caption", "top_stamp", "bottom_center"],
            "text_reveal_style": "strobe_cut",
            "caption_style": "karaoke_sweep",
            "hook_duration_s": 1.15,
            "grain_overlay": 0.1,
            "bloom": 0.25,
            "blur": 0.0,
        },
    }

    def build_campaign_plan(self, metadata: dict, details: dict, job: dict) -> dict:
        requested = metadata.get("visual_style_pack") or metadata.get("campaign_style_pack")
        mood = (metadata.get("music_mood") or details.get("music_mood") or "").lower()
        category = (metadata.get("content_category") or "").lower()
        title = (job.get("video_title_idea") or "").lower()

        pack_name = requested or self._choose_campaign_pack(mood, category, title)
        pack = dict(self.CAMPAIGN_PACKS.get(pack_name, self.CAMPAIGN_PACKS["tiktok_punchy"]))
        pack.update({
            "style_pack": pack_name,
            "hook_text": details.get("hook_text_3s") or job.get("hook_text_3s") or job.get("video_title_idea") or "",
            "cta_text": metadata.get("cta_text") or details.get("cta_text") or "Theo dõi để xem phần tiếp theo",
            "version": "campaign_visual_style_v1",
        })

        # Đồng bộ toàn bộ thông số xem trước từ Canvas Studio
        for canvas_key in [
            "caption_font_family", "caption_font_size", "caption_y_percent",
            "caption_color", "caption_preset", "caption_position",
            "title_banner_style", "show_title_banner", "logo_handle",
            "logo_position", "logo_opacity", "color_grading"
        ]:
            if metadata.get(canvas_key) is not None:
                pack[canvas_key] = metadata[canvas_key]

        return pack

    def apply_music_pack(self, metadata: dict) -> dict:
        pack_name = (
            metadata.get("music_style_pack")
            or metadata.get("visual_style_pack")
            or self._choose_music_pack(metadata)
        )
        pack = self.MUSIC_PACKS.get(pack_name)
        if not pack:
            return metadata
        merged = dict(metadata)
        for key, value in pack.items():
            merged.setdefault(key, value)
        merged["style_pack"] = pack_name
        return merged

    def _choose_campaign_pack(self, mood: str, category: str, title: str) -> str:
        haystack = f"{mood} {category} {title}"
        if any(token in haystack for token in ["finance", "business", "study", "education", "educational", "how to"]):
            return "clean_authority"
        if any(token in haystack for token in ["news", "update", "trend", "analysis", "case study"]):
            return "news_explainer"
        if any(token in haystack for token in ["story", "emotional", "life", "cozy", "warm"]):
            return "warm_story"
        if any(token in haystack for token in ["cinematic", "premium", "minimal", "brand"]):
            return "cinematic_minimal"
        return "tiktok_punchy"

    def _choose_music_pack(self, metadata: dict) -> str:
        mood = str(metadata.get("mood") or metadata.get("music_mood") or "").lower()
        title = str(metadata.get("song_title") or metadata.get("caption") or "").lower()
        haystack = f"{mood} {title}"
        if any(token in haystack for token in ["remix", "dance", "edm", "trap", "drop", "chaos"]):
            return "neon_chaos"
        if any(token in haystack for token in ["ballad", "sad", "emotional", "dream", "chill", "lofi"]):
            return "dream_lyric"
        if any(token in haystack for token in ["dark", "noir", "chrome", "luxury"]):
            return "chrome_noir"
        if any(token in haystack for token in ["viral", "pop", "trend", "tiktok"]):
            return "viral_pop"
        return "glass_club"
