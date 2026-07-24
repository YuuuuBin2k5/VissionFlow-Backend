import asyncio
import json
import os
import edge_tts
from worker.config import DEFAULT_TTS_VOICE, ASSETS_DIR
from worker.services.script_preprocessor import (
    preprocess_for_elevenlabs,
    ELEVENLABS_PARAMS_MAP,
    resolve_model_for_genre,
)

# ElevenLabs default voice IDs
ELEVENLABS_DEFAULT_VOICES = {
    ("female", "adult"): "21m00Tcm4TlvDq8ikWAM",  # Rachel (Warm, professional female)
    ("female", "child"): "EXAVITQu4vr4xnSDxMaL",  # Bella (Child female)
    ("male", "adult"): "pNInz6obpgDQGcFmaJgB",    # Adam (Dominant, Firm, Middle-aged American Male)
    ("male", "child"): "ODq5zmAzzEx5QqdD4T6D",    # Youthful male
}

# Model mặc định cho từng thể loại nội dung
# documentary / storytelling → eleven_v3 (kể chuyện kịch tính, triệu view)
# explainer → eleven_multilingual_v2 (giải thích kiến thức)
# promo / tutorial → eleven_turbo_v2_5 (quảng cáo, hướng dẫn nhanh)
DEFAULT_ELEVENLABS_MODEL = "eleven_multilingual_v2"

# TikTok standard voice codes for Vietnamese
TIKTOK_DEFAULT_VOICES = {
    "female": "vi_vn_female",
    "male": "vi_vn_male"
}

