"""
FPT.AI TTS Provider — Strategy Implementation
===============================================
Xử lý toàn bộ logic gọi FPT.AI Text-to-Speech API bao gồm async polling.
"""
from __future__ import annotations

import asyncio
import os

import requests

from worker.services.tts_providers.base import TTSProvider
from worker.services.tts_providers.edge_tts_provider import EdgeTTSProvider


class FPTAIProvider(TTSProvider):
    """
    Strategy implementation cho FPT.AI Text-to-Speech API.

    Tính năng:
    - Hỗ trợ async polling link (FPT.AI trả kết quả bất đồng bộ)
    - Timestamps ước lượng bằng char-weight (FPT không có word-level API)
    - Raise lỗi rõ ràng nếu thiếu API key
    """

    _API_URL = "https://api.fpt.ai/hmi/tts/v5"
    _MAX_POLL_ATTEMPTS = 20
    _POLL_INTERVAL_SECONDS = 1.5

    async def synthesize(
        self,
        text: str,
        output_path: str,
        voice_profile: dict,
    ) -> list[dict]:
        speaker = voice_profile.get("speaker", "minhquang")
        speed = str(voice_profile.get("speed", "0.9"))
        api_key = os.environ.get("FPTAI_API_KEY", "")

        if not api_key:
            raise ValueError(
                "FPTAI_API_KEY chưa được cấu hình trong file .env"
            )

        print(f"[FPTAIProvider] Generating TTS. Speaker: {speaker}, Speed: {speed}")

        headers = {
            "api_key": api_key,
            "voice": speaker,
            "speed": speed,
            "format": "mp3",
        }

        response = requests.post(
            self._API_URL,
            headers=headers,
            data=text.encode("utf-8"),
            timeout=15,
        )

        if response.status_code != 200:
            raise RuntimeError(
                f"FPT.AI API lỗi {response.status_code}: {response.text[:200]}"
            )

        res_data = response.json()
        async_link = res_data.get("async_link")
        if not async_link:
            raise RuntimeError(f"FPT.AI không trả về async_link: {res_data.get('message')}")

        print(f"[FPTAIProvider] Polling async link: {async_link}")
        audio_bytes = await self._poll_audio(async_link)

        with open(output_path, "wb") as f:
            f.write(audio_bytes)

        # FPT.AI không cung cấp word-level timestamps → dùng char-weight estimate
        timestamps = EdgeTTSProvider.estimate_timestamps_by_char_weight(text, output_path)
        print(f"[FPTAIProvider] ✅ Success. Saved to {output_path}. Words (estimated): {len(timestamps)}")
        return timestamps

    # ──────────────────────────────────────────────────────────────────────────
    # Private helpers
    # ──────────────────────────────────────────────────────────────────────────

    async def _poll_audio(self, async_link: str) -> bytes:
        """
        Poll FPT.AI async link cho đến khi file audio sẵn sàng.
        Timeout sau MAX_POLL_ATTEMPTS lần thử.
        """
        for attempt in range(self._MAX_POLL_ATTEMPTS):
            await asyncio.sleep(self._POLL_INTERVAL_SECONDS)
            try:
                poll_response = requests.get(async_link, timeout=10)
                if poll_response.status_code == 200:
                    content_type = poll_response.headers.get("Content-Type", "")
                    if "json" not in content_type:
                        # Audio đã sẵn sàng — trả về binary content
                        return poll_response.content
            except Exception as e:
                print(f"[FPTAIProvider] Poll attempt {attempt + 1} error: {e}")

        raise TimeoutError(
            f"FPT.AI async polling timed out sau {self._MAX_POLL_ATTEMPTS} lần thử "
            f"({self._MAX_POLL_ATTEMPTS * self._POLL_INTERVAL_SECONDS:.0f}s)"
        )
