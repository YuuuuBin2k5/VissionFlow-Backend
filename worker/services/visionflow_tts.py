"""TTS adapter writing audio and timestamps into a VisionFlow workspace."""
from __future__ import annotations
import asyncio
from dataclasses import dataclass
from worker.domain.render_workspace import RenderWorkspace

# Map từ voice preset (lưu trong CreativeSpec) → edge-tts voice name hợp lệ
VOICE_PRESET_MAP: dict[str, str] = {
    # Vietnamese
    "edge-nam-minh":   "vi-VN-NamMinhNeural",
    "edge-nam-long":   "vi-VN-NamMinhNeural",
    "edge-nu-phuong":  "vi-VN-HoaiMyNeural",
    # English
    "edge-en-guy":     "en-US-GuyNeural",
    "edge-en-jenny":   "en-US-JennyNeural",
    "edge-en-adam":    "en-US-ChristopherNeural",  # Free Edge-TTS Adam (Dominant, Firm, Middle-aged American Male)
    "eleven-adam":     "pNInz6obpgDQGcFmaJgB",     # ElevenLabs Official Adam Voice ID
}

def resolve_voice(voice_code: str) -> str:
    """Map preset name → valid edge-tts or ElevenLabs voice. Falls back to HoaiMyNeural."""
    if not voice_code:
        return "vi-VN-HoaiMyNeural"
    lower_code = voice_code.lower()
    if "adam" in lower_code:
        if "eleven" in lower_code:
            return "pNInz6obpgDQGcFmaJgB"
        return "en-US-ChristopherNeural"
    # Already a valid IETF voice name (e.g. vi-VN-HoaiMyNeural)
    if "-" in voice_code and "Neural" in voice_code:
        return voice_code
    return VOICE_PRESET_MAP.get(voice_code, "vi-VN-HoaiMyNeural")


def detect_genre_from_script(script: str) -> str:
    """
    Tự động nhận diện thể loại nội dung từ kịch bản để chọn model ElevenLabs phù hợp.
    Nguồn: ToiUuGiongDocAI.docx — Ma trận Thiết lập Tham số ElevenLabs.

    Returns:
        "documentary"  → eleven_v3 (kể chuyện kịch tính, true-crime)
        "explainer"    → eleven_multilingual_v2 (giải thích kiến thức)
        "promo"        → eleven_turbo_v2_5 (quảng cáo, bán hàng)
        "tutorial"     → eleven_turbo_v2_5 (hướng dẫn kỹ thuật)
    """
    script_lower = script.lower()

    # Từ khóa kịch bản kịch tính / documentary
    documentary_keywords = [
        "thảm họa", "thất bại", "sụp đổ", "phá sản", "bí mật", "sự thật",
        "true crime", "scandal", "disaster", "collapse", "secret", "shocking",
        "câu chuyện", "năm ", "thế kỷ", "lịch sử", "kinh hoàng", "triệu view",
        "bài học", "kỳ diệu", "huyền thoại", "coca", "airbnb", "apple",
    ]
    # Từ khóa giải thích / explainer
    explainer_keywords = [
        "cách", "làm thế nào", "tại sao", "giải thích", "hướng dẫn cơ bản",
        "nguyên nhân", "phân tích", "so sánh", "khái niệm",
        "how to", "why", "explain", "because", "reason",
    ]
    # Từ khóa quảng cáo / promo
    promo_keywords = [
        "mua ngay", "ưu đãi", "giảm giá", "miễn phí", "đặt hàng",
        "buy now", "discount", "offer", "sale", "promo",
    ]
    # Từ khóa tutorial
    tutorial_keywords = [
        "bước 1", "bước 2", "hướng dẫn từng bước", "cài đặt", "cấu hình",
        "step 1", "step 2", "install", "configure", "setup",
    ]

    doc_score = sum(1 for kw in documentary_keywords if kw in script_lower)
    exp_score = sum(1 for kw in explainer_keywords if kw in script_lower)
    promo_score = sum(1 for kw in promo_keywords if kw in script_lower)
    tutorial_score = sum(1 for kw in tutorial_keywords if kw in script_lower)

    scores = {
        "documentary": doc_score,
        "explainer": exp_score,
        "promo": promo_score,
        "tutorial": tutorial_score,
    }
    best_genre = max(scores, key=scores.get)
    best_score = scores[best_genre]

    # Mặc định documentary nếu không có từ khóa rõ ràng
    if best_score == 0:
        return "documentary"

    print(f"[VisionFlowTts] Genre detection: {scores} → detected={best_genre}")
    return best_genre


@dataclass(frozen=True)
class VisionFlowSpeech:
    audio_path: str
    word_timestamps: list[dict]

class VisionFlowTts:
    def synthesize(self, script: str, voice_code: str, workspace: RenderWorkspace, voice_rate: float = 1.12) -> VisionFlowSpeech:
        from worker.services.tts_service import TTSService
        resolved_voice = resolve_voice(voice_code)
        rate_percent = int((voice_rate - 1.0) * 100)
        rate_str = f"+{rate_percent}%" if rate_percent >= 0 else f"{rate_percent}%"
        workspace.create()
        audio_path = str(workspace.path / "voice.mp3")

        # Tự động nhận diện thể loại để chọn model ElevenLabs phù hợp
        genre = detect_genre_from_script(script)

        timestamps = asyncio.run(
            TTSService(resolved_voice).generate_speech_with_timestamps(
                script, audio_path, rate_str=rate_str, genre=genre
            )
        )
        if not timestamps:
            raise RuntimeError("TTS returned no timestamps")
        return VisionFlowSpeech(audio_path, timestamps)
