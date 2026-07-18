class MusicVisualPlannerService:
    """
    Quyết định visual mode và mức hiệu ứng từ mood + tín hiệu audio.
    Không tải asset, không render; chỉ tạo plan có cấu trúc để các service khác dùng.
    """

    PORTRAIT_MOODS = {"SAD_RAIN", "COZY_CHILL", "FOCUS_LOFI", "SAD_REM_GIRL", "BALLAD", "EMOTIONAL"}
    BEAT_CUT_MOODS = {"CYBERPUNK_NIGHT", "STREET_VIBES", "REMIX", "DANCE", "TRENDING", "ACTION"}

    def build_plan(
        self,
        metadata: dict,
        mood: str,
        song_title: str,
        artist_name: str,
        audio_data: dict,
    ) -> dict:
        requested_mode = metadata.get("visual_mode") or "auto"
        energy_profile = self._energy_profile(audio_data)
        if metadata.get("user_provided_visual_asset") or metadata.get("user_portrait_path"):
            requested_mode = "portrait_lyric"
        visual_mode = self._choose_visual_mode(requested_mode, mood, energy_profile)
        intensity = metadata.get("effect_intensity") or self._choose_intensity(mood, energy_profile)
        theme = self._theme_for(mood, visual_mode, intensity)
        typography = metadata.get("typography_style") or metadata.get("text_effect_style") or self._choose_typography(
            mood,
            visual_mode,
            intensity,
            energy_profile,
        )

        return {
            "visual_mode": visual_mode,
            "effect_intensity": intensity,
            "typography_style": typography,
            "typography_sequence": metadata.get("typography_sequence") or self._typography_sequence(typography, intensity),
            "layout_sequence": metadata.get("layout_sequence") or self._layout_sequence(visual_mode, intensity),
            "text_reveal_style": metadata.get("text_reveal_style") or self._choose_text_reveal(intensity, energy_profile),
            "caption_style": metadata.get("caption_style"),
            "hook_duration_s": metadata.get("hook_duration_s"),
            "grain_overlay": metadata.get("grain_overlay", 0.08),
            "bloom": metadata.get("bloom", 0.08),
            "blur": metadata.get("blur", 0.0),
            "style_pack": metadata.get("style_pack"),
            "asset_keywords": metadata.get("visual_keywords") or theme["keywords"],
            "portrait_keywords": metadata.get("portrait_keywords") or theme["portrait_keywords"],
            "color_grade": metadata.get("color_grade") or theme["color_grade"],
            "accent": theme["accent"],
            "song_title": song_title,
            "artist_name": artist_name,
            "energy_profile": energy_profile,
            "version": "music_visual_plan_v1",
        }

    def _energy_profile(self, audio_data: dict) -> dict:
        bass = audio_data.get("bass", []) or []
        mid = audio_data.get("mid", []) or []
        treble = audio_data.get("treble", []) or []
        if not bass:
            return {"bass_mean": 0.0, "bass_peak": 0.0, "onset_density": 0.0, "duration": audio_data.get("duration", 0)}

        peak_count = len(audio_data.get("drop_events", []) or [])
        duration = max(1.0, float(audio_data.get("duration", 0) or (len(bass) / max(1, audio_data.get("fps", 24)))))
        return {
            "bass_mean": round(sum(bass) / len(bass), 4),
            "bass_peak": round(max(bass), 4),
            "mid_mean": round(sum(mid) / len(mid), 4) if mid else 0.0,
            "treble_mean": round(sum(treble) / len(treble), 4) if treble else 0.0,
            "onset_density": round(peak_count / duration, 4),
            "duration": round(duration, 3),
        }

    def _choose_visual_mode(self, requested_mode: str, mood: str, energy: dict) -> str:
        if requested_mode == "beat_cut_video":
            return "scenic_beat_cut"
        if requested_mode in {"portrait_lyric", "scenic_beat_cut"}:
            return requested_mode
        mood_key = (mood or "").upper()
        if mood_key in self.BEAT_CUT_MOODS or mood_key in self.PORTRAIT_MOODS:
            return "scenic_beat_cut"
        if energy.get("bass_peak", 0) > 0.82 and energy.get("onset_density", 0) > 0.08:
            return "scenic_beat_cut"
        return "scenic_beat_cut"

    def _choose_intensity(self, mood: str, energy: dict) -> str:
        mood_key = (mood or "").upper()
        if mood_key in {"REMIX", "DANCE", "CYBERPUNK_NIGHT", "STREET_VIBES"}:
            return "hard"
        if energy.get("bass_peak", 0) > 0.78 or energy.get("onset_density", 0) > 0.07:
            return "medium"
        return "soft"

    def _choose_typography(self, mood: str, visual_mode: str, intensity: str, energy: dict) -> str:
        mood_key = (mood or "").upper()
        if intensity == "hard" or mood_key in {"REMIX", "DANCE", "CYBERPUNK_NIGHT", "TRENDING"}:
            return "glass_chrome"
        if visual_mode == "portrait_lyric" and mood_key in {"SAD_RAIN", "BALLAD", "EMOTIONAL"}:
            return "liquid_glass"
        if energy.get("treble_mean", 0) > 0.28:
            return "neon_kinetic"
        return "glass_chrome"

    def _choose_text_reveal(self, intensity: str, energy: dict) -> str:
        if intensity == "hard":
            return "strobe_cut"
        if energy.get("onset_density", 0) > 0.06:
            return "wipe_reveal"
        return "float_blur"

    def _typography_sequence(self, base_style: str, intensity: str) -> list:
        if intensity == "hard":
            return [base_style, "neon_kinetic", "sticker_pop", "chrome_noir"]
        if intensity == "medium":
            return [base_style, "liquid_glass", "neon_kinetic"]
        return [base_style, "pearl_minimal", "liquid_glass"]

    def _layout_sequence(self, visual_mode: str, intensity: str) -> list:
        if visual_mode == "portrait_lyric":
            return ["bottom_center", "center_title", "side_stack"]
        if intensity == "hard":
            return ["bottom_center", "center_burst", "top_stamp", "split_caption"]
        return ["bottom_center", "center_title", "top_stamp"]

    def _theme_for(self, mood: str, visual_mode: str, intensity: str) -> dict:
        mood_key = (mood or "").upper()
        if visual_mode in {"beat_cut_video", "scenic_beat_cut"}:
            if mood_key == "CYBERPUNK_NIGHT":
                return {
                    "keywords": "cyberpunk neon city night vertical",
                    "portrait_keywords": "neon portrait aesthetic",
                    "color_grade": "neon_contrast",
                    "accent": "#ff3df2",
                }
            return {
                "keywords": "street lights night aesthetic vertical",
                "portrait_keywords": "urban portrait aesthetic",
                "color_grade": "high_contrast",
                "accent": "#72efdd" if intensity != "hard" else "#ff3df2",
            }

        if mood_key == "SAD_RAIN":
            return {
                "keywords": "rainy window lonely night vertical",
                "portrait_keywords": "sad portrait rain aesthetic",
                "color_grade": "cool_melancholy",
                "accent": "#9cc9ff",
            }
        if mood_key == "COZY_CHILL":
            return {
                "keywords": "cozy room warm lights portrait",
                "portrait_keywords": "cozy portrait warm light",
                "color_grade": "warm_soft",
                "accent": "#ffd166",
            }
        return {
            "keywords": "lofi room portrait aesthetic",
            "portrait_keywords": "lofi portrait soft light",
            "color_grade": "soft_lofi",
            "accent": "#72efdd",
        }
