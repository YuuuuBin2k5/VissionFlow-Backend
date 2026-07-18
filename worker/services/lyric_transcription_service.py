import json
import os
import re
from pathlib import Path

from worker.config import GEMINI_API_KEYS, LYRIC_LANGUAGE, LYRIC_TRANSCRIPTION_MODEL, GROQ_API_KEY


class LyricTranscriptionService:
    """
    Tạo timeline lời nhạc từ file audio thật.
    Không tạo mock/fallback bịa lời: nếu không nhận diện được lời hát thì trả về timeline rỗng và in cảnh báo.
    """

    def transcribe_lyrics(self, audio_path: str, language: str = "default") -> list:
        source = Path(audio_path)
        if not source.exists():
            raise RuntimeError(f"Không tìm thấy file audio để nhận diện lời nhạc: {audio_path}")

        errors = []
        providers = (
            self._transcribe_with_groq_whisper,
            self._transcribe_with_gemini,
            self._transcribe_with_faster_whisper,
            self._transcribe_with_openai_whisper
        )
        for provider in providers:
            try:
                timeline = provider(source, language)
                timeline = self._normalize_timeline(timeline)
                if timeline:
                    return timeline
            except Exception as exc:
                errors.append(f"{provider.__name__}: {exc}")

        print(
            "[LyricTranscriptionService Warning] Không thể nhận diện lời nhạc từ file audio. "
            "Sử dụng chế độ không lời/instrumental (timeline trống). Chi tiết lỗi: " + " | ".join(errors[-4:])
        )
        return []


    def _transcribe_with_faster_whisper(self, audio_path: Path, language: str = "default") -> list:
        from faster_whisper import WhisperModel

        model = WhisperModel(LYRIC_TRANSCRIPTION_MODEL, device="cpu", compute_type="int8")
        if language == "default":
            target_lang = LYRIC_LANGUAGE or None
        elif language == "auto" or language is None:
            target_lang = None
        else:
            target_lang = language

        segments, _ = model.transcribe(
            str(audio_path),
            language=target_lang,
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

    def _transcribe_with_openai_whisper(self, audio_path: Path, language: str = "default") -> list:
        import whisper

        model = whisper.load_model(LYRIC_TRANSCRIPTION_MODEL)
        if language == "default":
            target_lang = LYRIC_LANGUAGE or None
        elif language == "auto" or language is None:
            target_lang = None
        else:
            target_lang = language

        result = model.transcribe(str(audio_path), language=target_lang, fp16=False)
        return [
            {"start": float(segment["start"]), "end": float(segment["end"]), "text": segment["text"]}
            for segment in result.get("segments", [])
        ]

    def _transcribe_with_groq_whisper(self, audio_path: Path, language: str = "default") -> list:
        if not GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY chưa được cấu hình")

        import requests
        url = "https://api.groq.com/openai/v1/audio/transcriptions"
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}"
        }

        if language == "default":
            target_lang = LYRIC_LANGUAGE or None
        elif language == "auto" or language is None:
            target_lang = None
        else:
            target_lang = language

        data = {
            "model": "whisper-large-v3",
            "response_format": "verbose_json"
        }
        if target_lang:
            data["language"] = target_lang

        with open(audio_path, "rb") as f:
            files = {
                "file": (audio_path.name, f, "audio/mpeg")
            }
            response = requests.post(url, headers=headers, data=data, files=files, timeout=60)

        if response.status_code != 200:
            raise RuntimeError(f"Groq Whisper API error {response.status_code}: {response.text}")

        res_data = response.json()
        segments = res_data.get("segments", [])
        return [
            {
                "start": float(segment["start"]),
                "end": float(segment["end"]),
                "text": str(segment["text"]).strip()
            }
            for segment in segments
        ]

    def _transcribe_with_gemini(self, audio_path: Path, language: str = "default") -> list:
        if not GEMINI_API_KEYS:
            raise RuntimeError("GEMINI_API_KEYS chưa được cấu hình")

        from google import genai

        if language == "default":
            target_lang = LYRIC_LANGUAGE or "auto"
        elif language == "auto" or language is None:
            target_lang = "auto"
        else:
            target_lang = language

        if target_lang == "vi":
            lang_desc = "tiếng Việt"
        elif target_lang == "en":
            lang_desc = "English"
        elif target_lang == "zh":
            lang_desc = "Chinese"
        elif target_lang == "auto":
            lang_desc = "ngôn ngữ gốc của âm thanh (hệ thống sẽ tự nhận diện)"
        else:
            lang_desc = f"ngôn ngữ '{target_lang}'"

        prompt = (
            f"Nghe file audio này và trả về JSON array timeline lời thoại/lời hát bằng {lang_desc}. "
            "Mỗi phần tử có start, end tính bằng giây và text là một cụm từ ngắn 2-7 từ. "
            "Chỉ trả JSON hợp lệ, không markdown. Không thêm lời nếu không nghe rõ."
        )
        model_names = [
            os.environ.get("GEMINI_AUDIO_MODEL"),
            os.environ.get("GEMINI_MODEL"),
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite",
            "gemini-2.5-pro",
            "gemini-2.0-flash",
        ]
        
        errors = []
        # Xoay vòng các API Key Gemini khi gặp lỗi hạn mức
        for api_key in GEMINI_API_KEYS:
            uploaded = None
            try:
                client = genai.Client(api_key=api_key)
                uploaded = client.files.upload(file=str(audio_path))
                
                for model_name in [name for index, name in enumerate(model_names) if name and name not in model_names[:index]]:
                    try:
                        response = client.models.generate_content(model=model_name, contents=[uploaded, prompt])
                        text = getattr(response, "text", "") or ""
                        match = re.search(r"\[[\s\S]*\]", text)
                        if not match:
                            raise RuntimeError("không trả JSON")
                        # Xóa file đã upload để dọn dẹp tài nguyên
                        try:
                            client.files.delete(name=uploaded.name)
                        except Exception:
                            pass
                        return json.loads(match.group(0))
                    except Exception as exc:
                        if "429" in str(exc) or "Quota exceeded" in str(exc):
                            raise exc
                        errors.append(f"{model_name} (Key: {api_key[:6]}...): {exc}")
                try:
                    if uploaded:
                        client.files.delete(name=uploaded.name)
                except Exception:
                    pass
            except Exception as key_err:
                errors.append(f"Key {api_key[:6]}... error: {key_err}")
                continue

        raise RuntimeError("Gemini không tạo được timeline lời hát sau khi thử tất cả các Keys: " + " | ".join(errors))


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
