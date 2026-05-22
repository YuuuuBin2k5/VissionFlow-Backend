import os
import random
import urllib.request
from pathlib import Path
import json

from worker.config import ASSETS_DIR
from worker.services.llm_service import LLMService

# Mapping high-quality stable royalty-free MP3s to standard moods
MOOD_MUSIC_URLS = {
    "SAD_RAIN": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-4.mp3",
    "CYBERPUNK_NIGHT": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-3.mp3",
    "COZY_CHILL": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3",
    "FOCUS_LOFI": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-2.mp3",
}

class TrendingMusicService:
    def __init__(self):
        self.llm = LLMService()

    def resolve_trending_song_for_topic(self, topic: str, current_title: str = None) -> tuple[str, str, str]:
        """
        Dùng Gemini phân tích chủ đề video (topic) hoặc tiêu đề video (current_title) 
        để gợi ý đúng 1 bài hát V-Pop/TikTok Trend thực tế đang cực kỳ thịnh hành 
        phù hợp nhất với tâm trạng/nội dung đó, cùng mood tương ứng.
        Trả về tuple: (song_title, artist_name, mood)
        Mood phải khớp vào một trong: SAD_RAIN, CYBERPUNK_NIGHT, COZY_CHILL, FOCUS_LOFI.
        """
        input_text = f"Chủ đề: {topic}"
        if current_title:
            input_text += f"\nTiêu đề video: {current_title}"

        print(f"[TrendingMusicService] Resolving trend song for topic: '{topic}'...")
        prompt = f"""
        Bạn là chuyên gia nhạc lý và giám đốc âm nhạc TikTok. Hãy phân tích chủ đề hoặc tiêu đề video sau:
        "{input_text}"

        NHIỆM VỤ:
        1. Đề xuất đúng 1 bài hát V-Pop/Nhạc Việt (hoặc bản Remix, Lofi hot trend) thực tế đang cực kỳ thịnh hành ở Việt Nam và phù hợp hoàn hảo với sắc thái/nội dung của video này.
           Ví dụ:
           - Video buồn hoài niệm học sinh, kỷ niệm lớp -> "Sau Lời Từ Khước" (Phan Mạnh Quỳnh) hoặc "Mình Cùng Nhau Đóng Băng" (Thùy Chi), mood: SAD_RAIN
           - Video công việc, Excel, kỹ năng -> Nhạc lofi thư giãn nhẹ nhàng, mood: COZY_CHILL hoặc FOCUS_LOFI
           - Video tư duy, động lực -> Nhạc acoustic bình yên tích cực, mood: COZY_CHILL
           - Video sôi động nhảy múa, remix -> Nhạc hot trend remix bass đập mạnh, mood: CYBERPUNK_NIGHT
        2. Phân loại cảm xúc chủ đạo (Mood) của bài hát này và khớp vào đúng 1 trong 4 nhãn dưới đây:
           - SAD_RAIN: Nhạc buồn hoài niệm, lofi trầm.
           - CYBERPUNK_NIGHT: Nhạc remix, EDM sôi động, thành phố neon.
           - COZY_CHILL: Nhạc acoustic, nhẹ nhàng, quán cafe, thư giãn.
           - FOCUS_LOFI: Nhạc lofi tập trung học tập, không lời sâu lắng.

        ĐẦU RA JSON DUY NHẤT:
        {{
          "song_title": "Tên bài hát thực tế",
          "artist_name": "Tên ca sĩ/nghệ sĩ thực tế",
          "mood": "SAD_RAIN / CYBERPUNK_NIGHT / COZY_CHILL / FOCUS_LOFI"
        }}
        LƯU Ý: CHỈ TRẢ VỀ JSON HỢP LỆ. KHÔNG CÓ KÝ TỰ MARKDOWN.
        """

        def fallback():
            trends = [
                {"song_title": "Sau Lời Từ Khước", "artist_name": "Phan Mạnh Quỳnh", "mood": "SAD_RAIN"},
                {"song_title": "Tình Đầu Quá Chén", "artist_name": "Quang Hùng MasterD", "mood": "CYBERPUNK_NIGHT"},
                {"song_title": "Lệ Lưu Ly", "artist_name": "Vũ Phụng Tiên", "mood": "COZY_CHILL"},
                {"song_title": "À Lôi", "artist_name": "Double2T", "mood": "CYBERPUNK_NIGHT"},
                {"song_title": "Khóa Ly Biệt", "artist_name": "Anh Tú", "mood": "SAD_RAIN"}
            ]
            return json.dumps(random.choice(trends), ensure_ascii=False)

        try:
            raw = self.llm._call_gemini_with_fallback(prompt, fallback)
            cleaned = self.llm._clean_json_string(raw)
            data = json.loads(cleaned)
            resolved_title = data.get("song_title", "Sau Lời Từ Khước")
            resolved_artist = data.get("artist_name", "Phan Mạnh Quỳnh")
            resolved_mood = data.get("mood", "SAD_RAIN")
            
            # Đảm bảo mood hợp lệ
            if resolved_mood not in ["SAD_RAIN", "CYBERPUNK_NIGHT", "COZY_CHILL", "FOCUS_LOFI"]:
                resolved_mood = "COZY_CHILL"
                
            print(f"[TrendingMusicService] Resolved Trend Song: '{resolved_title}' by {resolved_artist} (Mood: {resolved_mood})")
            return resolved_title, resolved_artist, resolved_mood
        except Exception as e:
            print(f"[TrendingMusicService Error] Failed to resolve trend song for topic: {e}. Using fallback...")
            fallback_data = json.loads(fallback())
            return fallback_data["song_title"], fallback_data["artist_name"], fallback_data["mood"]

    def resolve_trending_song_details(self, song_title: str, artist_name: str) -> tuple[str, str]:
        """
        Nếu tiêu đề là HOT TRENDING, gọi Gemini để gợi ý bài hát Việt Nam đang cực hot trên TikTok.
        Ngược lại, trả về bài hát custom của người dùng.
        """
        if song_title != "HOT TRENDING":
            return song_title, artist_name

        # Gọi hàm khớp nhạc đa năng với chủ đề chung
        title, artist, _ = self.resolve_trending_song_for_topic("Nhạc V-Pop Hot TikTok")
        return title, artist

    def download_mood_audio(self, mood: str, job_id: int) -> str:
        """
        Tải file âm thanh chất lượng cao tương ứng với Mood từ soundhelix hoặc copy lofi_ambient.mp3 có sẵn.
        Tên file bao gồm mood để phân biệt giữa các lượt render có mood khác nhau.
        Tự động dọn dẹp tệp âm thanh cũ của cùng job_id nếu mood thay đổi.
        """
        import shutil
        import glob
        import socket

        safe_mood = mood.lower().replace(" ", "_")
        dest_filename = f"music_video_{job_id}_{safe_mood}.mp3"
        dest_path = ASSETS_DIR / dest_filename

        # Dọn sạch các file nhạc cũ của cùng job_id (mood khác) để tránh tái sử dụng sai
        old_pattern = str(ASSETS_DIR / f"music_video_{job_id}_*.mp3")
        for old_file in glob.glob(old_pattern):
            if Path(old_file).name != dest_filename:
                try:
                    Path(old_file).unlink()
                    print(f"[TrendingMusicService] Purged stale audio cache: {old_file}")
                except Exception as purge_err:
                    print(f"[TrendingMusicService Warning] Could not purge {old_file}: {purge_err}")

        # Nếu đã tồn tại đúng file nhạc (cùng mood), dùng lại trực tiếp
        if dest_path.exists() and dest_path.stat().st_size > 0:
            print(f"[TrendingMusicService] Reusing cached audio for mood '{mood}': {dest_path}")
            return str(dest_path)

        url = MOOD_MUSIC_URLS.get(mood, MOOD_MUSIC_URLS["COZY_CHILL"])
        print(f"[TrendingMusicService] Downloading high-fidelity background beat from: {url} (Mood: {mood})")
        
        # Thiết lập socket timeout ngắn để tránh bị treo vô hạn ở mức socket read
        original_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(6.0)
        try:
            # Thiết lập User-Agent giả lập trình duyệt để tránh bị chặn tải file
            req = urllib.request.Request(
                url, 
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                raw_data = response.read()
            # Ghi an toàn: chỉ ghi khi tải xong hoàn toàn, tránh file tạm lỗi
            with open(dest_path, 'wb') as out_file:
                out_file.write(raw_data)
            print(f"[TrendingMusicService] Download complete! Saved to {dest_path}")
            return str(dest_path)
        except Exception as e:
            # Xóa bỏ tệp tạm lỗi nếu có để tránh lần sau nhận diện nhầm
            if dest_path.exists():
                dest_path.unlink(missing_ok=True)
            print(f"[TrendingMusicService Warning] Failed to download from soundhelix: {e}. Falling back to local lofi_ambient.mp3...")
            local_lofi = ASSETS_DIR / "lofi_ambient.mp3"
            if local_lofi.exists():
                shutil.copy(str(local_lofi), str(dest_path))
                print(f"[TrendingMusicService] Copied local lofi_ambient.mp3 to {dest_path}")
                return str(dest_path)
            else:
                # Nếu lofi_ambient.mp3 cũng không có, dùng test_full.mp3 hoặc test.mp3 từ thư mục gốc
                root_test = Path(__file__).resolve().parent.parent.parent / "test_full.mp3"
                if root_test.exists():
                    shutil.copy(str(root_test), str(dest_path))
                    print(f"[TrendingMusicService] Copied root test_full.mp3 to {dest_path}")
                    return str(dest_path)
                
                raise RuntimeError("Không tìm thấy bất kỳ file âm thanh nào để làm nhạc nền.")
        finally:
            # Khôi phục socket timeout ban đầu
            socket.setdefaulttimeout(original_timeout)