class TTSService:
    def __init__(self, voice: str = DEFAULT_TTS_VOICE):
        self.voice = voice
        self.elevenlabs_key = os.getenv("ELEVENLABS_API_KEY")
        self.valtec_url = os.getenv("VALTEC_TTS_URL", "http://localhost:8000/api/tts")

    def _estimate_word_timestamps(self, text: str, audio_path: str) -> list:
        """
        Ước lượng timestamps cấp từ dựa trên tổng thời lượng của tệp âm thanh thực tế
        (Dành cho ElevenLabs, TikTok TTS, và gTTS không hỗ trợ Word Boundary).
        """
        import subprocess
        import json
        
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
            print(f"[TTSService Warning] Failed to probe duration for estimation: {e}")
            
        words = text.split()
        if not words:
            return []
            
        total_ms = int(duration * 1000)
        word_duration = total_ms / len(words)
        
        word_timestamps = []
        for idx, word in enumerate(words):
            start_ms = int(idx * word_duration)
            end_ms = int((idx + 1) * word_duration)
            cleaned_word = word.strip(".,!?;:\"'()[]{}“”")
            if cleaned_word:
                word_timestamps.append({
                    "word": cleaned_word,
                    "start_ms": start_ms,
                    "end_ms": end_ms
                })
        return word_timestamps

    def _call_elevenlabs(
        self,
        text: str,
        voice_id: str,
        output_path: str,
        genre: str = "documentary",
    ) -> bool:
        """
        Gọi ElevenLabs API với:
        - Model đúng theo thể loại (v3/Multilingual v2/Turbo v2.5)
        - Hyper-tuned Stability/Clarity/Style theo Ma trận tối ưu (ToiUuGiongDocAI.docx)
        - Script pre-processing: chunking + số→chữ + SSML/emotion tags
        - Multi-chunk synthesis: ghép audio + timestamps chính xác
        """
        import requests
        import base64
        import time

        try:
            # Xác định model theo thể loại nội dung
            model_id = resolve_model_for_genre(genre)
            # Lấy tham số tối ưu theo model (theo Ma trận tối ưu trong tài liệu)
            voice_settings = ELEVENLABS_PARAMS_MAP.get(
                model_id, ELEVENLABS_PARAMS_MAP["eleven_multilingual_v2"]
            )

            print(
                f"[TTSService] ElevenLabs: voice={voice_id}, model={model_id}, genre={genre}\n"
                f"  Params: stability={voice_settings['stability']}, "
                f"style={voice_settings['style']}, "
                f"similarity={voice_settings['similarity_boost']}"
            )

            # Tiền xử lý kịch bản: số→chữ, viết hoa, SSML/emotion tags, chunking
            chunks = preprocess_for_elevenlabs(text, model_id=model_id)

            url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
            headers = {
                "xi-api-key": self.elevenlabs_key,
                "Content-Type": "application/json"
            }

            all_audio_bytes = bytearray()

            for chunk_idx, chunk_text in enumerate(chunks):
                body = {
                    "text": chunk_text,
                    "model_id": model_id,
                    "voice_settings": voice_settings,
                }
                success = False
                for attempt in range(1, 4):
                    response = requests.post(url, headers=headers, json=body, timeout=45)
                    if response.status_code == 200:
                        all_audio_bytes.extend(response.content)
                        success = True
                        break
                    elif response.status_code == 429:
                        wait = 2 ** attempt
                        print(f"[TTSService] Rate limited. Chờ {wait}s...")
                        time.sleep(wait)
                    else:
                        print(
                            f"[TTSService Warning] ElevenLabs chunk {chunk_idx+1} "
                            f"status {response.status_code}: {response.text[:100]}"
                        )
                        break
                if not success:
                    print(f"[TTSService Warning] Chunk {chunk_idx+1} thất bại, bỏ qua.")

                if chunk_idx < len(chunks) - 1:
                    time.sleep(0.3)  # Tránh rate limiting

            if all_audio_bytes and len(all_audio_bytes) > 1000:
                with open(output_path, "wb") as f:
                    f.write(all_audio_bytes)
                print(
                    f"[TTSService] ✅ ElevenLabs tổng hợp {len(chunks)} chunk(s) thành công. "
                    f"Voice: {voice_id}, Model: {model_id}"
                )
                return True

            print(f"[TTSService Warning] ElevenLabs không có audio bytes hợp lệ.")
            return False
        except Exception as e:
            print(f"[TTSService Warning] ElevenLabs synthesis failed: {e}")
            return False

    def _call_valtec(self, text: str, output_path: str) -> bool:
        import requests
        try:
            body = {
                "text": text,
                "speaker": "default",
                "speed": 1.0
            }
            # Sử dụng timeout ngắn (2.5 giây) để tránh bị treo luồng khi máy chủ cục bộ không hoạt động
            response = requests.post(self.valtec_url, json=body, timeout=2.5)
            if response.status_code == 200:
                with open(output_path, "wb") as f:
                    f.write(response.content)
                print(f"[TTSService] Local valtec-tts synthesis success.")
                return True
            return False
        except Exception as e:
            print(f"[TTSService Warning] Local valtec-tts synthesis failed: {e}")
            return False

    def _call_tiktok(self, text: str, speaker: str, output_path: str) -> bool:
        import requests
        import base64
        try:
            url = "https://api16-normal-c-useast1a.tiktokv.com/media/api/text/speech/start/"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.0.0 Safari/537.36",
                "Content-Type": "application/x-www-form-urlencoded"
            }
            req_text = text.replace("+", "plus").replace(" ", "+")
            data = f"status_code=0&speaker={speaker}&req_text={req_text}"
            response = requests.post(url, headers=headers, data=data, timeout=10)
            if response.status_code == 200:
                res_data = response.json()
                if res_data.get("message") == "success" and "data" in res_data:
                    vdata = res_data["data"]["v_str"]
                    audio_bytes = base64.b64decode(vdata)
                    with open(output_path, "wb") as f:
                        f.write(audio_bytes)
                    print(f"[TTSService] TikTok TTS synthesis success using speaker: {speaker}")
                    return True
            print(f"[TTSService Warning] TikTok TTS returned status code {response.status_code}: {response.text}")
            return False
        except Exception as e:
            print(f"[TTSService Warning] TikTok TTS synthesis failed: {e}")
            return False

    def _call_gtts(self, text: str, output_path: str) -> bool:
        import requests
        import urllib.parse
        try:
            # Tự động chia nhỏ câu thoại dài hơn 200 ký tự để tránh lỗi HTTP 400 Bad Request của Google Translate API
            words = text.split()
            chunks = []
            current_chunk = []
            current_length = 0
            
            for word in words:
                word_len = len(word) + 1
                if current_length + word_len > 190:
                    chunks.append(" ".join(current_chunk))
                    current_chunk = [word]
                    current_length = word_len
                else:
                    current_chunk.append(word)
                    current_length += word_len
            if current_chunk:
                chunks.append(" ".join(current_chunk))
                
            audio_bytes = bytearray()
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.0.0 Safari/537.36"
            }
            
            for chunk in chunks:
                encoded_chunk = urllib.parse.quote(chunk)
                url = f"https://translate.google.com/translate_tts?ie=UTF-8&tl=vi&client=tw-ob&q={encoded_chunk}"
                response = requests.get(url, headers=headers, timeout=10)
                if response.status_code == 200:
                    audio_bytes.extend(response.content)
                else:
                    print(f"[TTSService Warning] Google Translate TTS chunk failed with status code {response.status_code}")
                    return False
            
            if audio_bytes:
                with open(output_path, "wb") as f:
                    f.write(audio_bytes)
                print(f"[TTSService] Google Translate TTS (gTTS) synthesis success (merged {len(chunks)} chunks).")
                return True
            return False
        except Exception as e:
            print(f"[TTSService Warning] Google Translate TTS synthesis failed: {e}")
            return False

    async def generate_speech_with_timestamps(self, text: str, output_audio_path: str, gender: str = "female", age_group: str = "adult", rate_str: str = "+12%", genre: str = "documentary") -> list:
        """
        Chuyển đổi Text sang Speech với cơ chế dự phòng đa tầng ưu việt:
        Tầng 1 (ElevenLabs) -> Tầng 2 (Local valtec-tts) -> Tầng 3 (TikTok TTS) -> Tầng 4 (Edge-TTS) -> Tầng 5 (gTTS).
        genre: Thể loại nội dung (documentary, explainer, promo, tutorial) — dùng để chọn model ElevenLabs tối ưu.
        """
        print(f"[TTSService] Synthesizing speech using Multi-Tier Fallback with rate={rate_str}, genre={genre}.")
        print(f"[TTSService] Target profile: Gender={gender}, Age={age_group}")
        print(f"[TTSService] Text length: {len(text)} characters.")
        print(f"[TTSService] Text content: '{text}'")
        
        cleaned_text = "".join(c for c in text if c.isalnum())
        if not cleaned_text.strip():
            print(f"[TTSService Warning] Text contains no alphanumeric characters. Generating silence.")
            import subprocess
            cmd_silence = [
                "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                "-t", "0.5", "-acodec", "libmp3lame", output_audio_path
            ]
            try:
                subprocess.run(cmd_silence, capture_output=True, check=True)
            except Exception as e:
                print(f"[TTSService Error] Failed to generate silence: {e}")
                with open(output_audio_path, "wb") as f:
                    f.write(b"")
            return []

        # TẦNG 1: ElevenLabs
        if self.elevenlabs_key:
            # Use explicit voice ID if provided (e.g. pNInz6obpgDQGcFmaJgB for Adam), otherwise lookup table
            if self.voice and not ("-" in self.voice and "Neural" in self.voice):
                voice_id = self.voice
            else:
                voice_id = ELEVENLABS_DEFAULT_VOICES.get((gender, age_group), "21m00Tcm4TlvDq8ikWAM")
            if self._call_elevenlabs(text, voice_id, output_audio_path, genre=genre):
                return self._estimate_word_timestamps(text, output_audio_path)

        # TẦNG 2: Local valtec-tts
        if self.valtec_url and not (self.voice and "pNInz" in self.voice):
            if self._call_valtec(text, output_audio_path):
                return self._estimate_word_timestamps(text, output_audio_path)

        # TẦNG 3: TikTok TTS (skip if explicit English/ElevenLabs voice requested)
        if not (self.voice and ("pNInz" in self.voice or "en-" in self.voice.lower())):
            tiktok_speaker = TIKTOK_DEFAULT_VOICES.get(gender, "vi_vn_female")
            if self._call_tiktok(text, tiktok_speaker, output_audio_path):
                return self._estimate_word_timestamps(text, output_audio_path)

        # TẦNG 4: Edge-TTS
        if self.voice and "-" in self.voice and "Neural" in self.voice:
            edge_voice = self.voice
        elif self.voice and ("pNInz" in self.voice or "adam" in self.voice.lower()):
            edge_voice = "en-US-ChristopherNeural"
        else:
            edge_voice = self.voice or DEFAULT_TTS_VOICE
            if gender == "male" and not self.voice:
                from worker.config import BACKUP_TTS_VOICE
                edge_voice = BACKUP_TTS_VOICE
        
        max_edge_retries = 3
        for attempt in range(1, max_edge_retries + 1):
            try:
                print(f"[TTSService] Attempting Edge-TTS with voice: {edge_voice}, rate={rate_str} (Attempt {attempt}/{max_edge_retries})")
                word_timestamps = []
                sentence_timestamps = []
                audio_data = bytearray()
                
                communicate = edge_tts.Communicate(text, edge_voice, rate=rate_str)
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        audio_data.extend(chunk["data"])
                    elif chunk["type"] == "WordBoundary":
                        offset_ticks = chunk["offset"]
                        duration_ticks = chunk["duration"]
                        word = chunk["text"]
                        start_ms = offset_ticks // 10000
                        duration_ms = duration_ticks // 10000
                        end_ms = start_ms + duration_ms
                        cleaned_word = word.strip(".,!?;:\"'()[]{}“”")
                        if cleaned_word:
                            word_timestamps.append({
                                "word": cleaned_word,
                                "start_ms": start_ms,
                                "end_ms": end_ms
                            })
                    elif chunk["type"] == "SentenceBoundary":
                        offset_ticks = chunk["offset"]
                        duration_ticks = chunk["duration"]
                        sentence = chunk["text"]
                        start_ms = offset_ticks // 10000
                        duration_ms = duration_ticks // 10000
                        end_ms = start_ms + duration_ms
                        if sentence:
                            sentence_timestamps.append({
                                "word": sentence,
                                "start_ms": start_ms,
                                "end_ms": end_ms
                            })
                            
                if audio_data and len(audio_data) > 1000:  # Đảm bảo dữ liệu âm thanh hợp lệ
                    with open(output_audio_path, "wb") as f:
                        f.write(audio_data)
                    print(f"[TTSService] Edge-TTS synthesis success. Saved to: {output_audio_path}")
                    if not word_timestamps and sentence_timestamps:
                        word_timestamps = sentence_timestamps
                    return word_timestamps
                else:
                    raise RuntimeError("No audio was received or audio is too short.")
            except Exception as edge_err:
                print(f"[TTSService Warning] Edge-TTS attempt {attempt} failed: {edge_err}")
                if attempt < max_edge_retries:
                    sleep_time = attempt * 1.5
                    print(f"[TTSService] Waiting {sleep_time} seconds before retrying Edge-TTS...")
                    await asyncio.sleep(sleep_time)

        # TẦNG 5: gTTS (Google Translate)
        if self._call_gtts(text, output_audio_path):
            return self._estimate_word_timestamps(text, output_audio_path)

        # FALLBACK CỐI THƯỢNG: Tạo tệp im lặng
        print(f"[TTSService Fatal] All TTS providers failed. Creating silent fallback...")
        import subprocess
        est_duration = max(0.5, min(6.0, len(text.split()) * 0.35))
        cmd_silence = [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-t", f"{est_duration:.2f}", "-acodec", "libmp3lame", output_audio_path
        ]
        try:
            subprocess.run(cmd_silence, capture_output=True, check=True)
        except Exception as fallback_err:
            print(f"[TTSService Error] Fallback silence generation failed: {fallback_err}")
            with open(output_audio_path, "wb") as f:
                f.write(b"")
                
        return [{
            "word": text,
            "start_ms": 0,
            "end_ms": int(est_duration * 1000)
        }]

# Chạy thử kiểm nghiệm độc lập nếu chạy trực tiếp file
if __name__ == "__main__":
    async def main():
        service = TTSService()
        test_text = "Chào bạn! Đây là hệ thống tự động hóa video Tik Tok chuyên nghiệp."
        output_file = str(ASSETS_DIR / "test_voice.mp3")
        timestamps = await service.generate_speech_with_timestamps(test_text, output_file)
        print("Mẫu Timestamp 3 từ đầu tiên:", timestamps[:3])

    asyncio.run(main())
