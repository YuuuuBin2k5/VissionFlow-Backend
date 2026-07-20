class VideoQualityScoringService:
    """
    Chấm điểm chất lượng render theo các tiêu chí short-form.
    Kết quả dùng để lưu metadata và cảnh báo, không chặn render.
    """

    def score_campaign_plan(
        self,
        visual_style_plan: dict,
        retention_plan: dict,
        subtitle_chunks: list,
        scenes_layout: list,
        total_duration: float,
        size: tuple[int, int] = (1080, 1920),
    ) -> dict:
        warnings = []
        score = 100

        if size != (1080, 1920):
            warnings.append(f"Output should be 1080x1920, got {size[0]}x{size[1]}.")
            score -= 20

        safe_zone = visual_style_plan.get("safe_zone") or {}
        if int(safe_zone.get("bottom", 0) or 0) < 320:
            warnings.append("Bottom safe zone is too small for TikTok/Reels/Shorts UI.")
            score -= 10
        if int(safe_zone.get("x", 0) or 0) < 80:
            warnings.append("Horizontal text margin is narrow; captions may feel crowded.")
            score -= 6

        if not retention_plan.get("selected_hook") and not visual_style_plan.get("hook_text"):
            warnings.append("Missing first-frame hook text.")
            score -= 16
        if float(retention_plan.get("hook_duration_s", 0) or 0) > 2.2:
            warnings.append("Hook card lasts too long; target 1.0-1.5s for short-form.")
            score -= 5

        long_captions = [self._extract_chunk_text(chunk) for chunk in subtitle_chunks if len(self._extract_chunk_text(chunk).split()) > 6]
        if long_captions:
            warnings.append(f"{len(long_captions)} subtitle chunk(s) exceed the 3-6 word target.")
            score -= min(12, len(long_captions) * 3)

        dead_gaps = self._dead_gaps(subtitle_chunks, float(total_duration or 0), float(retention_plan.get("dead_space_limit_s", 2.5)))
        if dead_gaps:
            warnings.append(f"Detected {len(dead_gaps)} caption dead-space gap(s) over {retention_plan.get('dead_space_limit_s', 2.5)}s.")
            score -= min(12, len(dead_gaps) * 4)

        scene_durations = [float(scene.get("duration", 0) or 0) for scene in scenes_layout or []]
        if any(duration > 4.5 for duration in scene_durations):
            warnings.append("One or more scenes are longer than 4.5s; consider extra visual beats.")
            score -= 8
        if total_duration and total_duration < 5:
            warnings.append("Video duration is shorter than 5s; TikTok guidance prefers longer than 5s.")
            score -= 8

        return self._report(score, warnings)

    def _extract_chunk_text(self, chunk: object) -> str:
        if isinstance(chunk, dict):
            return str(chunk.get("text", ""))
        if isinstance(chunk, list):
            return " ".join(str(w.get("word", "")) for w in chunk if isinstance(w, dict))
        return ""

    def _extract_chunk_start_s(self, chunk: object) -> float:
        if isinstance(chunk, dict):
            return float(chunk.get("start_s", 0) or chunk.get("start_ms", 0) / 1000.0 or 0)
        if isinstance(chunk, list) and chunk and isinstance(chunk[0], dict):
            return float(chunk[0].get("start_s", 0) or chunk[0].get("start_ms", 0) / 1000.0 or 0)
        return 0.0

    def _extract_chunk_end_s(self, chunk: object) -> float:
        if isinstance(chunk, dict):
            return float(chunk.get("end_s", 0) or chunk.get("end_ms", 0) / 1000.0 or 0)
        if isinstance(chunk, list) and chunk and isinstance(chunk[-1], dict):
            return float(chunk[-1].get("end_s", 0) or chunk[-1].get("end_ms", 0) / 1000.0 or 0)
        return 0.0

    def score_music_plan(
        self,
        audio_data: dict,
        visual_plan: dict,
        retention_plan: dict,
        caption_timeline: list | None,
    ) -> dict:
        warnings = []
        score = 100
        caption_timeline = caption_timeline or []

        if not visual_plan.get("typography_sequence"):
            warnings.append("Music video has no typography sequence; style may feel static.")
            score -= 8
        if not visual_plan.get("layout_sequence"):
            warnings.append("Music video has no layout sequence; lyric placement may feel repetitive.")
            score -= 8
        if not retention_plan.get("intro_hook_text"):
            warnings.append("Music video has no intro hook text.")
            score -= 7

        duration = float(audio_data.get("duration", 0) or 0)
        cut_events = audio_data.get("cut_events", []) or []
        if duration > 8 and len(cut_events) < max(2, int(duration / 4)):
            warnings.append("Few visual cut events were detected; background may feel static.")
            score -= 10

        dead_gaps = self._dead_gaps(
            [
                {"start_s": item.get("start", 0), "end_s": item.get("end", 0), "text": item.get("text", "")}
                for item in caption_timeline
                if isinstance(item, dict)
            ],
            duration,
            float(retention_plan.get("dead_space_limit_s", 2.5)),
        )
        if dead_gaps:
            warnings.append(f"Detected {len(dead_gaps)} lyric/caption gap(s) over {retention_plan.get('dead_space_limit_s', 2.5)}s.")
            score -= min(10, len(dead_gaps) * 3)

        long_phrases = [item.get("text", "") for item in caption_timeline if isinstance(item, dict) and len(str(item.get("text", "")).split()) > 10]
        if long_phrases:
            warnings.append(f"{len(long_phrases)} lyric phrase(s) exceed the readable short-form target.")
            score -= min(10, len(long_phrases) * 3)

        return self._report(score, warnings)

    def _dead_gaps(self, chunks: list, total_duration: float, limit: float) -> list:
        if not chunks:
            return [(0.0, total_duration)] if total_duration > limit else []
        sorted_chunks = sorted(chunks, key=lambda chunk: self._extract_chunk_start_s(chunk))
        gaps = []
        cursor = 0.0
        for chunk in sorted_chunks:
            start = self._extract_chunk_start_s(chunk)
            end = max(start, self._extract_chunk_end_s(chunk))
            if start - cursor > limit:
                gaps.append((round(cursor, 3), round(start, 3)))
            cursor = max(cursor, end)
        if total_duration - cursor > limit:
            gaps.append((round(cursor, 3), round(total_duration, 3)))
        return gaps

    def _report(self, score: int, warnings: list) -> dict:
        score = max(0, min(100, int(score)))
        return {
            "quality_score": score,
            "quality_warnings": warnings,
            "quality_passed": score >= 75 and not any("Missing first-frame hook" in warning for warning in warnings),
            "version": "video_quality_score_v1",
        }
