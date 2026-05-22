import requests
import random
from pathlib import Path
from worker.config import PEXELS_API_KEY, ASSETS_DIR

class AssetService:
    def __init__(self):
        self.api_key = PEXELS_API_KEY
        self.headers = {
            "Authorization": self.api_key
        }

    def search_and_download_video(self, keywords: str, scene_id: int) -> str:
        """
        Tìm kiếm video nền dọc trên Pexels dựa trên từ khóa và tải về.
        Tích hợp cơ chế tự sửa lỗi (Self-Healing) khi không tìm thấy kết quả.
        """
        print(f"[AssetService] Searching Pexels for: '{keywords}' (Scene {scene_id})")
        
        # 1. Thử tìm kiếm với từ khóa gốc
        video_url = self._search_pexels_video(keywords)
        
        # Self-Healing 1: Nếu lỗi hoặc không có video, rút gọn từ khóa về các từ cơ bản (danh từ chính)
        if not video_url:
            simplified_keywords = self._simplify_keywords(keywords)
            if simplified_keywords != keywords:
                print(f"[AssetService Fallback] No videos for '{keywords}'. Retrying simplified: '{simplified_keywords}'")
                video_url = self._search_pexels_video(simplified_keywords)

        # Self-Healing 2: Nếu vẫn lỗi, dùng các từ khóa mặc định an toàn cho nội dung
        if not video_url:
            default_keywords = random.choice(["nature vertical", "abstract vertical", "city vertical", "aesthetic vertical"])
            print(f"[AssetService Fallback] No videos for simplified keywords. Using safe default: '{default_keywords}'")
            video_url = self._search_pexels_video(default_keywords)

        # 2. Tải video về thư mục tạm
        output_filename = f"scene_{scene_id}_{random.randint(1000, 9999)}.mp4"
        output_path = str(ASSETS_DIR / output_filename)

        if video_url:
            try:
                print(f"[AssetService] Downloading video from: {video_url}")
                response = requests.get(video_url, stream=True, timeout=30)
                response.raise_for_status()
                with open(output_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=1024*1024):
                        if chunk:
                            f.write(chunk)
                print(f"[AssetService] Successfully saved asset to: {output_path}")
                return output_path
            except Exception as e:
                print(f"[AssetService Error] Failed to download video: {e}")
        
        # Tình huống xấu nhất: Trả về một chuỗi rỗng để media engine xử lý tạo ảnh nền tĩnh hoặc báo lỗi
        raise Exception("Không thể tìm và tải bất kỳ video nền nào từ Pexels API.")

    def search_and_download_videos(self, keywords: str, job_id: int, count: int = 5) -> list:
        """
        Tải nhiều video nền dọc cùng mood để phục vụ beat-cut render.
        Giữ fallback an toàn: nếu tải được ít nhất 1 video thì trả về danh sách đó.
        """
        video_urls = self._search_pexels_videos(keywords, count=count)
        if not video_urls:
            simplified_keywords = self._simplify_keywords(keywords)
            if simplified_keywords != keywords:
                video_urls = self._search_pexels_videos(simplified_keywords, count=count)

        if not video_urls:
            for fallback_keywords in ["aesthetic vertical", "city night vertical", "abstract light vertical"]:
                video_urls = self._search_pexels_videos(fallback_keywords, count=count)
                if video_urls:
                    break

        paths = []
        for index, video_url in enumerate(video_urls[:count]):
            output_path = str(ASSETS_DIR / f"scene_{job_id}_beat_{index}_{random.randint(1000, 9999)}.mp4")
            try:
                self._download_file(video_url, output_path)
                paths.append(output_path)
            except Exception as exc:
                print(f"[AssetService Warning] Failed to download beat-cut video {index}: {exc}")

        if not paths:
            paths.append(self.search_and_download_video(keywords, job_id))
        return paths

    def search_and_download_scenic_videos(self, keywords: list | str, job_id: int, target_count: int = 6) -> list:
        """
        Tải 4-6 video phong cảnh dọc từ nhiều keyword. Dùng cho scenic beat-cut pipeline.
        """
        keyword_list = keywords if isinstance(keywords, list) else [keywords]
        keyword_list = [str(keyword).strip() for keyword in keyword_list if str(keyword or "").strip()]
        if not keyword_list:
            keyword_list = ["misty forest vertical", "ocean sunset vertical", "rainy mountain vertical"]

        paths = []
        seen_urls = set()
        per_keyword = max(1, min(3, target_count))
        for keyword in keyword_list:
            for video_url in self._search_pexels_videos(keyword, count=per_keyword):
                if video_url in seen_urls:
                    continue
                seen_urls.add(video_url)
                output_path = str(ASSETS_DIR / f"scene_{job_id}_scenic_{len(paths)}_{random.randint(1000, 9999)}.mp4")
                try:
                    self._download_file(video_url, output_path)
                    paths.append(output_path)
                except Exception as exc:
                    print(f"[AssetService Warning] Failed to download scenic video for '{keyword}': {exc}")
                if len(paths) >= target_count:
                    return paths

        if not paths:
            fallback_keyword = keyword_list[0] if keyword_list else "nature vertical"
            paths = self.search_and_download_videos(fallback_keyword, job_id, count=min(target_count, 5))
        return paths[:target_count]

    def search_and_download_image(self, keywords: str, job_id: int) -> str:
        """
        Tải ảnh portrait/stock có license từ Pexels Photos cho mode portrait_lyric.
        Không tự lấy ảnh người thật/người nổi tiếng ngoài nguồn asset có quyền.
        """
        image_url = self._search_pexels_image(keywords)
        if not image_url:
            simplified_keywords = self._simplify_keywords(keywords)
            if simplified_keywords != keywords:
                image_url = self._search_pexels_image(simplified_keywords)

        if not image_url:
            for fallback_keywords in ["portrait silhouette aesthetic", "lofi portrait", "person neon portrait"]:
                image_url = self._search_pexels_image(fallback_keywords)
                if image_url:
                    break

        if not image_url:
            raise Exception("Không thể tìm và tải ảnh portrait từ Pexels API.")

        output_path = str(ASSETS_DIR / f"portrait_{job_id}_{random.randint(1000, 9999)}.jpg")
        self._download_file(image_url, output_path)
        return output_path

    def _search_pexels_video(self, query: str) -> str:
        """Thực hiện gọi API Pexels tìm kiếm video dọc"""
        if not self.api_key or self.api_key == "YOUR_PEXELS_API_KEY_HERE":
            print("[AssetService] API Key is not set or invalid. Skipping Pexels fetch.")
            return ""

        url = "https://api.pexels.com/videos/search"
        params = {
            "query": query,
            "per_page": 5,
            "orientation": "portrait" # Yêu cầu video dọc 9:16
        }

        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=15)
            if response.status_code == 200:
                data = response.json()
                videos = data.get("videos", [])
                if videos:
                    # Lấy video đầu tiên
                    video = videos[0]
                    video_files = video.get("video_files", [])
                    
                    # Chọn video file có chất lượng HD và định dạng mp4
                    # Tìm file có width tầm 1080 hoặc ít nhất là vertical
                    hd_files = [f for f in video_files if f.get("width") and f.get("height") and f["width"] < f["height"]]
                    if hd_files:
                        # Ưu tiên các file HD tầm 720p hoặc 1080p
                        hd_files.sort(key=lambda x: x.get("width", 0))
                        return hd_files[0]["link"] # Lấy file có chất lượng vừa phải để giảm dung lượng tải
                    
                    # Fallback lấy link đầu tiên
                    if video_files:
                        return video_files[0]["link"]
            else:
                print(f"[AssetService API Warning] Pexels returned status {response.status_code}")
        except Exception as e:
            print(f"[AssetService Exception] Pexels request failed: {e}")
            
        return ""

    def _search_pexels_videos(self, query: str, count: int = 5) -> list:
        if not self.api_key or self.api_key == "YOUR_PEXELS_API_KEY_HERE":
            print("[AssetService] API Key is not set or invalid. Skipping Pexels multi-video fetch.")
            return []

        url = "https://api.pexels.com/videos/search"
        params = {
            "query": query,
            "per_page": max(1, min(10, count * 2)),
            "orientation": "portrait"
        }

        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=15)
            if response.status_code != 200:
                print(f"[AssetService API Warning] Pexels videos returned status {response.status_code}")
                return []
            videos = response.json().get("videos", [])
            links = []
            for video in videos:
                video_files = video.get("video_files", [])
                vertical_files = [
                    f for f in video_files
                    if f.get("width") and f.get("height") and f["width"] < f["height"] and f.get("link")
                ]
                if not vertical_files:
                    vertical_files = [f for f in video_files if f.get("link")]
                if vertical_files:
                    vertical_files.sort(key=lambda item: abs((item.get("width") or 720) - 720))
                    links.append(vertical_files[0]["link"])
                if len(links) >= count:
                    break
            return links
        except Exception as exc:
            print(f"[AssetService Exception] Pexels multi-video request failed: {exc}")
            return []

    def _search_pexels_image(self, query: str) -> str:
        if not self.api_key or self.api_key == "YOUR_PEXELS_API_KEY_HERE":
            print("[AssetService] API Key is not set or invalid. Skipping Pexels image fetch.")
            return ""

        url = "https://api.pexels.com/v1/search"
        params = {
            "query": query,
            "per_page": 8,
            "orientation": "portrait"
        }
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=15)
            if response.status_code != 200:
                print(f"[AssetService API Warning] Pexels photos returned status {response.status_code}")
                return ""
            photos = response.json().get("photos", [])
            for photo in photos:
                src = photo.get("src", {})
                if src.get("large2x") or src.get("large") or src.get("portrait"):
                    return src.get("large2x") or src.get("large") or src.get("portrait")
        except Exception as exc:
            print(f"[AssetService Exception] Pexels image request failed: {exc}")
        return ""

    def _download_file(self, url: str, output_path: str) -> str:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        print(f"[AssetService] Downloading asset from: {url}")
        response = requests.get(url, stream=True, timeout=30)
        response.raise_for_status()
        with open(output_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
        print(f"[AssetService] Successfully saved asset to: {output_path}")
        return output_path

    def _simplify_keywords(self, keywords: str) -> str:
        """Rút gọn từ khóa phức tạp thành từ khóa đơn giản để tìm kiếm dễ trúng hơn"""
        # Bỏ đi các tính từ, từ bổ nghĩa phổ biến và chỉ giữ lại 1-2 từ khóa cốt lõi
        words = keywords.split()
        ignore_words = ["dynamic", "cinematic", "realistic", "beautiful", "high", "quality", "vertical", "portrait", "footage", "4k"]
        filtered = [w for w in words if w.lower() not in ignore_words]
        
        # Nếu từ khóa quá dài, chỉ lấy 2 từ cuối cùng (thường là danh từ chính)
        if len(filtered) > 2:
            return " ".join(filtered[-2:])
        elif filtered:
            return " ".join(filtered)
        return keywords
