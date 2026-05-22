import asyncio
import json
import edge_tts
from worker.config import DEFAULT_TTS_VOICE, ASSETS_DIR

class TTSService:
    def __init__(self, voice: str = DEFAULT_TTS_VOICE):
        self.voice = voice

    async def generate_speech_with_timestamps(self, text: str, output_audio_path: str) -> list:
        """
        Chuyển đổi Text sang Speech dùng Edge-TTS, ghi file .mp3 và trả về mảng các từ đơn kèm mốc thời gian (ms).
        """
        print(f"[TTSService] Synthesizing speech using voice: {self.voice}")
        print(f"[TTSService] Text length: {len(text)} characters.")
        print(f"[TTSService] Text content: '{text}'")
        
        # Khởi tạo đối tượng truyền thông Edge-TTS
        communicate = edge_tts.Communicate(text, self.voice)
        
        word_timestamps = []
        sentence_timestamps = []
        audio_data = bytearray()

        # Stream dữ liệu âm thanh và bắt sự kiện WordBoundary / SentenceBoundary
        # Mỗi chunk chứa các khóa: "type", "data" hoặc "offset", "duration", "text"
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data.extend(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                # offset và duration tính bằng đơn vị 100-nanoseconds (1 tick = 100ns)
                # Đổi sang milliseconds: chia cho 10,000 (10^4)
                offset_ticks = chunk["offset"]
                duration_ticks = chunk["duration"]
                word = chunk["text"]

                start_ms = offset_ticks // 10000
                duration_ms = duration_ticks // 10000
                end_ms = start_ms + duration_ms

                # Loại bỏ các ký tự dấu câu thừa ở đầu/cuối từ
                cleaned_word = word.strip(".,!?;:\"'()[]{}“”")
                if cleaned_word:
                    word_timestamps.append({
                        "word": cleaned_word,
                        "start_ms": start_ms,
                        "end_ms": end_ms
                    })
            elif chunk["type"] == "SentenceBoundary":
                # Thu thập SentenceBoundary để làm fallback tự phục hồi cho phụ đề
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

        # Ghi âm thanh ra file
        with open(output_audio_path, "wb") as f:
            f.write(audio_data)

        print(f"[TTSService] Speech saved to: {output_audio_path}")
        
        # Fallback tự phục hồi thông minh của Tech Lead
        if not word_timestamps and sentence_timestamps:
            print("[TTSService Warning] No WordBoundary events found. Self-healing fallback: Using SentenceBoundary events for subtitles.")
            word_timestamps = sentence_timestamps
            
        print(f"[TTSService] Extracted {len(word_timestamps)} elements with timestamps.")
        
        return word_timestamps

# Chạy thử kiểm nghiệm độc lập nếu chạy trực tiếp file
if __name__ == "__main__":
    async def main():
        service = TTSService()
        test_text = "Chào bạn! Đây là hệ thống tự động hóa video Tik Tok chuyên nghiệp."
        output_file = str(ASSETS_DIR / "test_voice.mp3")
        timestamps = await service.generate_speech_with_timestamps(test_text, output_file)
        print("Mẫu Timestamp 3 từ đầu tiên:", timestamps[:3])

    asyncio.run(main())
