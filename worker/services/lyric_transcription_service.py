import json
import os
import re
from pathlib import Path

from worker.config import GEMINI_API_KEY, LYRIC_LANGUAGE, LYRIC_TRANSCRIPTION_MODEL


class LyricTranscriptionService:
    """
    Tạo timeline lời nhạc từ file audio thật.
    Không tạo mock/fallback bịa lời: nếu không nhận diện được lời hát thì raise lỗi rõ ràng.
    """

    def transcribe_lyrics(self, audio_path: str) -> list:
        source = Path(audio_path)
        if not source.exists():
            raise RuntimeError(f"Không tìm thấy file audio để nhận diện lời nhạc: {audio_path}")

        errors = []
        for provider in (self._transcribe_with_faster_whisper, self._transcribe_with_openai_whisper, self._transcribe_with_gemini):
            try:
                timeline = provider(source)
                timeline = self._normalize_timeline(timeline)
                if timeline:
                    return timeline
            except Exception as exc:
                errors.append(f"{provider.__name__}: {exc}")

        raise RuntimeError(
            "Không thể nhận diện lời nhạc từ file audio. "
            "Hãy kiểm tra file có giọng hát rõ hoặc cài faster-whisper/openai-whisper, "
            "hoặc cấu hình GEMINI_API_KEY hoạt động. Chi tiết: " + " | ".join(errors[-3:])
        )

    def _transcribe_with_faster_whisper(self, audio_path: Path) -> list:
        from faster_whisper import WhisperModel

        model = WhisperModel(LYRIC_TRANSCRIPTION_MODEL, device="cpu", compute_type="int8")
        segments, _ = model.transcribe(
            str(audio_path),
            language=LYRIC_LANGUAGE or None,
            vad_filter=True,
            beam_size=5,
            word_timestamps=True,
        )
        timeline = []
        for segment in segments:
            words = getattr(segment, "words", None) or []
            if words:
                timeline.extend(self._chunk_words([
                    {"start": float(word.start), "end": float(word.end), "text": word.word}
                    for word in words
                    if getattr(word, "word", "").strip()
                ]))
            else:
                timeline.append({"start": float(segment.start), "end": float(segment.end), "text": segment.text})
        return timeline

    def _transcribe_with_openai_whisper(self, audio_path: Path) -> list:
        import whisper

        model = whisper.load_model(LYRIC_TRANSCRIPTION_MODEL)
        result = model.transcribe(str(audio_path), language=LYRIC_LANGUAGE or None, fp16=False)
        return [
            {"start": float(segment["start"]), "end": float(segment["end"]), "text": segment["text"]}
            for segment in result.get("segments", [])
        ]

    def _transcribe_with_gemini(self, audio_path: Path) -> list:
        if not GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY chưa được cấu hình")

        import google.generativeai as genai

        genai.configure(api_key=GEMINI_API_KEY)
        uploaded = genai.upload_file(str(audio_path))
        prompt = (
            "Nghe file audio này và trả về JSON array timeline lời hát tiếng Việt. "
            "Mỗi phần tử có start, end tính bằng giây và text là một cụm lời hát ngắn 2-7 từ. "
            "Chỉ trả JSON hợp lệ, không markdown. Không thêm lời nếu không nghe rõ."
        )
        model_names = [
            os.environ.get("GEMINI_AUDIO_MODEL"),
            os.environ.get("GEMINI_MODEL"),
            "gemini-2.0-flash",
            "gemini-2.5-flash",
            "gemini-1.5-flash-latest",
            "gemini-1.5-flash",
        ]
        errors = []
        for model_name in [name for index, name in enumerate(model_names) if name and name not in model_names[:index]]:
            try:
                model = genai.GenerativeModel(model_name)
                response = model.generate_content([uploaded, prompt])
                text = getattr(response, "text", "") or ""
                match = re.search(r"\[[\s\S]*\]", text)
                if not match:
                    raise RuntimeError("không trả JSON")
                return json.loads(match.group(0))
            except Exception as exc:
                errors.append(f"{model_name}: {exc}")
        raise RuntimeError("Gemini không tạo được timeline lời hát: " + " | ".join(errors))

    def _normalize_timeline(self, timeline: list) -> list:
        normalized = []
        for item in timeline or []:
            try:
                start = float(item.get("start", item.get("start_s", 0)))
                end = float(item.get("end", item.get("end_s", 0)))
            except Exception:
                continue

            text = self._clean_text(str(item.get("text", "")))
            if not text or end <= start:
                continue
            normalized.extend(self._split_long_line(start, end, text))

        normalized.sort(key=lambda item: item["start"])
        return normalized

    def _split_long_line(self, start: float, end: float, text: str) -> list:
        words = text.split()
        if len(words) <= 7:
            return [{"start": round(start, 3), "end": round(end, 3), "text": text, "kind": "lyric"}]

        chunks = []
        duration = max(0.6, end - start)
        chunk_size = 5
        word_chunks = [words[index:index + chunk_size] for index in range(0, len(words), chunk_size)]
        for index, chunk in enumerate(word_chunks):
            chunk_start = start + (duration * index / len(word_chunks))
            chunk_end = start + (duration * (index + 1) / len(word_chunks))
            chunks.append({
                "start": round(chunk_start, 3),
                "end": round(chunk_end, 3),
                "text": " ".join(chunk),
                "kind": "lyric",
            })
        return chunks

    def _chunk_words(self, words: list, max_words: int = 5, max_gap: float = 0.55) -> list:
        chunks = []
        current = []
        for word in words:
            if current and (len(current) >= max_words or float(word["start"]) - float(current[-1]["end"]) > max_gap):
                chunks.append(current)
                current = []
            current.append(word)
        if current:
            chunks.append(current)

        return [
            {
                "start": round(float(chunk[0]["start"]), 3),
                "end": round(float(chunk[-1]["end"]), 3),
                "text": " ".join(self._clean_text(word["text"]) for word in chunk).strip(),
                "kind": "lyric",
            }
            for chunk in chunks
            if chunk
        ]

    def _clean_text(self, text: str) -> str:
        text = re.sub(r"\[[^\]]+\]|\([^)]+\)", " ", text)
        text = re.sub(r"\s+", " ", text).strip(" -–—\n\t")
        return text[:96]
