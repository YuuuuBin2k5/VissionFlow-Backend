import re


class RetentionDirectorService:
    """
    Tạo kế hoạch giữ chân người xem cho video ngắn.
    Chỉ trả về dữ liệu điều phối; không render và không gọi API ngoài.
    """

    def build_campaign_plan(self, metadata: dict, details: dict, job: dict, visual_style_plan: dict | None = None) -> dict:
        visual_style_plan = visual_style_plan or {}
        language = "en" if str(metadata.get("video_language") or job.get("video_language") or "vi").lower().startswith("en") else "vi"
        fallback_hook = "Watch this before you keep scrolling" if language == "en" else "Xem điều này trước khi bạn lướt tiếp"
        base_hook = (
            details.get("hook_text_3s")
            or job.get("hook_text_3s")
            or job.get("video_title_idea")
            or fallback_hook
        )
        title = job.get("video_title_idea") or base_hook
        concept = metadata.get("concept_description") or details.get("concept_description") or title
        variants = self._build_hook_variants(base_hook, title, concept, language)
        selected_hook = self._choose_hook(variants)

        return {
            "retention_mode": "campaign_short_form",
            "hook_variants": variants,
            "selected_hook": selected_hook,
            "hook_duration_s": float(visual_style_plan.get("hook_duration_s", 1.5)),
            "first_frame_strategy": visual_style_plan.get("first_frame_strategy", "pattern_interrupt"),
            "visual_beat_interval_s": float(visual_style_plan.get("visual_beat_interval_s", 2.0)),
            "dead_space_limit_s": 2.5,
            "caption_max_words": int(visual_style_plan.get("caption_max_words", 5)),
            "platform_shape": "vertical_9_16",
            "version": "retention_plan_v1",
        }

    def build_music_plan(
        self,
        metadata: dict,
        audio_data: dict,
        selected_viral_segment: dict | None,
        caption_timeline: list | None,
        visual_plan: dict | None = None,
    ) -> dict:
        visual_plan = visual_plan or {}
        cut_events = audio_data.get("cut_events", []) or []
        drop_events = audio_data.get("drop_events", []) or []
        first_drop = drop_events[0] if drop_events else None
        selected_viral_segment = selected_viral_segment or {}
        intro_text = (
            metadata.get("intro_hook_text")
            or metadata.get("song_title")
            or metadata.get("caption")
            or "Đoạn này đáng nghe lại"
        )

        return {
            "retention_mode": "music_reactive",
            "intro_hook_text": self._clean_hook(intro_text, limit=54),
            "hook_duration_s": float(visual_plan.get("hook_duration_s", 1.5)),
            "selected_viral_segment": selected_viral_segment,
            "starts_from_viral_segment": bool(selected_viral_segment),
            "first_drop_time": first_drop.get("time") if isinstance(first_drop, dict) else None,
            "visual_beat_interval_s": self._estimate_beat_interval(cut_events),
            "dead_space_limit_s": 2.5,
            "caption_phrase_max_words": 8,
            "chorus_color_shift": True,
            "version": "retention_plan_v1",
        }

    def _build_hook_variants(self, base_hook: str, title: str, concept: str, language: str = "vi") -> list:
        clean_base = self._clean_hook(base_hook)
        clean_title = self._clean_hook(title)
        clean_concept = self._clean_hook(concept)
        if language == "en":
            variants = [
                clean_base,
                f"The mistake nobody notices about {self._short_subject(clean_title)}",
                f"What nobody tells you about {self._short_subject(clean_concept)}",
            ]
        else:
            variants = [
                clean_base,
                f"Sai lầm ít ai nhận ra về {self._short_subject(clean_title)}",
                f"Sự thật ít ai nói về {self._short_subject(clean_concept)}",
            ]

        deduped = []
        seen = set()
        for variant in variants:
            key = variant.lower()
            if variant and key not in seen:
                deduped.append(self._clean_hook(variant, limit=86))
                seen.add(key)
        return deduped[:4]

    def _choose_hook(self, variants: list) -> str:
        if not variants:
            return "Xem điều này trước khi bạn lướt tiếp"

        def score(text: str) -> tuple:
            word_count = len(text.split())
            question_bonus = 0 if text.endswith("?") else 1
            length_penalty = abs(9 - word_count)
            too_long_penalty = 8 if word_count > 14 else 0
            return (too_long_penalty + length_penalty + question_bonus, len(text))

        return sorted(variants, key=score)[0]

    def _clean_hook(self, text: str, limit: int = 92) -> str:
        clean = re.sub(r"\s+", " ", str(text or "")).strip(" -–—:,.")
        if len(clean) <= limit:
            return clean
        shortened = clean[:limit].rsplit(" ", 1)[0].strip()
        return shortened or clean[:limit]

    def _short_subject(self, text: str) -> str:
        words = [word for word in re.split(r"\s+", text) if word]
        if not words:
            return "chủ đề này"
        return " ".join(words[:5]).strip(" -–—:,.")

    def _estimate_beat_interval(self, cut_events: list) -> float:
        times = [float(event.get("time", 0)) for event in cut_events if isinstance(event, dict) and event.get("time") is not None]
        if len(times) < 2:
            return 2.0
        gaps = [max(0.2, times[idx] - times[idx - 1]) for idx in range(1, len(times))]
        gaps = sorted(gaps)
        median = gaps[len(gaps) // 2]
        return round(min(3.0, max(1.5, median)), 3)
