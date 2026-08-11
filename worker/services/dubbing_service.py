import os
import json
import re
import subprocess
import asyncio
from pathlib import Path
from worker.services.llm_service import LLMService
from worker.services.tts_service import TTSService
from worker.services.lyric_transcription_service import LyricTranscriptionService
from worker.config import DEFAULT_TTS_VOICE, BACKUP_TTS_VOICE

def _get_ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"

class DubbingService:
    _supports_force_style_cache = None

    def __init__(self):
        self.llm = LLMService()
        self.transcription_service = LyricTranscriptionService()

    def check_subtitles_supports_force_style(self) -> bool:
        """Kiểm tra động xem FFmpeg hiện tại có hỗ trợ tham số force_style trong filter subtitles hay không"""
        if DubbingService._supports_force_style_cache is not None:
            return DubbingService._supports_force_style_cache

        try:
            cmd = [_get_ffmpeg_exe(), "-h", "filter=subtitles"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if res.returncode != 0:
                DubbingService._supports_force_style_cache = False
            else:
                DubbingService._supports_force_style_cache = "force_style" in res.stdout
        except Exception as e:
            print(f"[DubbingService Warning] Failed to check FFmpeg subtitles help: {e}")
            DubbingService._supports_force_style_cache = False

        return DubbingService._supports_force_style_cache

    def get_media_duration(self, file_path: str) -> float:
        """Sử dụng ffprobe để lấy độ dài file media (video/audio) tính bằng giây"""
        try:
            cmd = [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_format", "-show_streams", file_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            data = json.loads(result.stdout)
            return float(data.get("format", {}).get("duration", 0.0))
        except Exception as e:
            print(f"[DubbingService Warning] Failed to get duration for {file_path}: {e}")
            return 0.0

    async def transcribe_audio(self, audio_path: str, source_language: str = "auto", progress_callback=None) -> list:
        """Sử dụng LyricTranscriptionService để chép thoại kèm timestamp"""
        if progress_callback:
            progress_callback("Đang phân tích và chép thoại bằng mô hình Whisper...")

        # Nhờ lyric transcription service chạy Faster-Whisper hoặc OpenAI Whisper
        timeline = self.transcription_service.transcribe_lyrics(audio_path, language=source_language)
        return timeline

    async def translate_timeline(self, timeline: list, progress_callback=None, target_language: str = "vi") -> list:
        """Sử dụng Gemini AI để dịch câu thoại sát nghĩa chuẩn hoạt hình/phim ảnh theo ngôn ngữ đích chỉ định."""
        target_lang_clean = (target_language or "vi").strip().lower()
        is_english = target_lang_clean in ["en", "english"]
        lang_name = "tiếng Anh (English)" if is_english else "tiếng Việt"

        if progress_callback:
            progress_callback(f"Đang tiến hành dịch thuật thông minh sang {lang_name} bằng Gemini AI...")

        if not timeline:
            return []

        # Chia nhỏ timeline thành từng lô (batch) để xử lý tuần tự gối đầu bối cảnh
        batch_size = 40
        batches = [timeline[i:i + batch_size] for i in range(0, len(timeline), batch_size)]

        translated_results = {}
        identified_characters = set()  # Lưu giữ tên các nhân vật đã được nhận diện

        for batch_idx, batch in enumerate(batches):
            batch_start_idx = batch_idx * batch_size
            if progress_callback:
                progress_callback(f"Đang tiến hành dịch thuật & phân vai nhóm thoại {batch_idx + 1}/{len(batches)} (sang {lang_name})...")

            # Tạo ngữ cảnh gối đầu (Context Overlap) kèm thông tin định danh nhân vật đã biết
            context_data = []
            if batch_idx > 0:
                prev_batch = batches[batch_idx - 1]
                # Lấy 3 câu thoại cuối cùng đã dịch của nhóm trước
                for prev_item in prev_batch[-3:]:
                    prev_idx = timeline.index(prev_item)
                    context_data.append({
                        "original_text": prev_item["text"],
                        "translated_text": translated_results.get(prev_idx, {}).get("translated_text", prev_item["text"]),
                        "speaker_id": translated_results.get(prev_idx, {}).get("speaker_id", "SPEAKER_00"),
                        "gender": translated_results.get(prev_idx, {}).get("gender", "female"),
                        "age_group": translated_results.get(prev_idx, {}).get("age_group", "adult")
                    })

            # Chuẩn bị dữ liệu thoại cần dịch cho lô hiện tại
            prompt_data = []
            for item in batch:
                idx = timeline.index(item)
                duration = item["end"] - item["start"]
                prompt_data.append({
                    "id": idx,
                    "text": item["text"],
                    "duration_seconds": round(duration, 2)
                })

            # Xây dựng danh sách các nhân vật đã định danh để yêu cầu AI sử dụng nhất quán
            known_chars_str = ", ".join(identified_characters) if identified_characters else "Chưa có (Hãy tự định danh)"

            if is_english:
                lang_rule_details = (
                    "Bản dịch phải là 100% tiếng Anh tự nhiên, mượt mà chuẩn văn phong điện ảnh Hollywood/TikTok Shorts phương Tây. "
                    "Tuyệt đối KHÔNG được để sót bất kỳ chữ Hán (chữ Trung Quốc), ký tự phiên âm, hoặc ký tự ngoại lai nào."
                )
                context_rule_details = "Chọn từ vựng và văn phong tiếng Anh chuẩn điện ảnh, tự nhiên phù hợp với bối cảnh đối thoại."
            else:
                lang_rule_details = (
                    "Bản dịch phải là 100% tiếng Việt thuần túy, tuyệt đối KHÔNG được để sót bất kỳ chữ Hán (chữ Trung Quốc), "
                    "ký tự phiên âm, hoặc ký tự ngoại lai nào trong kết quả dịch. Tất cả các từ tiếng Trung (như \"胆小\", \"欺负\", \"娇气\", \"台面\") "
                    "phải được chuyển ngữ hoàn toàn sang từ ngữ tiếng Việt điện ảnh tương đương tự nhiên nhất (ví dụ: \"nhút nhát\", \"bắt nạt\", \"yểu điệu\", \"sân khấu/thể diện\")."
                )
                context_rule_details = (
                    "Phân tích kỹ quan hệ giữa các nhân vật dựa trên bối cảnh để chọn đại từ xưng hô tiếng Việt phù hợp, nhất quán và đậm chất điện ảnh:\n"
                    "     * Người lớn đối với trẻ em: Cô/Chú/Ta - Cháu/Con/Ngươi.\n"
                    "     * Cảnh sát/Đội trưởng/Đồng đội: Đội trưởng/Tôi - Cậu/Mọi người/Đồng chí.\n"
                    "     * Kẻ xấu và nạn nhân: Ta - Ngươi, Tao - Mày.\n"
                    "     * Xưng hô thông thường lịch sự: Tôi - Bạn, Anh - Em."
                )

            # Xây dựng prompt kèm cơ chế bối cảnh xưng hô và diarization
            prompt = f"""
Bạn là chuyên gia biên dịch kịch bản lồng tiếng hoạt hình và phim ảnh kỳ cựu.
Nhiệm vụ của bạn là dịch các phân đoạn thoại sau sang {lang_name}, đồng thời phân tích ngữ cảnh để chia vai (Speaker Diarization) cho từng câu nói.

"""
            if context_data:
                prompt += f"""
BỐI CẢNH HỘI THOẠI TRƯỚC ĐÓ (Chỉ dùng để tham khảo văn phong, KHÔNG dịch lại):
{json.dumps(context_data, ensure_ascii=False, indent=2)}

"""
            prompt += f"""
DANH SÁCH THOẠI CẦN DỊCH HÔM NAY (JSON):
{json.dumps(prompt_data, ensure_ascii=False, indent=2)}

DANH SÁCH NHÂN VẬT ĐÃ ĐƯỢC ĐỊNH DANH TRƯỚC ĐÓ (Hãy ưu tiên sử dụng nhất quán các tên này nếu là cùng một nhân vật):
[{known_chars_str}]

QUY TẮC DỊCH THUẬT & PHÂN VAI CHUYÊN NGHIỆP:
1. DỊCH VĂN CẢNH & KHỚP THỜI LƯỢNG SÚC TÍCH (LIP-SYNC, RHYTHM & COMPACT WORD LIMIT):
   - Bản dịch sang {lang_name} phải giữ trọn vẹn ý nghĩa, kịch tính, văn phong và cảm xúc của câu thoại gốc. KHÔNG được rút gọn thô bạo hoặc cắt xén câu thoại xuống còn 1-2 từ cộc lốc trừ khi bản gốc thực sự ngắn như thế.
   - {lang_rule_details}
   - RÀNG BUỘC ĐỘ DÀI TỪ VỰNG SÚC TÍCH: Bản dịch dịch ra phải cực kỳ súc tích, cô đọng, bỏ hết các từ đệm thừa thãi để đảm bảo tốc độ đọc tự nhiên khớp với thời lượng gốc (khoảng 2.0 đến 3.0 từ cho mỗi 1 giây thời lượng). Điều này giúp giảm thiểu tối đa tải trọng co dãn Tempo của FFmpeg.
   - KIẾN TRÚC HOOK NGƯỢC DÒNG (Contrarian Hook - 3 Giây Đầu): Nếu câu thoại đầu tiên là câu hook (0s - 3s), hãy dịch hoặc điều chỉnh câu nói này thành một lời khẳng định triệt lý mạnh mẽ, đi ngược lại suy nghĩ thông thường của đám đông hoặc đánh thẳng nỗi đau nhức nhối để kích thích tương tác bình luận.
   - CẤU TRÚC VÒNG LẶP VÔ TẬN (Seamless Loop): Tinh chỉnh câu thoại cuối cùng của video kết thúc lửng lơ bằng một vế câu mở sao cho khi nối liền mạch với câu Hook đầu tiên khi video lặp lại tạo thành một câu hoàn chỉnh, logic.
2. PHONG CÁCH VĂN PHONG VÀ XƯNG HÔ (DRAMATIC CONTEXT):
   - {context_rule_details}
3. PHÂN VAI NHÂN VẬT (SPEAKER DIARIZATION):
   - Phân tích ngữ cảnh câu thoại để gán thuộc tính nhân vật một cách nhất quán cho toàn bộ video:
     * "speaker_id": Đặt tên viết hoa ngắn gọn định danh nhân vật nói câu này (ví dụ: MOTHER, DAUGHTER, CAPTAIN, BOY_A, BOY_B). Hãy giữ nguyên tên nhân vật đã có nếu trùng khớp đối thoại.
     * "gender": Giới tính nhân vật, chỉ được chọn một trong hai nhãn: "male" hoặc "female".
     * "age_group": Nhóm tuổi nhân vật, chỉ được chọn một trong hai nhãn: "child" (trẻ em/thiếu niên) hoặc "adult" (người lớn).
4. Trả về ĐÚNG cấu trúc JSON array gồm các đối tượng có đầy đủ các trường: "id", "translated_text", "speaker_id", "gender", "age_group".
5. Chỉ trả về chuỗi JSON hợp lệ, không viết thêm bất cứ văn bản giải thích hay ký tự markdown nào ngoài JSON.
"""

            # Cơ chế tự động thử lại (Retry Loop) lên tới 3 lần nếu xảy ra lỗi JSON hoặc sai số lượng phân đoạn
            success_batch = False
            last_error = ""
            for attempt in range(3):
                try:
                    raw_response = self.llm.call_gemini_direct(prompt)
                    cleaned = self.llm._clean_json_string(raw_response)
                    parsed_list = json.loads(cleaned)

                    # Xác thực cấu trúc đầu ra: Phải là list và có số lượng khớp với lô đầu vào
                    if isinstance(parsed_list, list) and len(parsed_list) == len(batch):
                        # Ghi nhận kết quả dịch và vai nhân vật
                        for item in parsed_list:
                            if "id" in item:
                                s_id = item.get("speaker_id", "SPEAKER_00").strip().upper()
                                # Thêm vào danh sách nhân vật đã biết
                                identified_characters.add(s_id)
                                translated_results[int(item["id"])] = {
                                    "translated_text": item.get("translated_text", ""),
                                    "speaker_id": s_id,
                                    "gender": item.get("gender", "female").strip().lower(),
                                    "age_group": item.get("age_group", "adult").strip().lower()
                                }
                        success_batch = True
                        break
                    else:
                        last_error = f"Lô dịch {batch_idx + 1} có độ dài không khớp ({len(parsed_list) if isinstance(parsed_list, list) else 'not a list'} vs {len(batch)})."
                        print(f"[DubbingService Warning] {last_error} Đang thử lại lần {attempt + 1}...")
                except Exception as ex:
                    last_error = str(ex)
                    print(f"[DubbingService Warning] Lỗi dịch lô {batch_idx + 1} lần {attempt + 1}: {ex}. Tự động tạm dừng 8s để chờ reset hạn mức Rate-Limit...")
                    await asyncio.sleep(8.0)

            # Nếu thử lại cả 3 lần vẫn thất bại, ném lỗi rõ ràng thay vì dịch thô
            if not success_batch:
                raise RuntimeError(
                    f"Không thể dịch phân đoạn thoại nhóm {batch_idx + 1}/{len(batches)} sang tiếng Việt.\n"
                    f"Lý do lỗi: {last_error}\n"
                    f"Vui lòng kiểm tra lại trạng thái hạn mức hạn mức API Key Gemini của bạn."
                )

        # Khớp lại tất cả các bản dịch và thông tin phân vai vào timeline gốc
        for idx, item in enumerate(timeline):
            res = translated_results.get(idx, {})
            if isinstance(res, dict) and "translated_text" in res:
                item["translated_text"] = res.get("translated_text", item["text"])
                item["speaker_id"] = res.get("speaker_id", "SPEAKER_00")
                item["gender"] = res.get("gender", "female")
                item["age_group"] = res.get("age_group", "adult")
            else:
                item["translated_text"] = item["text"]
                item["speaker_id"] = "SPEAKER_00"
                item["gender"] = "female"
                item["age_group"] = "adult"

        return timeline

    def merge_adjacent_segments(self, timeline: list, max_gap: float = 1.2, max_duration: float = 6.0) -> list:
        """
        Gộp các phân đoạn thoại gần nhau để:
        1. Giảm số lượng gọi API Edge-TTS (tránh bị khóa IP/rate limit 429).
        2. Tạo giọng đọc lồng tiếng liền mạch, tự nhiên và lưu loát hơn.
        """
        if not timeline:
            return []

        merged = []
        current = dict(timeline[0]) # Sao chép để tránh sửa đổi bản gốc

        for next_seg in timeline[1:]:
            gap = next_seg["start"] - current["end"]
            combined_duration = next_seg["end"] - current["start"]

            # Gộp nếu khoảng nghỉ nhỏ hơn max_gap và tổng độ dài không vượt quá max_duration
            if gap < max_gap and combined_duration <= max_duration:
                current["text"] = f"{current['text'].strip()} {next_seg['text'].strip()}"
                current["end"] = next_seg["end"]
            else:
                merged.append(current)
                current = dict(next_seg)

        merged.append(current)
        print(f"[DubbingService] Merged timeline from {len(timeline)} segments down to {len(merged)} segments!")
        return merged

    def mix_wav_files_pure_python(self, dub_clips: list, output_path: str):
        """
        Hợp nhất các file WAV stereo 44100Hz 16-bit PCM bằng Python thuần
        để không bị phụ thuộc vào bộ lọc 'adelay' của các phiên bản FFmpeg cũ.
        """
        import wave
        import array

        if not dub_clips:
            # Nếu không có clip nào, tạo file wav im lặng ngắn 1s
            with wave.open(output_path, 'wb') as wav_out:
                wav_out.setnchannels(2)
                wav_out.setsampwidth(2)
                wav_out.setframerate(44100)
                wav_out.writeframes(b'\x00' * 44100 * 4)
            return

        # 1. Tìm tổng thời lượng lớn nhất (tính bằng số mẫu/samples)
        max_samples = 0
        clips_data = []

        for clip in dub_clips:
            path = clip["path"]
            start_ms = clip["start_ms"]

            with wave.open(path, 'rb') as wav_in:
                n_channels = wav_in.getnchannels()
                sampwidth = wav_in.getsampwidth()
                framerate = wav_in.getframerate()
                n_frames = wav_in.getnframes()

                # Đọc toàn bộ dữ liệu mẫu âm thanh
                raw_frames = wav_in.readframes(n_frames)
                # Chuyển thành mảng 16-bit signed short ('h')
                samples = array.array('h', raw_frames)

                # Quy đổi thời gian bắt đầu sang vị trí sample trong kênh stereo
                start_frame = int(start_ms * framerate / 1000)
                end_frame = start_frame + n_frames

                if end_frame > max_samples:
                    max_samples = end_frame

                clips_data.append({
                    "samples": samples,
                    "start_frame": start_frame,
                    "n_channels": n_channels
                })

        # 2. Khởi tạo mảng đích chứa toàn bộ mẫu âm thanh im lặng (zeros)
        # Vì là stereo 16-bit, số lượng phần tử của array 'h' là max_samples * 2 (trái + phải)
        target_samples = array.array('h', [0] * (max_samples * 2))

        # 3. Phối trộn (Mix) từng clip vào mảng đích kèm cơ chế chống méo tiếng (clipping guard)
        for clip in clips_data:
            samples = clip["samples"]
            start_frame = clip["start_frame"]
            n_channels = clip["n_channels"]

            # Nếu clip gốc là mono (1 kênh), cần nhân đôi thành stereo khi trộn
            if n_channels == 1:
                for i in range(len(samples)):
                    frame_idx = start_frame + i
                    target_left_idx = frame_idx * 2
                    target_right_idx = frame_idx * 2 + 1

                    if target_right_idx < len(target_samples):
                        # Trộn kênh trái
                        val_l = target_samples[target_left_idx] + samples[i]
                        target_samples[target_left_idx] = max(-32768, min(32767, val_l))
                        # Trộn kênh phải
                        val_r = target_samples[target_right_idx] + samples[i]
                        target_samples[target_right_idx] = max(-32768, min(32767, val_r))
            else:
                # Clip là stereo (2 kênh)
                for i in range(len(samples)):
                    target_idx = start_frame * 2 + i
                    if target_idx < len(target_samples):
                        val = target_samples[target_idx] + samples[i]
                        target_samples[target_idx] = max(-32768, min(32767, val))

        # 4. Ghi mảng phối trộn ra tệp tin WAV stereo 44100Hz 16-bit PCM mới
        with wave.open(output_path, 'wb') as wav_out:
            wav_out.setnchannels(2)
            wav_out.setsampwidth(2)
            wav_out.setframerate(44100)
            wav_out.writeframes(target_samples.tobytes())

        print(f"[DubbingService] Pure Python WAV Mixer: Successfully merged {len(dub_clips)} clips into '{output_path}'")

    def apply_audio_ducking_pure_python(self, input_wav_path: str, output_wav_path: str, timeline: list):
        """
        Thực hiện Audio Ducking (dìm âm lượng nhạc nền gốc khi có tiếng thuyết minh) bằng Python thuần
        để không bị phụ thuộc vào các tùy chọn và hàm toán học của bộ lọc 'volume' trong FFmpeg cũ.
        Tích hợp thêm hiệu ứng Fade-in/Fade-out mượt mà dài 200ms để âm thanh nghe vô cùng tự nhiên.
        """
        import wave
        import array

        with wave.open(input_wav_path, 'rb') as wav_in:
            n_channels = wav_in.getnchannels()
            sampwidth = wav_in.getsampwidth()
            framerate = wav_in.getframerate()
            n_frames = wav_in.getnframes()

            raw_frames = wav_in.readframes(n_frames)
            samples = array.array('h', raw_frames)

        total_frames = n_frames

        # Khởi tạo mảng hệ số âm lượng cho từng khung hình (frame), mặc định là 1.0 (100% âm lượng)
        volume_factors = [1.0] * total_frames

        fade_duration_frames = int(0.32 * framerate) # Fade transition 320ms mượt mà chuẩn studio

        for segment in timeline:
            start_sec = max(0.0, segment["start"] - 0.20)
            end_sec = segment["end"] + 0.20

            start_frame = int(start_sec * framerate)
            end_frame = int(end_sec * framerate)

            # Giới hạn vị trí trong khung hình thực tế
            start_frame = max(0, min(total_frames - 1, start_frame))
            end_frame = max(0, min(total_frames - 1, end_frame))

            # 1. Đoạn nói chính (Dìm nhẹ xuống 58% âm lượng - chuẩn studio lồng tiếng để giữ nguyên độ ấm/tiếng môi trường tự nhiên)
            duck_vol = 0.58
            duck_start = min(total_frames - 1, start_frame + fade_duration_frames)
            duck_end = max(0, end_frame - fade_duration_frames)

            if duck_start < duck_end:
                for f in range(duck_start, duck_end):
                    volume_factors[f] = duck_vol

                # 2. Hiệu ứng Fade-out (Giảm dần từ 1.0 xuống 0.58) trước khi nói
                for f in range(start_frame, duck_start):
                    progress = (f - start_frame) / fade_duration_frames
                    volume_factors[f] = min(volume_factors[f], 1.0 - (1.0 - duck_vol) * progress)

                # 3. Hiệu ứng Fade-in (Tăng dần từ 0.58 lên 1.0) sau khi nói xong
                for f in range(duck_end, end_frame):
                    progress = (f - duck_end) / fade_duration_frames
                    volume_factors[f] = min(volume_factors[f], duck_vol + (1.0 - duck_vol) * progress)
            else:
                # Nếu câu thoại quá ngắn, dìm nhẹ xuống 58%
                for f in range(start_frame, end_frame):
                    volume_factors[f] = duck_vol

        # 4. Áp dụng các hệ số âm lượng vào các mẫu âm thanh thực tế
        for f in range(total_frames):
            factor = volume_factors[f]
            if factor < 1.0:
                for c in range(n_channels):
                    sample_idx = f * n_channels + c
                    if sample_idx < len(samples):
                        val = int(samples[sample_idx] * factor)
                        samples[sample_idx] = max(-32768, min(32767, val))

        # 5. Ghi tệp WAV đã được dìm âm lượng
        with wave.open(output_wav_path, 'wb') as wav_out:
            wav_out.setnchannels(n_channels)
            wav_out.setsampwidth(sampwidth)
            wav_out.setframerate(framerate)
            wav_out.writeframes(samples.tobytes())

        print(f"[DubbingService] Pure Python Audio Ducking: Applied smooth ducking (15% vol) for {len(timeline)} segments on '{output_wav_path}'")

    def format_srt_time(self, seconds: float) -> str:
        """Quy đổi giây (float) sang định dạng thời gian của SRT (HH:MM:SS,mmm)"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int(round((seconds - int(seconds)) * 1000))
        if millis >= 1000:
            millis -= 1000
            secs += 1
            if secs >= 60:
                secs -= 60
                minutes += 1
                if minutes >= 60:
                    minutes -= 60
                    hours += 1
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    def split_segment_text(self, text: str, start: float, end: float, max_words: int = 4, max_chars_per_line: int = 10) -> list:
        """
        Chia nhỏ một đoạn văn bản dài thành các phân cảnh phụ đề động (Kinetic Subtitles) ngắn gọn.
        Mỗi frame hiển thị tối đa từ 3 đến 4 từ và không quá 2 dòng (tổng 20 ký tự), tự động phân bổ thời gian đều đặn.
        """
        try:
            words = text.split()
            if not words:
                return []

            duration = end - start
            total_chars = len(text)
            if total_chars == 0:
                return []

            chunks = []
            current_chunk = []
            current_len = 0

            for word in words:
                # Nếu thêm từ này vào mà vượt quá max_words hoặc quá dài, đóng chunk cũ lại
                if len(current_chunk) >= max_words or current_len + len(word) + 1 > max_chars_per_line * 2:
                    chunks.append(current_chunk)
                    current_chunk = [word]
                    current_len = len(word)
                else:
                    current_chunk.append(word)
                    current_len += len(word) + 1
            if current_chunk:
                chunks.append(current_chunk)

            # Phân bổ thời gian tỉ lệ thuận theo số lượng ký tự của mỗi chunk
            sub_segments = []
            current_start = start

            for chunk in chunks:
                chunk_text = " ".join(chunk)
                chunk_chars = len(chunk_text)

                # Tính thời lượng tương đối cho chunk này
                chunk_dur = duration * (chunk_chars / total_chars)
                chunk_dur = max(0.4, min(duration, chunk_dur))

                chunk_end = current_start + chunk_dur
                if chunk_end > end:
                    chunk_end = end

                # Định dạng ngắt dòng tự động nếu chunk có nhiều từ và dài hơn max_chars_per_line
                formatted_text = chunk_text
                if len(chunk_text) > max_chars_per_line:
                    mid_index = len(chunk_text) // 2
                    spaces = [i for i, c in enumerate(chunk_text) if c == ' ']
                    if spaces:
                        best_space = min(spaces, key=lambda x: abs(x - mid_index))
                        formatted_text = chunk_text[:best_space] + "\n" + chunk_text[best_space+1:]

                sub_segments.append({
                    "start": current_start,
                    "end": chunk_end,
                    "text": formatted_text
                })
                current_start = chunk_end

            if sub_segments:
                sub_segments[-1]["end"] = end

            return sub_segments
        except Exception as e:
            print(f"[DubbingService Warning] split_segment_text failed: {e}. Falling back to entire text.")
            return [{"start": start, "end": end, "text": text}]

    def format_ass_time(self, seconds: float) -> str:
        total_cs = max(0, int(round(seconds * 100)))
        h = total_cs // 360000
        total_cs %= 360000
        m = total_cs // 6000
        total_cs %= 6000
        s = total_cs // 100
        cs = total_cs % 100
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

    def detect_gpu_encoder(self) -> tuple[str, list[str]]:
        """Kiểm tra xem hệ thống có GPU Nvidia HOẠT ĐỘNG THỰC TẾ (Driver CUDA khả dụng) hay không."""
        try:
            # Chạy thử nghiệm 1 frame encoding thực tế với h264_nvenc để xác minh Driver CUDA khả dụng
            test_cmd = [
                _get_ffmpeg_exe(), "-y", "-hide_banner",
                "-f", "lavfi", "-i", "color=c=black:s=64x64:d=0.1",
                "-c:v", "h264_nvenc",
                "-f", "null", "-"
            ]
            res = subprocess.run(test_cmd, capture_output=True, text=True, timeout=5)
            if res.returncode == 0:
                print("[GPU Acceleration] Nvidia GPU Hardware (h264_nvenc) verified & active!")
                return "h264_nvenc", ["-preset", "p4", "-cq", "23"]
        except Exception as e:
            print(f"[GPU Acceleration Warning] NVENC hardware test failed: {e}")

        print("[GPU Acceleration] GPU hardware unavailable (no CUDA driver). Falling back to CPU H.264 encoder (libx264 superfast mode).")
        return "libx264", ["-profile:v", "high", "-level:v", "4.2", "-pix_fmt", "yuv420p", "-preset", "superfast", "-crf", "23", "-threads", "0"]

    def generate_ass_file(
        self,
        timeline: list,
        ass_path: str,
        caption_preset: str = "hormozi",
        aspect_ratio: str = "short_vertical",
        enable_karaoke: bool = True,
        font_family: str = "Montserrat",
        custom_font_size: int = 72,
        custom_y_percent: float = 80.0,
        custom_color: str = "#FFFF00",
    ):
        """Tạo file phụ đề ASS (Advanced SubStation Alpha) sắc nét, hỗ trợ Karaoke đổi màu từng từ và tọa độ Y-offset linh hoạt từ Canvas."""
        try:
            # Map Font Family
            clean_font = str(font_family or "Montserrat").lower()
            if "bebas" in clean_font:
                font_name = "Bebas Neue"
            elif "roboto" in clean_font:
                font_name = "Roboto Condensed"
            elif "outfit" in clean_font:
                font_name = "Outfit"
            elif "impact" in clean_font:
                font_name = "Impact"
            elif "playfair" in clean_font:
                font_name = "Playfair Display"
            else:
                font_name = "Montserrat"

            font_size = max(36, min(96, int(custom_font_size or 72)))

            # Quy đổi Y-percent (10-90%) sang MarginV pixel trên khung 1080x1920 (PlayResY=1920)
            y_pct = max(10.0, min(90.0, float(custom_y_percent or 80.0)))
            margin_v = int(round((100.0 - y_pct) * 1920.0 / 100.0))

            # Helper quy đổi Hex color sang ASS BGR format (&H00BBGGRR)
            def hex_to_ass_bgr(hex_str: str) -> str:
                clean_hex = str(hex_str or "").strip().lstrip("#")
                if len(clean_hex) == 6:
                    r, g, b = clean_hex[0:2], clean_hex[2:4], clean_hex[4:6]
                    return f"&H00{b}{g}{r}".upper()
                return "&H0000FFFF"

            primary_color = hex_to_ass_bgr(custom_color)
            secondary_color = "&H00FFFFFF"
            outline_color = "&H00000000"
            outline = 4
            shadow = 3

            header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},{primary_color},{secondary_color},{outline_color},&H80000000,1,0,0,0,100,100,0,0,1,{outline},{shadow},2,30,30,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
            events = []
            for segment in timeline:
                start = segment["start"]
                end = segment["end"]
                text = segment.get("translated_text", segment.get("text", "")).strip()

                sub_segments = self.split_segment_text(text, start, end, max_words=6, max_chars_per_line=22)
                for sub in sub_segments:
                    s_str = self.format_ass_time(sub["start"])
                    e_str = self.format_ass_time(sub["end"])
                    sub_text = sub["text"].strip()
                    sub_duration = sub["end"] - sub["start"]

                    if enable_karaoke and sub_duration > 0 and len(sub_text.split()) > 1:
                        # Phân bổ thời gian theo tỷ lệ ký tự thực cho từng từ (Word-Level Karaoke Timing)
                        words = sub_text.split()
                        total_chars = max(1, sum(len(w) for w in words))
                        total_cs = int(round(sub_duration * 100)) # centiseconds
                        karaoke_parts = []
                        remaining_cs = total_cs

                        for i, w in enumerate(words):
                            if i == len(words) - 1:
                                w_cs = max(1, remaining_cs)
                            else:
                                w_cs = max(1, int(round((len(w) / total_chars) * total_cs)))
                                remaining_cs -= w_cs
                            karaoke_parts.append(f"{{\\kf{w_cs}}}{w}")

                        ass_dialogue_text = " ".join(karaoke_parts).replace("\n", "\\N")
                    else:
                        ass_dialogue_text = sub_text.replace("\n", "\\N")

                    events.append(f"Dialogue: 0,{s_str},{e_str},Default,,0,0,0,,{ass_dialogue_text}")

            with open(ass_path, "w", encoding="utf-8") as f:
                f.write(header + "\n".join(events) + "\n")

            print(f"[DubbingService] ASS Subtitle file generated successfully (Karaoke={enable_karaoke}) at: {ass_path}")
        except Exception as e:
            print(f"[DubbingService Warning] Failed to generate ASS file: {e}")

    def generate_srt_file(self, timeline: list, srt_path: str):
        """Tạo file phụ đề SRT từ danh sách timeline dịch thuật"""
        try:
            with open(srt_path, "w", encoding="utf-8") as f:
                srt_index = 1
                for segment in timeline:
                    start = segment["start"]
                    end = segment["end"]
                    text = segment.get("translated_text", segment.get("text", "")).strip()

                    sub_segments = self.split_segment_text(text, start, end, max_words=4, max_chars_per_line=10)

                    for sub in sub_segments:
                        start_str = self.format_srt_time(sub["start"])
                        end_str = self.format_srt_time(sub["end"])
                        sub_text = sub["text"].strip()

                        f.write(f"{srt_index}\n")
                        f.write(f"{start_str} --> {end_str}\n")
                        f.write(f"{sub_text}\n\n")
                        srt_index += 1

            print(f"[DubbingService] SRT Subtitle file generated successfully at: {srt_path}")
        except Exception as e:
            print(f"[DubbingService Warning] Failed to generate SRT file: {e}")

    def apply_vocal_cleaner(self, input_audio_path: str, temp_dir: Path, mode: str = "ffmpeg_phase_cancel") -> str:
        """
        Xử lý triệt giọng đọc tiếng Trung gốc bằng FFmpeg Phase-Cancellation hoặc AI Stem Separation.
        Trả về đường dẫn tệp âm thanh đã triệt thoại gốc.
        """
        if not input_audio_path or not os.path.exists(input_audio_path):
            return input_audio_path

        output_cleaned = temp_dir / "cleaned_background_audio.mp3"
        mode_str = str(mode or "").strip().lower()

        if mode_str in ["ai_demucs", "demucs"]:
            try:
                import sys
                cmd_demucs = [
                    sys.executable, "-m", "demucs.separate",
                    "--two-stems", "vocals",
                    "-n", "htdemucs",
                    "-o", str(temp_dir),
                    str(input_audio_path)
                ]
                res = subprocess.run(cmd_demucs, capture_output=True, text=True)
                no_vocals_files = list(temp_dir.glob("**/no_vocals.wav")) or list(temp_dir.glob("**/no_vocals.mp3"))
                if res.returncode == 0 and no_vocals_files:
                    print(f"[DubbingService VocalCleaner] Applied AI Demucs stem separation successfully: {no_vocals_files[0]}")
                    return str(no_vocals_files[0])
                else:
                    print(f"[DubbingService Warning] AI Demucs non-zero code or missing output: {res.stderr[:200]}")
            except Exception as de:
                print(f"[DubbingService Warning] AI Demucs separation fallback: {de}")

        # Fallback hoặc Chế độ mặc định FFmpeg Vocal Suppression: Dập tần số giọng thoại + Center Channel Suppression
        try:
            cmd = [
                _get_ffmpeg_exe(), "-y", "-i", str(input_audio_path),
                "-af", "bandreject=f=1200:w=1400:g=-24,highpass=f=70,lowpass=f=11000,volume=1.2",
                "-acodec", "libmp3lame", "-q:a", "2", str(output_cleaned)
            ]
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode == 0 and output_cleaned.exists() and output_cleaned.stat().st_size > 0:
                print(f"[DubbingService VocalCleaner] Applied speech-band notch vocal suppression successfully.")
                return str(output_cleaned)
        except Exception as pe:
            print(f"[DubbingService Warning] Speech-band notch vocal cleaner error: {pe}")

        return input_audio_path

    async def execute_dubbing_pipeline(
        self,
        video_path: str,
        output_path: str,
        voice_gender: str = "female",
        voice_code: str = "edge-nam-minh",
        target_language: str = "vi",
        source_language: str = "auto",
        progress_callback=None,
        aspect_ratio: str = "original",
        burn_subtitles: bool = True,
        mute_original_audio: bool = False,
        blur_original_subtitles: bool = True,
        blur_region_height_ratio: float = 0.20,
        logo_handle: str = "GócChiêmNghiệm||YuuuBin",
        caption_preset: str = "montserrat",
        caption_font_family: str = "Montserrat ExtraBold",
        caption_font_size: int = 72,
        caption_y_percent: float = 80.0,
        caption_color: str = "#FFFF00",
        bgm_preset: str = "relaxing_chill",
        bgm_custom_url: str = None,
        bgm_volume: float = 0.18,
        enable_bgm: bool = True,
        enable_audio_ducking: bool = True,
        enable_bgm_fade: bool = True,
        smart_dynamic_blur: bool = True,
        vocal_removal_mode: str = "ffmpeg_phase_cancel",
        blur_original_logo: bool = True,
    ) -> tuple:
        """Thực hiện toàn bộ 8 bước của pipeline lồng tiếng tự động miễn phí 100%"""
        temp_dir = Path(os.path.dirname(output_path)) / f"dub_temp_{os.path.basename(video_path).split('.')[0]}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        success = False

        try:
            # 1. Trích xuất âm thanh gốc
            orig_audio_path = str(temp_dir / "original_audio.mp3")
            if os.path.exists(orig_audio_path) and os.path.getsize(orig_audio_path) > 0:
                print(f"[DubbingService] Reusing existing original audio extraction at: {orig_audio_path}")
            else:
                if progress_callback:
                    progress_callback("Đang trích xuất âm thanh gốc từ video...")
                cmd_extract = [
                    _get_ffmpeg_exe(), "-y", "-i", video_path,
                    "-vn", "-acodec", "libmp3lame", "-q:a", "2", orig_audio_path
                ]
                subprocess.run(cmd_extract, capture_output=True, check=True)

            # 2. Nhận diện giọng nói gốc bằng Whisper
            asr_cache_path = temp_dir / "asr_timeline.json"
            if asr_cache_path.exists():
                print(f"[DubbingService] Reusing cached ASR timeline: {asr_cache_path}")
                with open(asr_cache_path, "r", encoding="utf-8") as f:
                    timeline = json.load(f)
            else:
                timeline = await self.transcribe_audio(orig_audio_path, source_language, progress_callback)
                if not timeline:
                    print("[DubbingService Warning] Whisper không phát hiện bất kỳ giọng nói nào trong video nguồn. Chuyển sang chế độ remux tự động...")
                    timeline = []
                else:
                    with open(asr_cache_path, "w", encoding="utf-8") as f:
                        json.dump(timeline, f, ensure_ascii=False, indent=2)

            # Cấu hình biến phòng vệ cho video câm (Silent Video Support)
            is_silent_video = len(timeline) == 0
            realized_timeline = timeline

            if is_silent_video:
                print("[DubbingService] Đang remux trực tiếp tệp âm thanh gốc (không lồng tiếng)...")
                final_audio_path = orig_audio_path
            else:
                # Luôn gộp các phân đoạn sát nhau để tăng độ trôi chảy và tránh rate limit!
                timeline = self.merge_adjacent_segments(timeline)

                # 3. Dịch thuật thông minh qua Gemini
                trans_cache_path = temp_dir / f"translated_timeline_{target_language}.json"
                use_cached_trans = False
                if trans_cache_path.exists():
                    print(f"[DubbingService] Reusing cached translated timeline: {trans_cache_path}")
                    with open(trans_cache_path, "r", encoding="utf-8") as f:
                        cached_trans = json.load(f)
                    # Kiểm tra khớp độ dài của danh sách đã gộp để tránh lệch cache
                    if len(cached_trans) == len(timeline):
                        timeline = cached_trans
                        use_cached_trans = True
                    else:
                        print("[DubbingService Warning] Cache length mismatch with merged timeline, re-translating...")

                if not use_cached_trans:
                    timeline = await self.translate_timeline(timeline, progress_callback=progress_callback, target_language=target_language)
                    with open(trans_cache_path, "w", encoding="utf-8") as f:
                        json.dump(timeline, f, ensure_ascii=False, indent=2)

                is_en = (target_language or "").strip().lower() in ["en", "english"]
                if is_en and (not voice_code or voice_code.lower() in ["edge-nam-minh", "edge-hoai-bao", "vi-vn-namminhneural", "vi-vn-hoaibaoneural", "auto"]):
                    voice_code = "en-US-ChristopherNeural" if voice_gender == "male" else "en-US-AnaNeural"

                # 4. Sinh tiếng lồng tiếng bằng TTS & Tự động co dãn (Time-Stretch)
                if progress_callback:
                    lang_msg = "tiếng Anh" if is_en else "tiếng Việt"
                    progress_callback(f"Đang sinh giọng lồng {lang_msg} ({voice_code}) bằng AI...")

                tts_service = TTSService(voice=voice_code)

                dub_clips = []
                realized_timeline = []
                accumulated_shift_ms = 0.0

                for idx, segment in enumerate(timeline):
                    txt = segment["translated_text"]
                    # Chuẩn hóa dấu câu để giọng đọc AI ngắt nghỉ tự nhiên, chuẩn nhịp thở con người
                    txt = re.sub(r'([,.:;!?])([^\s])', r'\1 \2', txt)
                    txt = re.sub(r'\s+', ' ', txt).strip()

                    original_start = segment["start"]
                    original_end = segment["end"]
                    original_duration = original_end - original_start

                    original_start_ms = original_start * 1000.0
                    original_duration_ms = original_duration * 1000.0

                    # 1. KHỞI TẠO BIẾN TỊNH TIẾN ĐỘNG:
                    # Thời điểm bắt đầu thực tế của câu thoại tiếp theo phải bằng:
                    real_start_ms = original_start_ms + accumulated_shift_ms
                    real_start_sec = real_start_ms / 1000.0

                    # Trích xuất các nhãn phân vai nhân vật gán từ LLM
                    speaker_id = segment.get("speaker_id", "SPEAKER_00")
                    gender = segment.get("gender", "female")
                    age_group = segment.get("age_group", "adult")

                    # Tên file clip tạm thời
                    raw_clip_path = str(temp_dir / f"clip_raw_{idx}.mp3")
                    aligned_clip_path = str(temp_dir / f"clip_aligned_{idx}.wav")

                    actual_duration = 0.0
                    tempo = 1.0

                    # Nếu file aligned đã được sinh và hợp lệ, tái sử dụng để tiết kiệm 100% tài nguyên và thời gian
                    if os.path.exists(aligned_clip_path) and os.path.getsize(aligned_clip_path) > 0:
                        print(f"[DubbingService] Reusing existing aligned audio clip {idx}: {aligned_clip_path}")
                        actual_duration = self.get_media_duration(aligned_clip_path)
                    else:
                        # Gọi sinh âm thanh thô truyền động cấu hình giới tính/độ tuổi nhân vật với tốc độ chuẩn tự nhiên +0%
                        await tts_service.generate_speech_with_timestamps(
                            text=txt,
                            output_audio_path=raw_clip_path,
                            gender=gender,
                            age_group=age_group,
                            rate_str="+0%",
                        )
                        # Giãn cách 200ms giữa các câu nói để tránh bị rate limit từ chối dịch vụ
                        await asyncio.sleep(0.2)

                        # 2. KIỂM TRA CHẤT LƯỢNG FILE ÂM THANH (Audio Zero-Byte Guard):
                        is_invalid_audio = not os.path.exists(raw_clip_path) or os.path.getsize(raw_clip_path) == 0

                        if is_invalid_audio:
                            print(f"[DubbingService Warning] TTS audio file is missing or 0-byte: {raw_clip_path}. Generating silence fallback of {original_duration:.3f}s.")
                            # Ép hệ thống tự động sinh một file WAV chứa "âm thanh im lặng" (Silence Audio)
                            cmd_silence = [
                                "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                                "-t", f"{original_duration:.3f}", "-acodec", "pcm_s16le", aligned_clip_path
                            ]
                            subprocess.run(cmd_silence, capture_output=True, check=True)
                            actual_duration = original_duration
                        else:
                            # Kiểm tra độ dài âm thanh tiếng Việt thực tế
                            actual_duration = self.get_media_duration(raw_clip_path)
                            if actual_duration <= 0:
                                actual_duration = original_duration

                            # 2. TÍNH TOÁN TEMPO VÀ OVERFLOW THÔNG MINH (Cho phép co dãn linh hoạt 0.85x - 1.45x để khớp 100% nhịp hình ảnh)
                            tempo = actual_duration / original_duration
                            tempo = max(0.85, min(1.45, tempo))

                            # Xác định tỷ lệ điều tần (pitch shift) chuẩn nhân vật
                            pitch_ratio = 1.0
                            if gender == "female" and age_group == "child":
                                pitch_ratio = 1.05
                            elif gender == "male":
                                if age_group == "child":
                                    pitch_ratio = 1.04
                                else:
                                    pitch_ratio = 1.0  # Giữ nguyên giọng nam chính nguyên bản ấm áp

                            # Chế tạo bộ lọc kép Single-Pass hợp nhất xử lý pitch và tempo
                            filters = []
                            if abs(pitch_ratio - 1.0) > 0.01:
                                filters.append(f"asetrate=44100*{pitch_ratio:.3f}")
                                filters.append(f"atempo={1.0/pitch_ratio:.3f}")
                            if abs(tempo - 1.0) > 0.03:
                                if tempo > 2.0:
                                    filters.append("atempo=2.0")
                                    filters.append(f"atempo={tempo/2.0:.3f}")
                                else:
                                    filters.append(f"atempo={tempo:.3f}")

                            # Chạy FFmpeg để sinh file aligned với âm tần chuẩn
                            filter_str = ",".join(filters)
                            cmd_tempo = [_get_ffmpeg_exe(), "-y", "-i", raw_clip_path]
                            if filter_str:
                                cmd_tempo += ["-filter_complex", f"[0:a]{filter_str}[outa]", "-map", "[outa]"]
                            cmd_tempo += ["-ac", "2", "-ar", "44100", aligned_clip_path]

                            subprocess.run(cmd_tempo, capture_output=True, check=True)

                            actual_duration = self.get_media_duration(aligned_clip_path)

                    # Độ dài sau khi co dãn bằng FFmpeg thực tế
                    compressed_duration_ms = actual_duration * 1000.0
                    real_end_ms = real_start_ms + compressed_duration_ms
                    real_end_sec = real_end_ms / 1000.0

                    # Tính toán số mili-giây dư ra (overflow) và cộng dồn vào accumulated_shift_ms
                    overflow_ms = compressed_duration_ms - original_duration_ms
                    accumulated_shift_ms += overflow_ms

                    # Trừ bớt/thu hồi accumulated_shift_ms nếu có khoảng nghỉ (gap) đến câu tiếp theo
                    if idx < len(timeline) - 1:
                        next_segment = timeline[idx + 1]
                        next_original_start_ms = next_segment["start"] * 1000.0
                        gap_ms = next_original_start_ms - (original_end * 1000.0)
                        if gap_ms > 0:
                            accumulated_shift_ms = max(0.0, accumulated_shift_ms - gap_ms)

                    # Giới hạn accumulated_shift_ms tối đa 600ms để tuyệt đối giữ chuẩn nhịp hình ảnh
                    accumulated_shift_ms = max(0.0, min(600.0, accumulated_shift_ms))

                    dub_clips.append({
                        "path": aligned_clip_path,
                        "start_ms": int(real_start_ms)
                    })

                    # 3. ĐỒNG BỘ ĐẦU RA CHO SRT VÀ AUDIO DUCKING
                    realized_segment = dict(segment)
                    realized_segment["start"] = real_start_sec
                    realized_segment["end"] = real_end_sec
                    realized_timeline.append(realized_segment)

                    # LOGGING GIÁM SÁT DÒNG THỜI GIAN (Timeline Drift Logger)
                    print(f"[DubbingService] Segment {idx} -> Original Duration: {original_duration_ms:.1f}ms | Real Duration: {compressed_duration_ms:.1f}ms | Current Accumulated Shift: {accumulated_shift_ms:.1f}ms")

                # 5. Phối trộn tất cả các câu lồng tiếng bằng Python thuần
                merged_vocal_path = str(temp_dir / "merged_vocals.wav")
                self.mix_wav_files_pure_python(dub_clips, merged_vocal_path)

                # 6. Audio Ducking nhạc nền gốc
                if progress_callback:
                    progress_callback("Đang thực hiện Audio Ducking lọc dìm nhạc nền nguyên bản...")

                # Trích xuất file WAV stereo 44100Hz từ original_audio.mp3 trước khi xử lý
                orig_audio_wav_path = str(temp_dir / "original_audio.wav")
                cmd_conv = [
                    _get_ffmpeg_exe(), "-y", "-i", orig_audio_path,
                    "-ac", "2", "-ar", "44100", orig_audio_wav_path
                ]
                subprocess.run(cmd_conv, capture_output=True, check=True)

                # 1. Triệt giọng đọc tiếng Trung gốc TRƯỚC trên file full-gain nguyên bản để giữ nguyên năng lượng âm thanh môi trường
                clean_background_audio = orig_audio_wav_path
                if not mute_original_audio and vocal_removal_mode not in ["ducking", "none", "off"]:
                    if progress_callback:
                        progress_callback(f"Đang xử lý triệt giọng đọc tiếng Trung gốc (chế độ: {vocal_removal_mode})...")
                    clean_background_audio = self.apply_vocal_cleaner(orig_audio_wav_path, temp_dir, vocal_removal_mode)

                # 2. Áp dụng Audio Ducking SAU KHI đã bóc tách giọng thoại gốc để tiếng môi trường chìm nhẹ tự nhiên chuẩn Studio
                if not mute_original_audio and enable_audio_ducking and realized_timeline:
                    ducked_audio_path = str(temp_dir / "ducked_original_audio.wav")
                    self.apply_audio_ducking_pure_python(clean_background_audio, ducked_audio_path, realized_timeline)
                    clean_background_audio = ducked_audio_path

                final_audio_path = str(temp_dir / "final_dubbed_audio.mp3")
                video_dur = self.get_media_duration(video_path)

                # --- XỬ LÝ NHẠC NỀN BGM (TỰ ĐỘNG LẶP HƠẶC CẮT THEO ĐỘ DÀI VIDEO) ---
                prepared_bgm_path = None
                raw_bgm_source = None

                # 1. Kiểm tra nếu có link / file nhạc tùy chỉnh của người dùng (Hỗ trợ cả link YouTube / TikTok / Direct URL)
                if bgm_custom_url and str(bgm_custom_url).strip():
                    url_str = str(bgm_custom_url).strip()
                    if url_str.startswith("http://") or url_str.startswith("https://"):
                        try:
                            if progress_callback:
                                progress_callback(f"Đang tải nhạc nền tùy chỉnh từ URL: {url_str[:40]}...")
                            custom_bgm_file = temp_dir / "custom_bgm_track.mp3"
                            
                            is_social_url = any(dom in url_str.lower() for dom in ["youtube.com", "youtu.be", "tiktok.com", "douyin.com", "soundcloud.com", "bilibili.com"])
                            if is_social_url:
                                if progress_callback:
                                    progress_callback("Phát hiện link YouTube/Social Media. Đang dùng yt-dlp trích xuất âm thanh MP3...")
                                from worker.infrastructure.douyin_client import _get_ytdlp_cmd
                                cmd_yt = _get_ytdlp_cmd() + [
                                    "-x", "--audio-format", "mp3", "--audio-quality", "0",
                                    "--no-playlist", "-o", str(custom_bgm_file), url_str
                                ]
                                res = subprocess.run(cmd_yt, capture_output=True, text=True)
                                if res.returncode != 0:
                                    print(f"[DubbingService Warning] yt-dlp custom BGM extraction warning: {res.stderr[:200]}")
                            else:
                                import urllib.request
                                urllib.request.urlretrieve(url_str, str(custom_bgm_file))

                            # Nếu yt-dlp lưu theo tên đuôi mở rộng tự động (vd: custom_bgm_track.mp3.mp3 hoặc .webm)
                            if not custom_bgm_file.exists():
                                candidates = list(temp_dir.glob("custom_bgm_track*"))
                                if candidates:
                                    custom_bgm_file = candidates[0]

                            if custom_bgm_file.exists() and custom_bgm_file.stat().st_size > 0:
                                raw_bgm_source = str(custom_bgm_file)
                                print(f"[DubbingService BGM] Custom BGM track downloaded successfully to: {raw_bgm_source}")
                        except Exception as dl_err:
                            print(f"[DubbingService Warning] Failed to download custom BGM from {url_str}: {dl_err}")
                    elif os.path.exists(url_str):
                        raw_bgm_source = url_str

                # 2. Nếu không có file tùy chỉnh, sử dụng nhạc nền preset
                if not raw_bgm_source and bgm_preset and str(bgm_preset).strip().lower() not in ["none", "off", "false"]:
                    preset_name = str(bgm_preset).strip().lower()
                    if not preset_name.endswith(".mp3"):
                        preset_name += ".mp3"
                    from worker.utils.asset_initializer import ASSETS_DIR, initialize_bgm_library
                    preset_file = ASSETS_DIR / "audio" / "bgm" / preset_name
                    if not preset_file.exists():
                        initialize_bgm_library()
                    if preset_file.exists():
                        raw_bgm_source = str(preset_file)

                # 3. Tiến hành tự động lặp (loop) hoặc cắt (trim) nhạc nền theo đúng độ dài video_dur
                if enable_bgm and raw_bgm_source and video_dur > 0:
                    try:
                        if progress_callback:
                            progress_callback("Đang tự động căn chỉnh & lặp nhạc nền khớp với độ dài video...")
                        target_bgm_wav = temp_dir / "prepared_bgm.wav"
                        
                        # Chuẩn hóa âm lượng BGM (nếu truyền > 1.0 nghĩa là % thì chia 100)
                        raw_vol = float(bgm_volume if bgm_volume is not None else 0.18)
                        if raw_vol > 1.0:
                            raw_vol = raw_vol / 100.0
                        vol_val = max(0.01, min(1.0, raw_vol))

                        fade_start = max(0.0, video_dur - 2.0)
                        if enable_bgm_fade:
                            af_filter = f"afade=t=in:ss=0:d=1.5,volume={vol_val:.3f},afade=t=out:st={fade_start:.3f}:d=2.0"
                        else:
                            af_filter = f"volume={vol_val:.3f}"

                        cmd_bgm = [
                            _get_ffmpeg_exe(), "-y",
                            "-stream_loop", "-1",
                            "-i", raw_bgm_source,
                            "-t", f"{video_dur:.3f}",
                            "-af", af_filter,
                            "-ac", "2", "-ar", "44100",
                            str(target_bgm_wav)
                        ]
                        subprocess.run(cmd_bgm, capture_output=True, check=True)
                        if target_bgm_wav.exists() and target_bgm_wav.stat().st_size > 0:
                            # 4. Nếu bật Smart Audio Ducking trên BGM thì dìm nhạc BGM khi có giọng thoại lồng tiếng
                            if enable_audio_ducking and realized_timeline:
                                ducked_bgm_wav = temp_dir / "ducked_prepared_bgm.wav"
                                self.apply_audio_ducking_pure_python(str(target_bgm_wav), str(ducked_bgm_wav), realized_timeline)
                                if ducked_bgm_wav.exists() and ducked_bgm_wav.stat().st_size > 0:
                                    prepared_bgm_path = str(ducked_bgm_wav)
                                else:
                                    prepared_bgm_path = str(target_bgm_wav)
                            else:
                                prepared_bgm_path = str(target_bgm_wav)

                            print(f"[DubbingService BGM] Prepared background track matched to {video_dur:.1f}s at {prepared_bgm_path}")
                    except Exception as bgm_err:
                        print(f"[DubbingService Warning] Failed to prepare BGM track: {bgm_err}")

                # --- PHA TRỘN CÁC LUỒNG ÂM THANH THEO TỶ LỆ CHUẨN STUDIO BROADCAST ---
                t_args = ["-t", f"{video_dur:.3f}"] if video_dur > 0 else []

                if mute_original_audio:
                    if prepared_bgm_path:
                        if progress_callback:
                            progress_callback("Đang xuất âm thanh lồng tiếng + Nhạc nền BGM (đã tắt nhạc gốc)...")
                        cmd_mix = [
                            _get_ffmpeg_exe(), "-y",
                            "-i", merged_vocal_path,
                            "-i", prepared_bgm_path,
                            "-filter_complex", "[0:a]apad,volume=1.5[vocal_b];[1:a]volume=1.0[bgm_b];[vocal_b][bgm_b]amix=inputs=2:duration=first[mix_raw];[mix_raw]volume=1.3[out]",
                            "-map", "[out]", "-acodec", "libmp3lame", "-q:a", "2"
                        ] + t_args + [final_audio_path]
                    else:
                        if progress_callback:
                            progress_callback("Đang xuất âm thanh lồng tiếng thuần khiết (đã tắt nhạc nền bản quyền)...")
                        cmd_mix = [
                            _get_ffmpeg_exe(), "-y",
                            "-i", merged_vocal_path,
                            "-af", "apad",
                            "-acodec", "libmp3lame", "-q:a", "2"
                        ] + t_args + [final_audio_path]
                else:
                    if prepared_bgm_path:
                        if progress_callback:
                            progress_callback("Đang pha trộn giọng lồng tiếng + Nhạc nền gốc đã triệt thoại + Nhạc BGM...")
                        cmd_mix = [
                            _get_ffmpeg_exe(), "-y",
                            "-i", clean_background_audio,
                            "-i", merged_vocal_path,
                            "-i", prepared_bgm_path,
                            "-filter_complex", "[0:a]volume=1.35[env_b];[1:a]apad,volume=1.25[vocal_b];[2:a]volume=0.90[bgm_b];[env_b][vocal_b][bgm_b]amix=inputs=3:duration=first:dropout_transition=0:normalize=0[out]",
                            "-map", "[out]", "-acodec", "libmp3lame", "-q:a", "2"
                        ] + t_args + [final_audio_path]
                    else:
                        cmd_mix = [
                            _get_ffmpeg_exe(), "-y",
                            "-i", clean_background_audio,
                            "-i", merged_vocal_path,
                            "-filter_complex", "[0:a]volume=1.35[env_b];[1:a]apad,volume=1.25[vocal_b];[env_b][vocal_b]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[out]",
                            "-map", "[out]", "-acodec", "libmp3lame", "-q:a", "2"
                        ] + t_args + [final_audio_path]

                subprocess.run(cmd_mix, capture_output=True, check=True)

            # 8. Muxer: Đè âm thanh lồng tiếng mới vào video cũ không cần render lại hình ảnh (Giữ nguyên 100% chất lượng video)
            if progress_callback:
                progress_callback("Đang xuất video hoạt hình lồng tiếng Việt thành phẩm...")

            ass_path = temp_dir / "subtitles.ass"
            srt_path = temp_dir / "subtitles.srt"
            has_subtitles = False
            if burn_subtitles and realized_timeline:
                try:
                    if progress_callback:
                        progress_callback("Đang tự động biên soạn và tạo file phụ đề ASS tiếng Việt...")
                    self.generate_ass_file(
                        realized_timeline,
                        str(ass_path),
                        caption_preset=caption_preset,
                        aspect_ratio=aspect_ratio,
                        enable_karaoke=enable_karaoke if 'enable_karaoke' in locals() else True,
                        font_family=caption_font_family,
                        custom_font_size=caption_font_size,
                        custom_y_percent=caption_y_percent,
                        custom_color=caption_color,
                    )
                    self.generate_srt_file(realized_timeline, str(srt_path))
                    has_subtitles = os.path.exists(ass_path) and os.path.getsize(ass_path) > 0
                except Exception as sub_err:
                    print(f"[DubbingService Warning] Failed to write subtitle files: {sub_err}")

            # Tạo file cấu hình fonts.conf trong thư mục tạm thời để giải quyết lỗi Fontconfig trên Windows
            # Đăng ký thư mục fonts của hệ thống lẫn thư mục fonts dự án chứa Montserrat
            from worker.config import FONTS_DIR
            fonts_conf_path = temp_dir / "fonts.conf"
            fonts_conf_content = f"""<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig>
    <dir>/usr/share/fonts</dir>
    <dir>/usr/local/share/fonts</dir>
    <dir>~/.fonts</dir>
    <dir>C:\\Windows\\Fonts</dir>
    <dir>{FONTS_DIR.as_posix()}</dir>
    <include ignore_missing="yes">/etc/fonts/fonts.conf</include>
</fontconfig>
"""
            try:
                with open(fonts_conf_path, "w", encoding="utf-8") as f:
                    f.write(fonts_conf_content)
            except Exception as fe:
                print(f"[DubbingService Warning] Failed to write fonts.conf: {fe}")

            # Sử dụng đường dẫn tương đối (relative path) từ thư mục làm việc hiện tại (CWD)
            try:
                rel_ass_path = os.path.relpath(ass_path).replace("\\", "/")
                escaped_ass = rel_ass_path.replace("'", "'\\''")
            except Exception:
                escaped_ass = str(ass_path).replace("\\", "/").replace(":", "\\:").replace("'", "'\\''")

            # Cấu hình môi trường fontconfig truyền cho FFmpeg
            env_copy = os.environ.copy()
            env_copy["FONTCONFIG_FILE"] = str(fonts_conf_path)
            env_copy["FONTCONFIG_PATH"] = str(temp_dir)
            env_copy["FC_CONFIG_DIR"] = str(temp_dir)

            # Dynamic FFmpeg Filter Complex Construction
            filter_nodes = []
            current_v = "[0:v]"

            # 0. Anti-Copyright Mirror Flip & Color Grading (Lật gương hflip + Color grading)
            if progress_callback:
                progress_callback("Đang áp dụng bộ lọc lật gương anti-copyright...")
            filter_nodes.append(
                f"{current_v}hflip,eq=contrast=1.04:brightness=0.01:saturation=1.05[v_anti_wm]"
            )
            current_v = "[v_anti_wm]"

            # 0.1 Quét nhận diện Bounding Box chính xác bằng Computer Vision (OpenCV)
            ai_sub_box = None
            ai_logo_box = None
            if blur_original_subtitles or blur_original_logo:
                try:
                    if progress_callback:
                        progress_callback("Đang kích hoạt AI Computer Vision (OpenCV) quét nhận diện Bounding Box vị trí chữ & logo...")
                    from worker.services.smart_text_detector import SmartTextDetector
                    ai_regions = SmartTextDetector.detect_video_regions(video_path, realized_timeline)
                    ai_sub_box = ai_regions.get("subtitle")
                    ai_logo_tl = ai_regions.get("logo_topleft")
                    ai_logo_tr = ai_regions.get("logo_topright")
                except Exception as cv_err:
                    print(f"[DubbingService Warning] CV Detector error: {cv_err}")

            # 1. Original Logo & Watermark Blur (Che mờ Logo Kênh Gốc & Watermark ID góc trên/dưới)
            if blur_original_logo:
                if progress_callback:
                    progress_callback("Đang tự động che mờ Logo & Watermark kênh gốc (Góc trên trái & Góc trên phải)...")

                # Chỉ che mờ khi AI Computer Vision thực sự quét thấy Bounding Box của Logo/Watermark
                if ai_logo_tr:
                    logo_w = ai_logo_tr.get("w_ratio", 0.15)
                    logo_h = ai_logo_tr.get("h_ratio", 0.04)
                    raw_x = ai_logo_tr.get("x_ratio", 0.65)
                    # Sau hflip, tọa độ x_ratio bên phải lật về bên trái: x_flipped = 1.0 - raw_x - logo_w
                    logo_x = max(0.0, round(1.0 - raw_x - logo_w, 3))
                    logo_y = ai_logo_tr.get("y_top_ratio", 0.01)
                    filter_nodes.append(
                        f"{current_v}split=2[v_logo_base1][v_logo_tr];"
                        f"[v_logo_tr]crop=iw*{logo_w:.3f}:ih*{logo_h:.3f}:iw*{logo_x:.3f}:ih*{logo_y:.3f},boxblur=8:2[v_blur_tr];"
                        f"[v_logo_base1][v_blur_tr]overlay=W*{logo_x:.3f}:H*{logo_y:.3f}[v_logo_clean1]"
                    )
                    current_v = "[v_logo_clean1]"

                if ai_logo_tl:
                    logo_w = ai_logo_tl.get("w_ratio", 0.15)
                    logo_h = ai_logo_tl.get("h_ratio", 0.04)
                    raw_x = ai_logo_tl.get("x_ratio", 0.0)
                    # Sau hflip, tọa độ x_ratio bên trái lật sang bên phải
                    logo_x = max(0.0, round(1.0 - raw_x - logo_w, 3))
                    logo_y = ai_logo_tl.get("y_top_ratio", 0.01)
                    filter_nodes.append(
                        f"{current_v}split=2[v_logo_base2][v_logo_tl];"
                        f"[v_logo_tl]crop=iw*{logo_w:.3f}:ih*{logo_h:.3f}:iw*{logo_x:.3f}:ih*{logo_y:.3f},boxblur=8:2[v_blur_tl];"
                        f"[v_logo_base2][v_blur_tl]overlay=W*{logo_x:.3f}:H*{logo_y:.3f}[v_logo_clean2]"
                    )
                    current_v = "[v_logo_clean2]"

            # 2. Original Subtitle Blur / Smart Dynamic Centered Bounding Box Blur (if enabled)
            if blur_original_subtitles:
                dynamic_applied = False

                # Sử dụng tọa độ từ AI Computer Vision nếu phát hiện được
                if ai_sub_box:
                    y_top_ratio = max(0.72, min(0.85, ai_sub_box.get("y_top_ratio", 0.81)))
                    h_ratio = min(0.18, max(0.08, ai_sub_box.get("h_ratio", 0.13)))
                    x_ratio = max(0.0, min(0.30, ai_sub_box.get("x_ratio", 0.05)))
                    w_ratio = min(1.0 - x_ratio, max(0.40, ai_sub_box.get("w_ratio", 0.90)))
                else:
                    y_center_pct = float(caption_y_percent or 80.0) / 100.0
                    h_ratio = min(0.18, max(0.08, float(blur_region_height_ratio or 0.13)))
                    y_top_ratio = max(0.72, min(0.88, y_center_pct - (h_ratio / 2.0)))
                    x_ratio = 0.0
                    w_ratio = 1.0

                if smart_dynamic_blur and realized_timeline:
                    try:
                        if progress_callback:
                            progress_callback("Đang áp dụng bộ lọc khoanh vùng động AI (chỉ mờ đúng giây chữ xuất hiện)...")
                        
                        # Gom nhóm các mốc thời gian thoại để sinh điều kiện enable='between(t,st,et)'
                        time_intervals = []
                        for seg in realized_timeline:
                            st = max(0.0, float(seg.get("start", 0.0)))
                            et = max(st + 0.1, float(seg.get("end", st + 0.5)))
                            if time_intervals and (st - time_intervals[-1][1]) < 0.5:
                                time_intervals[-1] = (time_intervals[-1][0], max(time_intervals[-1][1], et))
                            else:
                                time_intervals.append((st, et))

                        if time_intervals:
                            enable_conditions = " + ".join([f"between(t,{st:.2f},{et:.2f})" for st, et in time_intervals])
                            filter_nodes.append(
                                f"{current_v}split=2[v_dyn_base][v_dyn_strip];"
                                f"[v_dyn_strip]crop=iw*{w_ratio:.3f}:ih*{h_ratio:.3f}:iw*{x_ratio:.3f}:ih*{y_top_ratio:.3f},boxblur=8:2[v_dyn_blur];"
                                f"[v_dyn_base][v_dyn_blur]overlay=W*{x_ratio:.3f}:H*{y_top_ratio:.3f}:enable='{enable_conditions}'[v_unsub]"
                            )
                            current_v = "[v_unsub]"
                            dynamic_applied = True
                    except Exception as dyn_err:
                        print(f"[DubbingService Warning] Dynamic blur fallback to static: {dyn_err}")
                        dynamic_applied = False

                if not dynamic_applied:
                    if progress_callback:
                        progress_callback("Đang tự động che mờ vùng phụ đề tiếng Trung gốc...")
                    filter_nodes.append(
                        f"{current_v}split=2[v_base][v_strip];"
                        f"[v_strip]crop=iw*{w_ratio:.3f}:ih*{h_ratio:.3f}:iw*{x_ratio:.3f}:ih*{y_top_ratio:.3f},boxblur=8:2[v_blur_strip];"
                        f"[v_base][v_blur_strip]overlay=W*{x_ratio:.3f}:H*{y_top_ratio:.3f}[v_unsub]"
                    )
                    current_v = "[v_unsub]"

            # 3. Channel Logo / Watermark Handle
            if logo_handle and logo_handle.strip():
                clean_handle = logo_handle.strip().replace("'", "'\\''").replace(":", "\\:")
                filter_nodes.append(
                    f"{current_v}drawtext=text='{clean_handle}':x=35:y=35:fontsize=22:fontcolor=white@0.85:shadowcolor=black@0.6:shadowx=2:shadowy=2[v_logo]"
                )
                current_v = "[v_logo]"

            # 3. Aspect Ratio Transformation
            if aspect_ratio == "vertical_blur":
                if progress_callback:
                    progress_callback("Đang chuyển đổi kích thước video sang Dọc 9:16 với viền mờ nghệ thuật...")
                filter_nodes.append(
                    f"{current_v}split=2[v_split_bg][v_split_fg];"
                    f"[v_split_bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=8:2,setsar=1[bg];"
                    f"[v_split_fg]scale=1080:-1:force_original_aspect_ratio=decrease,setsar=1[fg];"
                    f"[bg][fg]overlay=(W-w)/2:(H-h)/2[v_aspect]"
                )
                current_v = "[v_aspect]"

            # 4. Burn Vietnamese Subtitles
            if has_subtitles:
                if progress_callback:
                    progress_callback("Đang ghi cứng phụ đề tiếng Việt chuẩn SEO vào video...")
                filter_nodes.append(f"{current_v}subtitles='{escaped_ass}'[outv]")
            else:
                filter_nodes.append(f"{current_v}null[outv]")

            filter_complex_str = ";".join(filter_nodes)

            encoder_name, encoder_opts = self.detect_gpu_encoder()
            cmd_mux = [
                _get_ffmpeg_exe(), "-y",
                "-i", video_path,
                "-i", final_audio_path,
                "-filter_complex", filter_complex_str,
                "-map", "[outv]",
                "-map", "1:a:0",
                "-c:v", encoder_name, *encoder_opts,
                "-c:a", "aac", "-strict", "-2",
            ]
            if video_dur > 0:
                cmd_mux.extend(["-t", f"{video_dur:.3f}"])
            else:
                cmd_mux.append("-shortest")
            cmd_mux.append(output_path)

            subprocess.run(cmd_mux, capture_output=True, check=True, env=env_copy)

            if progress_callback:
                progress_callback("Hoàn thành quy trình lồng tiếng AI chất lượng cao! 🎉")
            success = True
            return True, realized_timeline

        except subprocess.CalledProcessError as cpe:
            print(f"[DubbingService Fatal Error] Subprocess failed with exit code {cpe.returncode}")
            print(f"Command run: {' '.join(cpe.cmd) if isinstance(cpe.cmd, list) else cpe.cmd}")
            if cpe.stdout:
                print(f"[Subprocess Stdout]:\n{cpe.stdout.decode(errors='ignore')}")
            if cpe.stderr:
                print(f"[Subprocess Stderr]:\n{cpe.stderr.decode(errors='ignore')}")
            import traceback
            traceback.print_exc()
            return False, []
        except Exception as e:
            print(f"[DubbingService Fatal Error] Dubbing pipeline failed: {e}")
            import traceback
            traceback.print_exc()
            return False, []

        finally:
            # Dọn dẹp thư mục tạm VÔ ĐIỀU KIỆN — dù pipeline THÀNH CÔNG hay THẤT BẠI.
            # Ngăn chặn tích tụ hàng trăm MB file WAV/MP3 thô sau mỗi lần crash.
            import shutil
            try:
                if temp_dir.exists():
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    print(f"[DubbingService Cleanup] ✅ Đã xóa sạch thư mục tạm: {temp_dir}")
            except Exception as cleanup_err:
                print(f"[DubbingService Cleanup Warning] Không thể xóa thư mục tạm {temp_dir}: {cleanup_err}")
