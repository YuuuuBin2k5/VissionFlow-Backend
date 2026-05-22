import json
import os
import re
from pathlib import Path

from worker.config import GEMINI_API_KEY


class MusicViralSegmentAdvisor:
    """
    Hỏi Gemini để lấy gợi ý đoạn hook/điệp khúc/drop có khả năng viral.
    Service này chỉ trả hint có cấu trúc; AudioSignalService vẫn là nơi chốt biên cắt an toàn.
    """

    def suggest_segment(self, audio_path: str, song_title: str = "", artist_name: str = "") -> dict | None:
        if not GEMINI_API_KEY:
            return None

        source = Path(audio_path)
        if not source.exists():
            raise RuntimeError(f"Không tìm thấy file audio để Gemini phân tích đoạn viral: {audio_path}")

        import google.generativeai as genai

        genai.configure(api_key=GEMINI_API_KEY)
        uploaded = genai.upload_file(str(source))
        prompt = (
            "Bạn là editor TikTok chuyên chọn đoạn viral của bài nhạc. "
            f"Bài hát: {song_title or 'không rõ'} - {artist_name or 'không rõ'}. "
            "Nghe file audio và trả về JSON object duy nhất với các khóa: "
            "start, end, peak_start, peak_end, reason. "
            "start/end là đoạn nên dùng cho video edit, tính bằng giây trên file gốc. "
            "Đoạn phải bao trọn hook/điệp khúc/drop, không cắt cụt lúc đang hay. "
            "Ưu tiên tối thiểu 30 giây; nếu đoạn viral dài hơn, end có thể dài hơn. "
            "Chỉ trả JSON hợp lệ, không markdown."
        )
        errors = []
        for model_name in self._candidate_models():
            try:
                model = genai.GenerativeModel(model_name)
                response = model.generate_content([uploaded, prompt])
                text = getattr(response, "text", "") or ""
                parsed = self._extract_json_object(text)
                return self._normalize_hint(parsed, model_name)
            except Exception as exc:
                errors.append(f"{model_name}: {exc}")

        raise RuntimeError("Gemini không gợi ý được đoạn viral: " + " | ".join(errors))

    def _candidate_models(self) -> list:
        raw = [
            os.environ.get("GEMINI_AUDIO_MODEL"),
            os.environ.get("GEMINI_MODEL"),
            "gemini-2.0-flash",
            "gemini-2.5-flash",
            "gemini-1.5-flash-latest",
            "gemini-1.5-flash",
        ]
        candidates = []
        for name in raw:
            if name and name not in candidates:
                candidates.append(name)
        return candidates

    def _extract_json_object(self, text: str) -> dict:
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            raise RuntimeError("Gemini không trả JSON object")
        parsed = json.loads(match.group(0))
        if not isinstance(parsed, dict):
            raise RuntimeError("Gemini trả dữ liệu không phải object")
        return parsed

    def _normalize_hint(self, hint: dict, model_name: str) -> dict:
        start = max(0.0, float(hint.get("start", 0.0)))
        end = max(start, float(hint.get("end", start)))
        peak_start = max(start, float(hint.get("peak_start", start)))
        peak_end = max(peak_start, float(hint.get("peak_end", end)))
        return {
            "start": round(start, 3),
            "end": round(end, 3),
            "peak_start": round(peak_start, 3),
            "peak_end": round(peak_end, 3),
            "reason": str(hint.get("reason", "")).strip()[:240],
            "source": "gemini",
            "model": model_name,
        }
