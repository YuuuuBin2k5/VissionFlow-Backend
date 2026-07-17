"""
ElevenLabs Provider — Strategy Implementation
==============================================
Xử lý toàn bộ logic gọi ElevenLabs API với word-level timestamps.
"""
from __future__ import annotations

import base64
import os

import requests

from worker.services.tts_providers.base import TTSProvider


class ElevenLabsProvider(TTSProvider):
    """
    Strategy implementation cho ElevenLabs Text-to-Speech API.

    Tính năng:
    - Word-level timestamps thực sự từ alignment API
    - Tự động merge character-level → word-level timestamps
    - Raise lỗi rõ ràng nếu thiếu API key
    """

    _API_BASE = "https://api.elevenlabs.io/v1/text-to-speech"
    _DEFAULT_VOICE_SETTINGS = {
        "stability": 0.42,
        "similarity_boost": 0.82,
        "style": 0.22,
        "use_speaker_boost": True,
    }

    async def synthesize(
        self,
        text: str,
        output_path: str,
        voice_profile: dict,
    ) -> list[dict]:
        voice_id = voice_profile.get("voice_id", "Marcus")
        model = voice_profile.get("model", "eleven_multilingual_v2")
        api_key = os.environ.get("ELEVENLABS_API_KEY", "")

        if not api_key:
            raise ValueError(
                "ELEVENLABS_API_KEY chưa được cấu hình trong file .env"
            )

        print(f"[ElevenLabsProvider] Generating TTS. Voice ID: {voice_id}, Model: {model}")

        url = f"{self._API_BASE}/{voice_id}/with-timestamps"
        headers = {"xi-api-key": api_key, "Content-Type": "application/json"}
        body = {
            "text": text,
            "model_id": model,
            "voice_settings": self._DEFAULT_VOICE_SETTINGS,
        }

        response = requests.post(url, headers=headers, json=body, timeout=30)

        if response.status_code != 200:
            raise RuntimeError(
                f"ElevenLabs API lỗi {response.status_code}: {response.text[:200]}"
            )

        res_data = response.json()
        audio_bytes = base64.b64decode(res_data.get("audio_base64", ""))
        with open(output_path, "wb") as f:
            f.write(audio_bytes)

        alignment = res_data.get("alignment", {})
        word_timestamps = self._merge_char_alignment_to_words(alignment)

        print(f"[ElevenLabsProvider] ✅ Success. Saved to {output_path}. Words: {len(word_timestamps)}")
        return word_timestamps

    # ──────────────────────────────────────────────────────────────────────────
    # Private helpers
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _merge_char_alignment_to_words(alignment: dict) -> list[dict]:
        """
        Gộp character-level alignment từ ElevenLabs thành word-level timestamps.
        ElevenLabs trả về từng ký tự một, cần gom thành từ để SubtitleRenderer sử dụng.
        """
        characters = alignment.get("characters", [])
        start_times = alignment.get("character_start_times_seconds", [])
        end_times = alignment.get("character_end_times_seconds", [])

        word_timestamps: list[dict] = []
        current_chars: list[str] = []
        word_start: float | None = None
        word_end: float | None = None

        for char, start, end in zip(characters, start_times, end_times):
            if char == " ":
                if current_chars:
                    word_str = "".join(current_chars).strip(".,!?;:\"'()[]{}""")
                    if word_str and word_start is not None:
                        word_timestamps.append({
                            "word": word_str,
                            "start_ms": int(word_start * 1000),
                            "end_ms": int((word_end or start) * 1000),
                        })
                    current_chars = []
                    word_start = None
                    word_end = None
            else:
                if word_start is None:
                    word_start = start
                word_end = end
                current_chars.append(char)

        # Flush từ cuối cùng
        if current_chars:
            word_str = "".join(current_chars).strip(".,!?;:\"'()[]{}""")
            if word_str and word_start is not None:
                word_timestamps.append({
                    "word": word_str,
                    "start_ms": int(word_start * 1000),
                    "end_ms": int((word_end or word_start) * 1000),
                })

        return word_timestamps
