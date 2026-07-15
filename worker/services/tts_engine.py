import asyncio
import re

from worker.services.tts_providers import TTS_PROVIDER_REGISTRY

VOICE_REGISTRY = {
    "edge-nam-minh": {"source": "edge-tts", "voice": "vi-VN-NamMinhNeural", "rate": "-6%"},
    "edge-nu-hoai-an": {"source": "edge-tts", "voice": "vi-VN-HoaiAnNeural", "rate": "-4%"},
    "edge-en-guy": {"source": "edge-tts", "voice": "en-US-GuyNeural", "rate": "-4%"},
    "edge-en-jenny": {"source": "edge-tts", "voice": "en-US-JennyNeural", "rate": "-2%"},
    "eleven-marcus": {"source": "elevenlabs", "voice_id": "Marcus", "model": "eleven_multilingual_v2"},
    "eleven-adam": {"source": "elevenlabs", "voice_id": "Adam", "model": "eleven_multilingual_v2"},
    "fpt-minh-quang": {"source": "fptai", "speaker": "minhquang", "speed": "0.9"},
}

class TTSEngine:
    def __init__(self):
        pass

    def _merge_alignments_to_words(self, alignment: dict) -> list:
        """
        Gộp character-level alignments từ ElevenLabs thành word-level timestamps.
        """
        characters = alignment.get("characters", [])
        start_times = alignment.get("character_start_times_seconds", [])
        end_times = alignment.get("character_end_times_seconds", [])

        word_timestamps = []
        current_word_chars = []
        current_start_time = None
        current_end_time = None

        for char, start, end in zip(characters, start_times, end_times):
            if char == " ":
                if current_word_chars:
                    word_str = "".join(current_word_chars)
                    cleaned_word = word_str.strip(".,!?;:\"'()[]{}“”")
                    if cleaned_word:
                        word_timestamps.append({
                            "word": cleaned_word,
                            "start_ms": int(current_start_time * 1000),
                            "end_ms": int(current_end_time * 1000)
                        })
                    current_word_chars = []
                    current_start_time = None
                    current_end_time = None
            else:
                if current_start_time is None:
                    current_start_time = start
                current_end_time = end
                current_word_chars.append(char)

        if current_word_chars:
            word_str = "".join(current_word_chars)
            cleaned_word = word_str.strip(".,!?;:\"'()[]{}“”")
            if cleaned_word:
                word_timestamps.append({
                    "word": cleaned_word,
                    "start_ms": int(current_start_time * 1000),
                    "end_ms": int(current_end_time * 1000)
                })

        return word_timestamps

    def _estimate_timestamps_by_char_weight(self, text: str, audio_path: str) -> list:
        """
        Ước lượng timestamps cấp từ dựa trên trọng số độ dài ký tự của từng từ.
        """
        duration = 0.5
        try:
            cmd = [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_format", audio_path
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            data = json.loads(res.stdout)
            duration = float(data.get("format", {}).get("duration", 0.5))
        except Exception as e:
            print(f"[TTSEngine Warning] Failed to probe duration for estimation: {e}")

        words = text.split()
        if not words:
            return []

        total_ms = int(duration * 1000)
        word_lens = [len(w) for w in words]
        total_chars = sum(word_lens)
        if total_chars == 0:
            total_chars = 1

        word_timestamps = []
        current_time_ms = 0

        for idx, word in enumerate(words):
            weight = word_lens[idx] / total_chars
            allocated_duration = int(weight * total_ms)

            start_ms = current_time_ms
            end_ms = current_time_ms + allocated_duration
            current_time_ms = end_ms

            cleaned_word = word.strip(".,!?;:\"'()[]{}“”")
            if cleaned_word:
                word_timestamps.append({
                    "word": cleaned_word,
                    "start_ms": start_ms,
                    "end_ms": end_ms
                })
        return word_timestamps

    def _prepare_tts_text_for_natural_rhythm(self, text: str) -> str:
        """
        Chuẩn hóa script trước khi đưa vào TTS để giọng đọc có nhịp nghỉ tự nhiên hơn.
        """
        normalized = str(text or "").strip()
        if not normalized:
            return ""

        normalized = normalized.replace("...", ". ")
        normalized = re.sub(r"\s*\n+\s*", ". ", normalized)
        normalized = re.sub(r"\s+", " ", normalized)
        normalized = re.sub(r"\s+([,.!?;:])", r"\1", normalized)

        sentence_markers = ["Nhưng", "Và rồi", "Bởi vì", "Thế nên", "Cuối cùng"]
        for marker in sentence_markers:
            normalized = re.sub(
                rf"(?<![.!?])\s+({re.escape(marker)})\b",
                rf". \1",
                normalized,
                flags=re.IGNORECASE,
            )

        pause_markers = ["Bạn biết không", "Sự thật là", "Điều quan trọng là"]
        for marker in pause_markers:
            normalized = re.sub(
                rf"\b{re.escape(marker)}\b\s+",
                f"{marker}, ",
                normalized,
                flags=re.IGNORECASE,
            )

        # Cắt câu quá dài thành các nhịp nhỏ
        sentence_parts = re.split(r"([.!?])", normalized)
        rebuilt = []
        for idx in range(0, len(sentence_parts), 2):
            sentence = sentence_parts[idx].strip()
            ending = sentence_parts[idx + 1] if idx + 1 < len(sentence_parts) else "."
            if not sentence:
                continue

            words = sentence.split()
            if len(words) <= 32:
                rebuilt.append(f"{sentence}{ending}")
                continue

            rebuilt.append(f"{sentence}{ending}")

        return " ".join(rebuilt).strip()

    def _create_edge_tts_communicate(self, edge_tts_module, text: str, voice: str, rate: str):
        import inspect

        kwargs = {}
        if rate != "+0%":
            kwargs["rate"] = rate

        signature = inspect.signature(edge_tts_module.Communicate)
        if "boundary" in signature.parameters:
            kwargs["boundary"] = "WordBoundary"

        return edge_tts_module.Communicate(text, voice, **kwargs)

    async def generate_tts(self, text: str, output_audio_path: str, voice_code: str) -> list:
        """
        Sinh file âm thanh từ text dựa trên cấu hình giọng đọc được chỉ định.

        Sử dụng Strategy Pattern để điều hướng đến đúng TTS Provider.
        Thêm provider mới: tạo class trong tts_providers/ và đăng ký vào TTS_PROVIDER_REGISTRY.
        File này KHÔNG cần sửa khi thêm provider (OCP compliant).
        """
        tts_text = self._prepare_tts_text_for_natural_rhythm(text)

        voice_profile = VOICE_REGISTRY.get(voice_code)
        if not voice_profile:
            print(f"[TTSEngine] Voice '{voice_code}' không có trong registry. Fallback: edge-nam-minh")
            voice_code = "edge-nam-minh"
            voice_profile = VOICE_REGISTRY["edge-nam-minh"]

        source = voice_profile.get("source", "edge-tts")

        # ── Strategy lookup ────────────────────────────────────────────────────
        provider_class = TTS_PROVIDER_REGISTRY.get(source)
        if not provider_class:
            print(f"[TTSEngine] Source '{source}' chưa được đăng ký. Fallback: edge-tts")
            source = "edge-tts"
            voice_profile = VOICE_REGISTRY["edge-nam-minh"]
            provider_class = TTS_PROVIDER_REGISTRY["edge-tts"]

        # ── Thực thi provider; fallback edge-tts nếu provider cloud lỗi ───────
        try:
            provider = provider_class()
            return await provider.synthesize(tts_text, output_audio_path, voice_profile)
        except Exception as api_err:
            if source != "edge-tts":
                print(f"[TTSEngine] Provider '{source}' thất bại: {api_err}. Fallback edge-tts...")
                fallback_profile = VOICE_REGISTRY["edge-nam-minh"]
                edge_provider = TTS_PROVIDER_REGISTRY["edge-tts"]()
                return await edge_provider.synthesize(tts_text, output_audio_path, fallback_profile)
            raise api_err
