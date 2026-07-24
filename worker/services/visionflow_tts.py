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
        timestamps = asyncio.run(TTSService(resolved_voice).generate_speech_with_timestamps(script, audio_path, rate_str=rate_str))
        if not timestamps:
            raise RuntimeError("TTS returned no timestamps")
        return VisionFlowSpeech(audio_path, timestamps)
