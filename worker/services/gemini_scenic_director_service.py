import json
import os
import re

from worker.config import GEMINI_API_KEY


MOOD_SCENIC_FALLBACKS = {
    "SAD_RAIN": ["rainy mountain road", "misty forest", "lonely ocean waves", "night rain window"],
    "COZY_CHILL": ["cozy cabin rain", "warm sunset field", "quiet coffee shop window", "soft city lights"],
    "FOCUS_LOFI": ["lofi study room", "night city rain", "calm river sunset", "train window landscape"],
    "CYBERPUNK_NIGHT": ["neon city street", "cyberpunk night rain", "urban lights vertical", "night traffic bokeh"],
}


class GeminiScenicDirectorService:
    """
    Gemini đóng vai director sinh keyword phong cảnh. Nếu Gemini lỗi, dùng keyword mood an toàn,
    không bịa lyric/tên bài/ca sĩ.
    """

    def suggest_scenic_plan(
        self,
        song_title: str,
        artist_name: str,
        caption_timeline: list,
        selected_viral_segment: dict,
        mood: str,
    ) -> dict:
        fallback = self._fallback_plan(mood)
        if not GEMINI_API_KEY:
            return fallback

        try:
            from google import genai

            client = genai.Client(api_key=GEMINI_API_KEY)
            prompt = self._build_prompt(song_title, artist_name, caption_timeline, selected_viral_segment, mood)
            errors = []
            for model_name in self._candidate_models():
                try:
                    response = client.models.generate_content(model=model_name, contents=prompt)
                    text = getattr(response, "text", "") or ""
                    parsed = self._extract_json(text)
                    keywords = parsed.get("scenic_keywords") or parsed.get("keywords") or []
                    keywords = [str(item).strip() for item in keywords if str(item or "").strip()][:6]
                    if not keywords:
                        raise RuntimeError("empty scenic_keywords")
                    return {
                        "scenic_keywords": keywords,
                        "visual_story": str(parsed.get("visual_story", "")).strip()[:500],
                        "color_grade": str(parsed.get("color_grade", fallback["color_grade"])).strip() or fallback["color_grade"],
                        "scenic_director_source": "gemini",
                        "scenic_director_model": model_name,
                    }
                except Exception as exc:
                    errors.append(f"{model_name}: {exc}")
            fallback["scenic_director_error"] = " | ".join(errors)
            return fallback
        except Exception as exc:
            fallback["scenic_director_error"] = str(exc)
            return fallback

    def _build_prompt(self, song_title: str, artist_name: str, caption_timeline: list, segment: dict, mood: str) -> str:
        lyric_lines = "\n".join(
            f"- {item.get('text', '')}"
            for item in (caption_timeline or [])[:12]
            if item.get("text")
        )
        return f"""
You are a TikTok music video director. Create scenic stock-video search keywords.

Song: {song_title}
Artist: {artist_name}
Mood: {mood}
Selected segment: {segment}
Lyric snippets:
{lyric_lines}

Return ONLY valid JSON:
{{
  "scenic_keywords": ["3-6 short English landscape/video keywords"],
  "visual_story": "one short visual direction",
  "color_grade": "soft_lofi | cool_melancholy | warm_soft | high_contrast | neon_contrast"
}}

Rules:
- Keywords must be English and search-friendly for Pexels/Pixabay.
- Prefer landscapes, city ambience, rain, ocean, mountain, forest, road, sunset, night lights.
- Do not mention real people or celebrities.
"""

    def _candidate_models(self) -> list:
        raw = [
            os.environ.get("GEMINI_MODEL"),
            os.environ.get("GEMINI_AUDIO_MODEL"),
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite",
            "gemini-2.5-pro",
            "gemini-2.0-flash",
        ]
        candidates = []
        for model_name in raw:
            if model_name and model_name not in candidates:
                candidates.append(model_name)
        return candidates

    def _extract_json(self, text: str) -> dict:
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            raise RuntimeError("Gemini did not return a JSON object")
        parsed = json.loads(match.group(0))
        if not isinstance(parsed, dict):
            raise RuntimeError("Gemini JSON is not an object")
        return parsed

    def _fallback_plan(self, mood: str) -> dict:
        mood_key = (mood or "").upper()
        return {
            "scenic_keywords": MOOD_SCENIC_FALLBACKS.get(
                mood_key,
                ["aesthetic nature vertical", "ocean sunset vertical", "misty forest vertical", "city night rain"],
            ),
            "visual_story": "Mood-based scenic fallback.",
            "color_grade": "cool_melancholy" if mood_key == "SAD_RAIN" else "soft_lofi",
            "scenic_director_source": "fallback",
            "scenic_director_fallback": "mood_keywords",
        }
