"""
ElevenLabs Provider — Hyper-Tuned Strategy Implementation
=========================================================
Nâng cấp theo tài liệu ToiUuGiongDocAI.docx:
  - Chọn model đúng theo thể loại: eleven_v3 / eleven_multilingual_v2 / eleven_turbo_v2_5
  - Tham số Stability/Clarity/Style theo Ma trận tối ưu
  - Chunking + multi-segment synthesis (500-800 ký tự/đoạn)
  - Tích hợp ScriptPreprocessor (số→chữ, viết hoa, SSML/emotion tags)
  - Ghép timestamps chính xác sau khi merge các chunk
"""
from __future__ import annotations

import base64
import io
import os
import time
from pathlib import Path

import requests

from worker.services.tts_providers.base import TTSProvider
from worker.services.script_preprocessor import (
    ELEVENLABS_PARAMS_MAP,
    preprocess_for_elevenlabs,
)


class ElevenLabsProvider(TTSProvider):
    """
    Strategy implementation cho ElevenLabs Text-to-Speech API.

    Tính năng:
    - Word-level timestamps thực sự từ alignment API
    - Tự động merge character-level → word-level timestamps
    - Chunking 500-800 ký tự/đoạn (tránh voice drift)
    - Script pre-processing: số→chữ, viết hoa, SSML/emotion tags
    - Hyper-tuned params theo model (stability/style theo Ma trận tối ưu)
    - Raise lỗi rõ ràng nếu thiếu API key
    """

    _API_BASE = "https://api.elevenlabs.io/v1/text-to-speech"

    # Mặc định fallback khi không xác định được thể loại
    _DEFAULT_MODEL = "eleven_multilingual_v2"

    async def synthesize(
        self,
        text: str,
        output_path: str,
        voice_profile: dict,
    ) -> list[dict]:
        voice_id = voice_profile.get("voice_id", "pNInz6obpgDQGcFmaJgB")  # Adam mặc định
        model = voice_profile.get("model", self._DEFAULT_MODEL)
        genre = voice_profile.get("genre", "documentary")  # Thể loại nội dung
        api_key = os.environ.get("ELEVENLABS_API_KEY", "")

        if not api_key:
            raise ValueError("ELEVENLABS_API_KEY chưa được cấu hình trong file .env")

        # Xác định model từ thể loại nếu không được chỉ định rõ
        from worker.services.script_preprocessor import resolve_model_for_genre
        if not voice_profile.get("model"):
            model = resolve_model_for_genre(genre)

        # Lấy tham số tối ưu theo model
        voice_settings = ELEVENLABS_PARAMS_MAP.get(model, ELEVENLABS_PARAMS_MAP["eleven_multilingual_v2"])

        print(
            f"[ElevenLabsProvider] Voice ID: {voice_id}, Model: {model}, Genre: {genre}\n"
            f"  Params: stability={voice_settings['stability']}, "
            f"style={voice_settings['style']}, "
            f"similarity={voice_settings['similarity_boost']}"
        )

        # Pre-process kịch bản: số→chữ, viết hoa, SSML/emotion tags, chunking
        chunks = preprocess_for_elevenlabs(text, model_id=model)

        all_word_timestamps: list[dict] = []
        all_audio_bytes = bytearray()
        time_offset_ms = 0

        for chunk_idx, chunk_text in enumerate(chunks):
            print(
                f"[ElevenLabsProvider] Synthesizing chunk {chunk_idx + 1}/{len(chunks)}: "
                f"{len(chunk_text)} chars"
            )
            chunk_audio, chunk_timestamps = self._synthesize_chunk(
                text=chunk_text,
                voice_id=voice_id,
                model=model,
                voice_settings=voice_settings,
                api_key=api_key,
                time_offset_ms=time_offset_ms,
            )
            all_audio_bytes.extend(chunk_audio)

            # Cập nhật offset cho chunk tiếp theo
            if chunk_timestamps:
                last_ts = chunk_timestamps[-1]
                time_offset_ms = last_ts["end_ms"] + 50  # 50ms gap giữa các chunk

            all_word_timestamps.extend(chunk_timestamps)

            # Delay nhỏ giữa các API call để tránh rate limiting
            if chunk_idx < len(chunks) - 1:
                time.sleep(0.3)

        # Lưu audio bytes ra file
        with open(output_path, "wb") as f:
            f.write(all_audio_bytes)

        print(
            f"[ElevenLabsProvider] ✅ Hoàn tất. "
            f"Chunks: {len(chunks)}, Words: {len(all_word_timestamps)}, "
            f"Audio: {len(all_audio_bytes)} bytes → {output_path}"
        )
        return all_word_timestamps

    # ──────────────────────────────────────────────────────────────────────
    # Private: synthesize một chunk đơn
    # ──────────────────────────────────────────────────────────────────────

    def _synthesize_chunk(
        self,
        text: str,
        voice_id: str,
        model: str,
        voice_settings: dict,
        api_key: str,
        time_offset_ms: int = 0,
        max_retries: int = 3,
    ) -> tuple[bytes, list[dict]]:
        """
        Gọi ElevenLabs API với-timestamps cho một chunk văn bản.
        Retry tối đa 3 lần nếu thất bại.
        """
        url = f"{self._API_BASE}/{voice_id}/with-timestamps"
        headers = {"xi-api-key": api_key, "Content-Type": "application/json"}
        body = {
            "text": text,
            "model_id": model,
            "voice_settings": voice_settings,
            "language_code": "vi",  # Bắt buộc cho eleven_v3 phát âm tiếng Việt chuẩn xác
        }

        last_err: Exception | None = None
        for attempt in range(1, max_retries + 1):
            try:
                response = requests.post(url, headers=headers, json=body, timeout=45)
                if response.status_code == 200:
                    res_data = response.json()
                    audio_bytes = base64.b64decode(res_data.get("audio_base64", ""))
                    alignment = res_data.get("alignment", {})
                    word_timestamps = self._merge_char_alignment_to_words(
                        alignment, time_offset_ms
                    )
                    return audio_bytes, word_timestamps
                elif response.status_code == 429:
                    wait_time = 2 ** attempt  # Exponential backoff
                    print(
                        f"[ElevenLabsProvider Warning] Rate limited (429). "
                        f"Chờ {wait_time}s trước attempt {attempt + 1}..."
                    )
                    time.sleep(wait_time)
                else:
                    raise RuntimeError(
                        f"ElevenLabs API lỗi {response.status_code}: {response.text[:200]}"
                    )
            except Exception as e:
                last_err = e
                if attempt < max_retries:
                    print(f"[ElevenLabsProvider Warning] Attempt {attempt} thất bại: {e}. Thử lại...")
                    time.sleep(1.5 * attempt)

        raise RuntimeError(f"ElevenLabs chunk synthesis thất bại sau {max_retries} lần: {last_err}")

    # ──────────────────────────────────────────────────────────────────────
    # Private: merge character-level → word-level timestamps
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _merge_char_alignment_to_words(
        alignment: dict,
        time_offset_ms: int = 0,
    ) -> list[dict]:
        """
        Gộp character-level alignment từ ElevenLabs thành word-level timestamps.
        ElevenLabs trả về từng ký tự một, cần gom thành từ để SubtitleRenderer sử dụng.
        time_offset_ms: Offset thời gian cộng thêm (để ghép nhiều chunk).
        """
        characters = alignment.get("characters", [])
        start_times = alignment.get("character_start_times_seconds", [])
        end_times = alignment.get("character_end_times_seconds", [])

        word_timestamps: list[dict] = []
        current_chars: list[str] = []
        word_start: float | None = None
        word_end: float | None = None

        import re

        for char, start, end in zip(characters, start_times, end_times):
            if char == " ":
                if current_chars:
                    raw_word = "".join(current_chars).strip()
                    word_str = raw_word.strip(".,!?;:\"'()[]{}“”")
                    # Lọc bỏ hoàn toàn các Audio Tags dạng [excited], [dramatic], [whispers], [pause]
                    is_tag = (raw_word.startswith("[") and raw_word.endswith("]")) or bool(
                        re.match(r"^(excited|dramatic|whispers|pause|sighs|hesitates)$", word_str, re.IGNORECASE)
                    )
                    if word_str and not is_tag and word_start is not None:
                        word_timestamps.append({
                            "word": word_str,
                            "start_ms": int(word_start * 1000) + time_offset_ms,
                            "end_ms": int((word_end or start) * 1000) + time_offset_ms,
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
            raw_word = "".join(current_chars).strip()
            word_str = raw_word.strip(".,!?;:\"'()[]{}“”")
            is_tag = (raw_word.startswith("[") and raw_word.endswith("]")) or bool(
                re.match(r"^(excited|dramatic|whispers|pause|sighs|hesitates)$", word_str, re.IGNORECASE)
            )
            if word_str and not is_tag and word_start is not None:
                word_timestamps.append({
                    "word": word_str,
                    "start_ms": int(word_start * 1000) + time_offset_ms,
                    "end_ms": int((word_end or word_start) * 1000) + time_offset_ms,
                })

        return word_timestamps
