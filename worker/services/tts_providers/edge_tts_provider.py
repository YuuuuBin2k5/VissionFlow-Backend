"""
Edge-TTS Provider — Strategy Implementation
============================================
Xử lý toàn bộ logic sinh giọng đọc qua Microsoft Edge-TTS.
Tách biệt hoàn toàn khỏi TTSEngine theo Strategy Pattern.
"""
from __future__ import annotations

import asyncio
import json
import subprocess

import edge_tts

from worker.services.tts_providers.base import TTSProvider


class EdgeTTSProvider(TTSProvider):
    """
    Strategy implementation cho Microsoft Edge-TTS (miễn phí, hỗ trợ tiếng Việt & Anh).

    Tính năng:
    - Word-boundary timestamps thời gian thực qua streaming
    - Tự động retry 3 lần với fallback rate nếu lỗi mạng
    - Fallback estimate timestamps bằng char-weight nếu streaming thất bại
    """

    # Thứ tự rate fallback khi gặp lỗi mạng
    _RATE_FALLBACK_SEQUENCE = [None, "-4%", "+0%"]  # None = dùng rate gốc từ profile

    async def synthesize(
        self,
        text: str,
        output_path: str,
        voice_profile: dict,
    ) -> list[dict]:
        raw_voice = voice_profile.get("voice", "vi-VN-NamMinhNeural")
        from worker.services.visionflow_tts import resolve_voice
        voice = resolve_voice(raw_voice)
        rate = voice_profile.get("rate", "-6%")

        print(f"[EdgeTTSProvider] Generating TTS. Voice: {voice}, Rate: {rate}")

        max_retries = 3
        rate_attempts = [rate, "-4%", "+0%"]

        for attempt in range(1, max_retries + 1):
            current_rate = rate_attempts[min(attempt - 1, len(rate_attempts) - 1)]
            try:
                word_timestamps = []
                audio_data = bytearray()
                communicate = self._build_communicate(text, voice, current_rate)

                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        audio_data.extend(chunk["data"])
                    elif chunk["type"] in ("WordBoundary", "SentenceBoundary"):
                        offset_ticks = chunk["offset"]
                        duration_ticks = chunk["duration"]
                        word = chunk["text"]
                        start_ms = offset_ticks // 10000
                        end_ms = start_ms + duration_ticks // 10000
                        cleaned = word.strip(".,!?;:\"'()[]{}""")
                        if cleaned:
                            word_timestamps.append({
                                "word": cleaned,
                                "start_ms": start_ms,
                                "end_ms": end_ms,
                            })

                if audio_data and len(audio_data) > 1000:
                    with open(output_path, "wb") as f:
                        f.write(audio_data)
                    print(f"[EdgeTTSProvider] ✅ Success. Saved to {output_path} (Rate: {current_rate})")
                    return word_timestamps

            except Exception as e:
                print(f"[EdgeTTSProvider] Attempt {attempt}/{max_retries} failed: {e}")
                if attempt == max_retries:
                    raise RuntimeError(
                        f"Edge-TTS thất bại sau {max_retries} lần thử. Lỗi cuối: {e}"
                    ) from e
                await asyncio.sleep(1.0)

        return []

    # ──────────────────────────────────────────────────────────────────────────
    # Private helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _build_communicate(
        self, text: str, voice: str, rate: str
    ) -> edge_tts.Communicate:
        """Khởi tạo Communicate object tương thích với nhiều phiên bản edge-tts."""
        import inspect

        kwargs: dict = {}
        if rate != "+0%":
            kwargs["rate"] = rate

        sig = inspect.signature(edge_tts.Communicate)
        if "boundary" in sig.parameters:
            kwargs["boundary"] = "WordBoundary"

        return edge_tts.Communicate(text, voice, **kwargs)

    @staticmethod
    def estimate_timestamps_by_char_weight(text: str, audio_path: str) -> list[dict]:
        """
        Ước lượng timestamps từ trọng số ký tự khi streaming không trả về WordBoundary.
        Dùng làm fallback trong các trường hợp Edge-TTS không gửi metadata.
        """
        duration = 0.5
        try:
            cmd = [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_format", audio_path,
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            data = json.loads(res.stdout)
            duration = float(data.get("format", {}).get("duration", 0.5))
        except Exception as e:
            print(f"[EdgeTTSProvider] ffprobe failed, using 0.5s estimate: {e}")

        words = text.split()
        if not words:
            return []

        total_ms = int(duration * 1000)
        word_lens = [len(w) for w in words]
        total_chars = max(sum(word_lens), 1)
        timestamps = []
        current_ms = 0

        for idx, word in enumerate(words):
            weight = word_lens[idx] / total_chars
            allocated = int(weight * total_ms)
            cleaned = word.strip(".,!?;:\"'()[]{}""")
            if cleaned:
                timestamps.append({
                    "word": cleaned,
                    "start_ms": current_ms,
                    "end_ms": current_ms + allocated,
                })
            current_ms += allocated

        return timestamps
