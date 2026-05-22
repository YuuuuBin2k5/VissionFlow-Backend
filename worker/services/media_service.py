import os
import json
import random
from PIL import Image, ImageDraw, ImageFont
try:
    from moviepy.editor import (
        VideoFileClip, 
        AudioFileClip, 
        ImageClip, 
        CompositeVideoClip, 
        CompositeAudioClip,
        concatenate_videoclips
    )
except ImportError:
    from moviepy import (
        VideoFileClip, 
        AudioFileClip, 
        ImageClip, 
        CompositeVideoClip, 
        CompositeAudioClip,
        concatenate_videoclips
    )
from worker.config import ASSETS_DIR, OUTPUT_DIR, FONTS_DIR

class MediaService:
    def __init__(self):
        # Thiết lập font chữ tiếng Việt
        self.font_path = self._get_best_font()
        print(f"[MediaService] Using font: {self.font_path}")

    def _get_best_font(self) -> str:
        """Lấy font chữ việt hóa tốt nhất có sẵn trên hệ thống Windows hoặc thư mục shared"""
        # Thử tìm font trong thư mục shared
        custom_font = FONTS_DIR / "Montserrat-ExtraBold.ttf"
        if custom_font.exists():
            return str(custom_font)
            
        # Fallback về các font chữ nét dày có sẵn trên Windows
        windows_fonts = [
            "C:\\Windows\\Fonts\\Impact.ttf",
            "C:\\Windows\\Fonts\\arialbd.ttf", # Arial Bold
            "C:\\Windows\\Fonts\\tahomabd.ttf", # Tahoma Bold
            "C:\\Windows\\Fonts\\segoeuib.ttf"   # Segoe UI Bold
        ]
        for font in windows_fonts:
            if os.path.exists(font):
                return font
                
        return "arial.ttf" # Cực kỳ cơ bản

    def group_words_into_chunks(self, word_timestamps: list, max_words: int = 4, max_gap_ms: int = 500) -> list:
        """
        Thuật toán gom nhóm các từ đơn thành cụm hiển thị dòng (Subtitle Chunking).
        Không vượt quá 4 từ và khoảng nghỉ không quá 500ms.
        """
        if not word_timestamps:
            return []

        # Tự động phát hiện nếu dữ liệu bị fallback thành cả câu (SentenceBoundary) do Edge-TTS
        # Nếu bất cứ phần tử nào chứa khoảng trắng, chứng tỏ đây là cả câu/cụm từ dài -> KHÔNG gom nhóm nữa để tránh chữ bị lặp đè
        is_sentence_fallback = any(" " in item["word"] for item in word_timestamps)
        
        if is_sentence_fallback:
            formatted_chunks = []
            for item in word_timestamps:
                formatted_chunks.append({
                    "text": item["word"],
                    "start_s": item["start_ms"] / 1000.0,
                    "end_s": item["end_ms"] / 1000.0
                })
            return formatted_chunks

        chunks = []
        current_chunk = []

        for item in word_timestamps:
            if not current_chunk:
                current_chunk.append(item)
            else:
                gap = item["start_ms"] - current_chunk[-1]["end_ms"]
                if len(current_chunk) >= max_words or gap > max_gap_ms:
                    chunks.append(current_chunk)
                    current_chunk = [item]
                else:
                    current_chunk.append(item)

        if current_chunk:
            chunks.append(current_chunk)

        # Định dạng lại dữ liệu cụm dòng phụ đề
        formatted_chunks = []
        for chunk in chunks:
            text = " ".join([w["word"] for w in chunk])
            start_s = chunk[0]["start_ms"] / 1000.0
            end_s = chunk[-1]["end_ms"] / 1000.0
            formatted_chunks.append({
                "text": text,
                "start_s": start_s,
                "end_s": end_s
            })

        return formatted_chunks

    def wrap_text(self, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list:
        """Tự động xuống dòng khi độ rộng chữ vượt quá max_width"""
        words = text.split(" ")
        lines = []
        current_line = []
        
        # Tạo đối tượng ImageDraw giả để đo kích thước chữ
        dummy_img = Image.new("RGBA", (1, 1))
        dummy_draw = ImageDraw.Draw(dummy_img)
        
        for word in words:
            test_line = " ".join(current_line + [word]) if current_line else word
            
            # Đo chiều rộng chữ bằng phương pháp an toàn nhất
            try:
                bbox = dummy_draw.textbbox((0, 0), test_line, font=font)
                width = bbox[2] - bbox[0]
            except AttributeError:
                try:
                    width, _ = dummy_draw.textsize(test_line, font=font)
                except AttributeError:
                    width = font.getbbox(test_line)[2]
                    
            if width <= max_width:
                current_line.append(word)
            else:
                if current_line:
                    lines.append(" ".join(current_line))
                current_line = [word]
                
        if current_line:
            lines.append(" ".join(current_line))
            
        return lines

    def _create_subtitle_png(self, text: str, output_path: str, size=(1080, 1920)) -> str:
        """
        Dùng Pillow vẽ chữ viền đen nền trong suốt.
        Bypass hoàn toàn sự phụ thuộc vào ImageMagick trên Windows!
        Tự động ngắt dòng thông minh khi chữ quá dài.
        """
        # Tạo ảnh trong suốt RGBA
        image = Image.new("RGBA", size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        
        # Font size 55 - nhỏ hơn để chữ không bao giờ tràn viền
        fontsize = 55
        try:
            font = ImageFont.truetype(self.font_path, fontsize)
        except Exception:
            font = ImageFont.load_default()

        # Giới hạn chiều rộng tối đa: 1080 - 240px margin (120px mỗi bên) = 840px
        # Margin lớn hơn đảm bảo text + stroke không tràn ra frame
        max_width = 840
        lines = self.wrap_text(text, font, max_width)

        # Tính toán chiều cao một dòng
        try:
            bbox = draw.textbbox((0, 0), "Ag", font=font)
            line_height = bbox[3] - bbox[1]
        except AttributeError:
            try:
                _, line_height = draw.textsize("Ag", font=font)
            except AttributeError:
                line_height = font.getbbox("Ag")[3]
                
        line_spacing = 15
        total_height = len(lines) * line_height + (len(lines) - 1) * line_spacing

        # Đặt vị trí Y trung tâm ở 2/3 màn hình (Y = 1280)
        # Bắt đầu vẽ từ y_start sao cho cụm chữ được căn giữa theo chiều dọc quanh điểm 1280
        y_position_center = 1280
        start_y = y_position_center - total_height // 2

        # Vẽ từng dòng chữ căn giữa ngang
        for i, line in enumerate(lines):
            try:
                bbox = draw.textbbox((0, 0), line, font=font)
                text_width = bbox[2] - bbox[0]
            except AttributeError:
                try:
                    text_width, _ = draw.textsize(line, font=font)
                except AttributeError:
                    text_width = font.getbbox(line)[2]
                    
            x_position = (size[0] - text_width) // 2
            y_pos = start_y + i * (line_height + line_spacing)

            # Vẽ text có viền đen nổi bật (stroke 4px thay vì 5px để không làm rộng thêm nhiều)
            draw.text(
                (x_position, y_pos),
                line,
                font=font,
                fill="white",
                stroke_width=4,
                stroke_fill="black"
            )

        image.save(output_path, "PNG")
        return output_path

    def render_final_video(self, scenes_layout: list, word_timestamps: list, 
                           voice_audio_path: str, background_video_paths: list, 
                           job_id: int, background_music_path: str = None) -> str:
        """
        Biên tập toàn bộ Video bằng MoviePy:
        - Ghép nối, cắt các video nền tương thích với độ dài phân cảnh.
        - Trộn âm thanh đọc nói gốc + nhạc nền lofi nhẹ (-22dB).
        - Đè các file ảnh phụ đề trong suốt khớp thời gian (Karaoke Style).
        """
        print(f"[MediaService] Rendering video for Job #{job_id}")
        
        # 0. Load voice audio đầu tiên để lấy độ dài thực tế của giọng đọc (giá trị chuẩn xác tuyệt đối)
        voice_audio = AudioFileClip(voice_audio_path)
        voice_duration = voice_audio.duration

        # Tính tổng thời lượng của các phân cảnh theo kịch bản ban đầu
        sum_scene_durations = sum([scene.get("duration", 5) for scene in scenes_layout])
        
        # Tỷ lệ scale để kéo dãn/thu hẹp các phân cảnh cho khớp khít 100% với giọng đọc thực tế
        scale_factor = voice_duration / sum_scene_durations if sum_scene_durations > 0 else 1.0
        print(f"[MediaService] Voice duration: {voice_duration:.2f}s, sum of scene durations: {sum_scene_durations:.2f}s. Scale factor: {scale_factor:.4f}")

        # 1. Khởi tạo danh sách các Video Clip phân cảnh
        video_clips = []
        current_time = 0.0

        for idx, scene in enumerate(scenes_layout):
            original_duration = scene.get("duration", 5)
            # Khớp nối thời lượng đã được scale
            duration = original_duration * scale_factor
            if duration <= 0:
                duration = 1.0
                
            bg_path = background_video_paths[idx]
            
            # Load video nền và cắt theo thời lượng phân cảnh
            clip = VideoFileClip(bg_path)
            
            # Tự động crop/resize video nền về chuẩn 1080x1920 nếu cần
            clip = clip.resized(height=1920)
            if clip.w > 1080:
                clip = clip.cropped(x_center=clip.w/2, width=1080)
            
            # Cắt clip theo thời lượng kịch bản phân cảnh đã scale
            if clip.duration > duration:
                # Lấy ngẫu nhiên một khoảng clip nền để sinh động
                start_trim = random.uniform(0, max(0, clip.duration - duration - 0.5))
                clip = clip.subclipped(start_trim, start_trim + duration)
            else:
                # Nếu video ngắn hơn phân cảnh, cho lặp lại
                from moviepy import vfx
                clip = clip.with_effects([vfx.Loop(duration=duration)])
                
            video_clips.append(clip)
            current_time += duration

        # Ghép nối các phân cảnh thành video nền hoàn chỉnh
        final_bg = concatenate_videoclips(video_clips, method="compose")
        total_duration = final_bg.duration

        # 2. Xử lý Âm thanh (Voice + Background Music) - Sử dụng voice_audio đã load sẵn ở trên
        
        # Thử tìm file nhạc nền đã được chọn theo kịch bản/mood.
        music_clip = None
        bg_music_path = background_music_path or str(ASSETS_DIR / "lofi_ambient.mp3")
        
        # Nếu chưa có lofi_ambient, ta tạo file câm hoặc bỏ qua, nhưng để premium ta có thể dùng giọng nói làm audio chính
        audio_clips = [voice_audio]
        
        if bg_music_path and os.path.exists(bg_music_path):
            try:
                print(f"[MediaService] Mixing background music: {bg_music_path}")
                music_clip = AudioFileClip(str(bg_music_path))
                # Lặp nhạc nền nếu ngắn hơn video
                if music_clip.duration < total_duration:
                    from moviepy import afx
                    music_clip = music_clip.with_effects([afx.AudioLoop(duration=total_duration)])
                else:
                    music_clip = music_clip.subclipped(0, total_duration)
                
                # Hạ âm lượng nhạc xuống -22dB (tương đương giảm xuống hệ số ~0.08)
                music_clip = music_clip.with_volume_scaled(0.08)
                audio_clips.append(music_clip)
            except Exception as e:
                print(f"[MediaService Warning] Failed to mix background music: {e}")

        final_audio = CompositeAudioClip(audio_clips)
        final_bg = final_bg.with_audio(final_audio)

        # 3. Vẽ Phụ đề Động (Dynamic Karaoke Subtitles Overlay)
        subtitle_chunks = self.group_words_into_chunks(word_timestamps)
        subtitle_clips = []

        sub_temp_dir = ASSETS_DIR / f"subs_{job_id}"
        sub_temp_dir.mkdir(exist_ok=True)

        for s_idx, chunk in enumerate(subtitle_chunks):
            text = chunk["text"]
            start_s = chunk["start_s"]
            end_s = chunk["end_s"]
            duration = end_s - start_s

            if duration <= 0:
                continue

            # Tạo file ảnh PNG trong suốt chứa chữ phụ đề
            png_path = str(sub_temp_dir / f"sub_{s_idx}.png")
            self._create_subtitle_png(text, png_path)

            # Load vào làm ImageClip đè lên video nền
            # PNG đã là 1080x1920 - cùng kích thước video, đặt tại (0,0) tuyệt đối
            sub_clip = (
                ImageClip(png_path)
                .with_start(start_s)
                .with_duration(duration)
                .with_position((0, 0))  # Pillow đã vẽ chữ đúng vị trí, không cần di chuyển
            )
            subtitle_clips.append(sub_clip)

        # Ghép đè phụ đề lên trên video nền và tiếng nói
        final_video = CompositeVideoClip([final_bg] + subtitle_clips, size=(1080, 1920))
        final_video = final_video.with_duration(total_duration)

        # 4. Xuất Video .mp4 chất lượng cao
        output_file_path = str(OUTPUT_DIR / f"tiktok_video_{job_id}.mp4")
        
        print(f"[MediaService] Rendering final file to: {output_file_path}")
        # render với ffmpeg cấu hình tối ưu luồng
        final_video.write_videofile(
            output_file_path,
            fps=24,
            codec="libx264",
            audio_codec="aac",
            temp_audiofile=str(ASSETS_DIR / f"temp_audio_{job_id}.m4a"),
            remove_temp=True
        )

        # Đóng các luồng để giải phóng RAM (Self-Healing memory leaks)
        final_video.close()
        final_bg.close()
        voice_audio.close()
        for clip in video_clips:
            clip.close()
            
        # Dọn dẹp các ảnh phụ đề tạm thời để giải phóng dung lượng đĩa (giải quyết [L3])
        try:
            import shutil
            if sub_temp_dir.exists():
                shutil.rmtree(sub_temp_dir)
                print(f"[MediaService] Cleaned up temporary subtitle assets at: {sub_temp_dir}")
        except Exception as e:
            print(f"[MediaService Warning] Failed to clean up temporary subtitle files: {e}")

        print(f"[MediaService Success] Render completed! File size: {os.path.getsize(output_file_path)} bytes")
        return output_file_path
