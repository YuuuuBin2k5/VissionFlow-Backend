"""TTS adapter writing audio and timestamps into a VisionFlow workspace."""
from __future__ import annotations
import asyncio
from dataclasses import dataclass
from worker.domain.render_workspace import RenderWorkspace

@dataclass(frozen=True)
class VisionFlowSpeech:
    audio_path: str
    word_timestamps: list[dict]

class VisionFlowTts:
    def synthesize(self, script: str, voice_code: str, workspace: RenderWorkspace) -> VisionFlowSpeech:
        from worker.services.tts_service import TTSService
        workspace.create()
        audio_path = str(workspace.path / "voice.mp3")
        timestamps = asyncio.run(TTSService(voice_code).generate_speech_with_timestamps(script, audio_path))
        if not timestamps:
            raise RuntimeError("TTS returned no timestamps")
        return VisionFlowSpeech(audio_path, timestamps)
