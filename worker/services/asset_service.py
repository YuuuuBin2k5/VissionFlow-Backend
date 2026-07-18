import requests
import random
import json
import hashlib
from dataclasses import dataclass, asdict
from pathlib import Path
from worker.config import PEXELS_API_KEY, PIXABAY_API_KEY, COVERR_API_KEY, ASSETS_DIR


@dataclass
class StockVideoCandidate:
    provider: str
    query: str
    link: str
    source_url: str
    duration: float
    width: int
    height: int
    score: int
    creator: str = ""
    license: str = "Pexels License"
    provider_asset_id: str = ""

    @property
    def aspect_ratio(self) -> float:
        if not self.height:
            return 0.0
        return self.width / self.height


class AssetService:
    def __init__(self):
        self.api_key = PEXELS_API_KEY
        self.pixabay_api_key = PIXABAY_API_KEY
        self.coverr_api_key = COVERR_API_KEY
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
        selected_candidate = self._find_best_video_candidate(keywords)
        
        # Self-Healing 1: Nếu lỗi hoặc không có video, rút gọn từ khóa về các từ cơ bản (danh từ chính)
        if not selected_candidate:
            simplified_keywords = self._simplify_keywords(keywords)
            if simplified_keywords != keywords:
                print(f"[AssetService Fallback] No videos for '{keywords}'. Retrying simplified: '{simplified_keywords}'")
                selected_candidate = self._find_best_video_candidate(simplified_keywords)

        # Self-Healing 2: Nếu vẫn lỗi, dùng các từ khóa mặc định an toàn cho nội dung
        if not selected_candidate:
            default_keywords = random.choice(["nature vertical", "abstract vertical", "city vertical", "aesthetic vertical"])
            print(f"[AssetService Fallback] No videos for simplified keywords. Using safe default: '{default_keywords}'")
            selected_candidate = self._find_best_video_candidate(default_keywords)

        # 2. Tải video về thư mục tạm
        output_filename = f"scene_{scene_id}_{random.randint(1000, 9999)}.mp4"
        output_path = str(ASSETS_DIR / output_filename)

        if selected_candidate:
            try:
                self._download_file(selected_candidate.link, output_path)
                self._write_asset_metadata(output_path, selected_candidate)
                self._notify_provider_download(selected_candidate)
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
        candidates = self._find_video_candidates(keywords, count=count)
        if not candidates:
            simplified_keywords = self._simplify_keywords(keywords)
            if simplified_keywords != keywords:
                candidates = self._find_video_candidates(simplified_keywords, count=count)

        if not candidates:
            for fallback_keywords in ["aesthetic vertical", "city night vertical", "abstract light vertical"]:
                candidates = self._find_video_candidates(fallback_keywords, count=count)
                if candidates:
                    break

        paths = []
        for index, candidate in enumerate(candidates[:count]):
            output_path = str(ASSETS_DIR / f"scene_{job_id}_beat_{index}_{random.randint(1000, 9999)}.mp4")
            try:
                self._download_file(candidate.link, output_path)
                self._write_asset_metadata(output_path, candidate)
                self._notify_provider_download(candidate)
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
            for candidate in self._find_video_candidates(keyword, count=per_keyword):
                if candidate.link in seen_urls:
                    continue
                seen_urls.add(candidate.link)
                output_path = str(ASSETS_DIR / f"scene_{job_id}_scenic_{len(paths)}_{random.randint(1000, 9999)}.mp4")
                try:
                    self._download_file(candidate.link, output_path)
                    self._write_asset_metadata(output_path, candidate)
                    self._notify_provider_download(candidate)
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
        """Thực hiện gọi API Pexels tìm kiếm video dọc.

        RANDOM POOL SELECTION — Lấy Top 8 kết quả, bốc ngẫu nhiên 1 video
        từ pool để đảm bảo mỗi lần render tạo ra hình ảnh không trùng lặp,
        dù các chiến dịch cùng dùng chung từ khóa.
        """
        candidates = self._search_pexels_candidates(
            query=query,
            per_page=12,
            minimum_duration=4,
            prefer_portrait=True,
        )
        selected = self._select_candidate_from_ranked_pool(candidates)
        return selected.link if selected else ""


    def _search_pexels_videos(self, query: str, count: int = 5) -> list:
        candidates = self._search_pexels_candidates(
            query=query,
            per_page=max(8, min(24, count * 4)),
            minimum_duration=4,
            prefer_portrait=True,
        )
        links = []
        seen = set()
        for candidate in candidates:
            if candidate.link in seen:
                continue
            seen.add(candidate.link)
            links.append(candidate.link)
            if len(links) >= count:
                break
        return links

    def _find_best_video_candidate(self, query: str) -> StockVideoCandidate | None:
        candidates = self._find_video_candidates(query, count=5)
        return self._select_candidate_from_ranked_pool(candidates)

    def _find_video_candidates(self, query: str, count: int = 5) -> list[StockVideoCandidate]:
        candidates = self._search_pexels_candidates(
            query=query,
            per_page=max(8, min(30, count * 4)),
            minimum_duration=4,
            prefer_portrait=True,
        )
        if len(candidates) < count:
            candidates.extend(
                self._search_pixabay_candidates(
                    query=query,
                    per_page=max(8, min(30, count * 4)),
                    minimum_duration=4,
                    prefer_portrait=True,
                )
            )
        if len(candidates) < count:
            candidates.extend(
                self._search_coverr_candidates(
                    query=query,
                    page_size=max(8, min(20, count * 3)),
                    minimum_duration=4,
                    prefer_portrait=True,
                )
            )
        candidates.sort(key=lambda item: item.score, reverse=True)
        deduped = []
        seen = set()
        for candidate in candidates:
            if candidate.link in seen:
                continue
            seen.add(candidate.link)
            deduped.append(candidate)
            if len(deduped) >= count:
                break
        return deduped

    def _search_pexels_candidates(
        self,
        query: str,
        per_page: int = 12,
        minimum_duration: int = 4,
        prefer_portrait: bool = True,
    ) -> list[StockVideoCandidate]:
        if not self.api_key or self.api_key == "YOUR_PEXELS_API_KEY_HERE":
            print("[AssetService] API Key is not set or invalid. Skipping Pexels fetch.")
            return []

        url = "https://api.pexels.com/videos/search"
        params = {
            "query": query,
            "per_page": max(1, min(40, per_page)),
        }
        if prefer_portrait:
            params["orientation"] = "portrait"

        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=15)
            if response.status_code != 200:
                print(f"[AssetService API Warning] Pexels returned status {response.status_code}")
                return []
            videos = response.json().get("videos", [])
        except Exception as exc:
            print(f"[AssetService Exception] Pexels request failed: {exc}")
            return []

        candidates: list[StockVideoCandidate] = []
        seen_links = set()
        for video in videos:
            duration = float(video.get("duration") or 0)
            if duration < minimum_duration:
                continue

            chosen_file = self._choose_best_pexels_file(video.get("video_files", []), prefer_portrait)
            if not chosen_file or not chosen_file.get("link"):
                continue
            if chosen_file["link"] in seen_links:
                continue
            seen_links.add(chosen_file["link"])

            user = video.get("user") or {}
            creator = user.get("name", "Pexels Creator") if isinstance(user, dict) else "Pexels Creator"
            width = int(chosen_file.get("width") or video.get("width") or 0)
            height = int(chosen_file.get("height") or video.get("height") or 0)
            score = self._score_stock_candidate(
                query=query,
                duration=duration,
                width=width,
                height=height,
                metadata_text=" ".join([
                    str(video.get("url") or ""),
                    str(creator),
                ]),
                prefer_portrait=prefer_portrait,
            )
            candidates.append(
                StockVideoCandidate(
                    provider="pexels",
                    query=query,
                    link=chosen_file["link"],
                    source_url=video.get("url") or "https://www.pexels.com",
                    duration=duration,
                    width=width,
                    height=height,
                    score=score,
                    creator=creator,
                )
            )

        candidates.sort(key=lambda item: item.score, reverse=True)
        print(f"[AssetService] Ranked {len(candidates)} Pexels candidates for query: '{query[:70]}'")
        return candidates

    def _search_pixabay_candidates(
        self,
        query: str,
        per_page: int = 12,
        minimum_duration: int = 4,
        prefer_portrait: bool = True,
    ) -> list[StockVideoCandidate]:
        if not self.pixabay_api_key:
            return []

        url = "https://pixabay.com/api/videos/"
        params = {
            "key": self.pixabay_api_key,
            "q": query,
            "per_page": max(3, min(40, per_page)),
            "safesearch": "true",
            "video_type": "all",
        }
        if prefer_portrait:
            params["orientation"] = "vertical"

        try:
            response = requests.get(url, params=params, timeout=15)
            if response.status_code != 200:
                print(f"[AssetService API Warning] Pixabay returned status {response.status_code}: {response.text[:120]}")
                return []
            videos = response.json().get("hits", [])
        except Exception as exc:
            print(f"[AssetService Exception] Pixabay request failed: {exc}")
            return []

        candidates: list[StockVideoCandidate] = []
        seen_links = set()
        for video in videos:
            duration = float(video.get("duration") or 0)
            if duration < minimum_duration:
                continue

            chosen_file = self._choose_best_pixabay_file(video.get("videos") or {}, prefer_portrait)
            if not chosen_file or not chosen_file.get("url"):
                continue
            if chosen_file["url"] in seen_links:
                continue
            seen_links.add(chosen_file["url"])

            width = int(chosen_file.get("width") or 0)
            height = int(chosen_file.get("height") or 0)
            tags = str(video.get("tags") or "")
            creator = str(video.get("user") or "Pixabay Creator")
            score = self._score_stock_candidate(
                query=query,
                duration=duration,
                width=width,
                height=height,
                metadata_text=" ".join([tags, creator, str(video.get("pageURL") or "")]),
                prefer_portrait=prefer_portrait,
            )
            candidates.append(
                StockVideoCandidate(
                    provider="pixabay",
                    query=query,
                    link=chosen_file["url"],
                    source_url=video.get("pageURL") or "https://pixabay.com",
                    duration=duration,
                    width=width,
                    height=height,
                    score=score,
                    creator=creator,
                    license="Pixabay Content License",
                )
            )

        candidates.sort(key=lambda item: item.score, reverse=True)
        print(f"[AssetService] Ranked {len(candidates)} Pixabay candidates for query: '{query[:70]}'")
        return candidates

    def _search_coverr_candidates(
        self,
        query: str,
        page_size: int = 12,
        minimum_duration: int = 4,
        prefer_portrait: bool = True,
    ) -> list[StockVideoCandidate]:
        if not self.coverr_api_key:
            return []

        url = "https://api.coverr.co/videos"
        params = {
            "query": query,
            "page_size": max(1, min(20, page_size)),
            "sort": "popular",
            "urls": "true",
        }
        headers = {
            "Authorization": f"Bearer {self.coverr_api_key}",
        }

        try:
            response = requests.get(url, headers=headers, params=params, timeout=15)
            if response.status_code != 200:
                print(f"[AssetService API Warning] Coverr returned status {response.status_code}: {response.text[:120]}")
                return []
            videos = response.json().get("hits", [])
        except Exception as exc:
            print(f"[AssetService Exception] Coverr request failed: {exc}")
            return []

        candidates: list[StockVideoCandidate] = []
        seen_links = set()
        for video in videos:
            duration = float(video.get("duration") or 0)
            if duration < minimum_duration:
                continue

            urls = video.get("urls") or {}
            link = urls.get("mp4_download") or urls.get("mp4")
            if not link or link in seen_links:
                continue
            seen_links.add(link)

            width = int(video.get("max_width") or 0)
            height = int(video.get("max_height") or 0)
            if bool(video.get("is_vertical")) and width > height:
                width, height = height, width

            metadata_text = " ".join([
                str(video.get("title") or ""),
                str(video.get("description") or ""),
                " ".join([str(tag) for tag in video.get("tags") or []]),
            ])
            score = self._score_stock_candidate(
                query=query,
                duration=duration,
                width=width,
                height=height,
                metadata_text=metadata_text,
                prefer_portrait=prefer_portrait,
            )
            if prefer_portrait and video.get("is_vertical"):
                score += 5

            video_id = str(video.get("id") or "")
            candidates.append(
                StockVideoCandidate(
                    provider="coverr",
                    query=query,
                    link=link,
                    source_url=f"https://coverr.co/videos/{video_id}" if video_id else "https://coverr.co",
                    duration=duration,
                    width=width,
                    height=height,
                    score=score,
                    creator="Coverr",
                    license="Coverr API License - attribution required",
                    provider_asset_id=video_id,
                )
            )

        candidates.sort(key=lambda item: item.score, reverse=True)
        print(f"[AssetService] Ranked {len(candidates)} Coverr candidates for query: '{query[:70]}'")
        return candidates

    def _choose_best_pixabay_file(self, videos: dict, prefer_portrait: bool = True) -> dict | None:
        if not isinstance(videos, dict):
            return None

        candidates = []
        for quality in ["large", "medium", "small", "tiny"]:
            item = videos.get(quality)
            if isinstance(item, dict) and item.get("url"):
                candidates.append(item)
        if not candidates:
            return None

        portrait_files = [
            item for item in candidates
            if int(item.get("width") or 0) < int(item.get("height") or 0)
        ]
        pool = portrait_files if prefer_portrait and portrait_files else candidates

        def quality_key(item: dict) -> tuple:
            width = int(item.get("width") or 0)
            height = int(item.get("height") or 0)
            portrait_bonus = 1 if width < height else 0
            target_width_distance = abs(width - 1080)
            resolution = width * height
            return (portrait_bonus, -target_width_distance, resolution)

        pool.sort(key=quality_key, reverse=True)
        return pool[0]

    def _choose_best_pexels_file(self, video_files: list, prefer_portrait: bool = True) -> dict | None:
        valid_files = [f for f in video_files if f.get("link") and f.get("width") and f.get("height")]
        if not valid_files:
            return None

        portrait_files = [f for f in valid_files if int(f.get("width") or 0) < int(f.get("height") or 0)]
        pool = portrait_files if prefer_portrait and portrait_files else valid_files

        def quality_key(item: dict) -> tuple:
            width = int(item.get("width") or 0)
            height = int(item.get("height") or 0)
            portrait_bonus = 1 if width < height else 0
            target_width_distance = abs(width - 1080)
            resolution = width * height
            return (portrait_bonus, -target_width_distance, resolution)

        pool.sort(key=quality_key, reverse=True)
        return pool[0]

    def _score_stock_candidate(
        self,
        query: str,
        duration: float,
        width: int,
        height: int,
        metadata_text: str = "",
        prefer_portrait: bool = True,
    ) -> int:
        score = 0
        if duration >= 12:
            score += 4
        elif duration >= 7:
            score += 2
        elif duration < 4:
            score -= 8

        if width and height:
            if width < height:
                score += 6 if prefer_portrait else 2
                ratio = width / height
                score += max(0, 4 - int(abs(ratio - (9 / 16)) * 20))
            elif width >= 1280 and height >= 720:
                score += 2
            else:
                score -= 3

            if width >= 720 and height >= 1280:
                score += 3
            elif width >= 540 and height >= 960:
                score += 1

        query_tokens = {
            token.strip().lower()
            for token in str(query or "").replace("-", " ").split()
            if len(token.strip()) >= 4
        }
        metadata = str(metadata_text or "").lower()
        score += min(4, sum(1 for token in query_tokens if token in metadata))

        avoid_terms = ["logo", "watermark", "brand", "trademark"]
        if any(term in metadata for term in avoid_terms):
            score -= 6

        return score

    def _select_candidate_from_ranked_pool(self, candidates: list[StockVideoCandidate]) -> StockVideoCandidate | None:
        if not candidates:
            return None
        top_pool = candidates[: min(5, len(candidates))]
        # Weighted randomness keeps videos fresh but still favors strong matches.
        min_score = min(item.score for item in top_pool)
        weights = [max(1, item.score - min_score + 1) for item in top_pool]
        selected = random.choices(top_pool, weights=weights, k=1)[0]
        print(
            f"[AssetService] Selected candidate score={selected.score}, "
            f"duration={selected.duration}s, size={selected.width}x{selected.height}, "
            f"provider={selected.provider}"
        )
        return selected

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

    def _write_asset_metadata(self, output_path: str, candidate: StockVideoCandidate | None):
        if not candidate:
            return
        metadata_path = f"{output_path}.metadata.json"
        payload = asdict(candidate)
        payload["download_hash"] = hashlib.sha256(candidate.link.encode("utf-8")).hexdigest()[:16]
        payload["attribution_required"] = candidate.provider == "coverr"
        try:
            with open(metadata_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            print(f"[AssetService Warning] Failed to write asset metadata: {exc}")

    def _notify_provider_download(self, candidate: StockVideoCandidate | None):
        if not candidate or candidate.provider != "coverr" or not candidate.provider_asset_id:
            return
        if not self.coverr_api_key:
            return

        url = f"https://api.coverr.co/videos/{candidate.provider_asset_id}/stats/downloads"
        headers = {
            "Authorization": f"Bearer {self.coverr_api_key}",
        }
        try:
            response = requests.patch(url, headers=headers, timeout=10)
            if response.status_code not in (200, 204):
                print(f"[AssetService API Warning] Coverr download stat returned status {response.status_code}")
        except Exception as exc:
            print(f"[AssetService Warning] Failed to notify Coverr download stat: {exc}")

    def search_and_download_lofi_loop(self, job_id: int) -> str:
        """
        Tìm kiếm và tải video lofi anime loop dọc 9:16 chất lượng cao.
        Sử dụng xoay vòng các từ khóa mỹ thuật (aesthetic queries) nổi tiếng nhất của dòng lofi chill.
        Tích hợp danh sách link dự phòng (bulletproof fallback list) cực kỳ đẹp và an toàn.
        """
        print(f"[AssetService] Searching Pexels for premium lofi loop (Job {job_id})")
        
        queries = [
            "lofi rain room vertical",
            "anime bedroom loop vertical",
            "pixel art room rain vertical",
            "starry night lofi loop vertical",
            "cozy train window vertical",
            "cafe rainy day aesthetic vertical"
        ]
        
        # Chọn ngẫu nhiên một từ khóa để đảm bảo sự đa dạng giữa các video
        query = random.choice(queries)
        print(f"[AssetService] Selected premium query: '{query}'")
        video_url = self._search_pexels_video(query)
        
        # Nếu không tìm thấy, thử các truy vấn lofi rộng hơn
        if not video_url:
            for fallback_query in queries:
                if fallback_query != query:
                    print(f"[AssetService Fallback] Retrying query: '{fallback_query}'")
                    video_url = self._search_pexels_video(fallback_query)
                    if video_url:
                        break
                        
        # Danh sách liên kết video Lofi Anime Loop dự phòng cực kỳ nổi tiếng và chất lượng siêu đẹp (direct high-quality URLs)
        # Các video này được lưu trữ trên Pexels CDN rất ổn định
        premium_fallbacks = [
            "https://videos.pexels.com/video-files/3129671/3129671-hd_1080_1920_30fps.mp4", # Cozy rain window with neon lights
            "https://videos.pexels.com/video-files/2816215/2816215-hd_1080_1920_24fps.mp4", # Cozy room fireplace warm ambient
            "https://videos.pexels.com/video-files/4252655/4252655-hd_1080_1920_25fps.mp4", # Aesthetic starry night mountain train
            "https://videos.pexels.com/video-files/18069608/18069608-hd_1080_1920_24fps.mp4", # Beautiful lofi pixel city rain loop
            "https://videos.pexels.com/video-files/18069614/18069614-hd_1080_1920_24fps.mp4"  # Pixel cafe street rain aesthetic
        ]
        
        if not video_url:
            print("[AssetService Fallback] API didn't return vertical loop. Using bulletproof premium lofi fallback URL!")
            video_url = random.choice(premium_fallbacks)
            
        output_path = str(ASSETS_DIR / f"scene_{job_id}_lofi_{random.randint(1000, 9999)}.mp4")
        try:
            self._download_file(video_url, output_path)
            return output_path
        except Exception as e:
            print(f"[AssetService Error] Failed to download premium lofi video: {e}")
            try:
                print("[AssetService Emergency] Attempting emergency backup download...")
                self._download_file(premium_fallbacks[0], output_path)
                return output_path
            except Exception as emergency_err:
                raise Exception(f"Không thể tải bất kỳ video lofi anime nào: {emergency_err}")

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

    def score_bottom_asset(self, video: dict, requirements: dict = None) -> int:
        """
        Chấm điểm video ứng viên dựa trên các tiêu chí:
        - +5 nếu duration >= 45s
        - +3 nếu duration >= 30s
        - -5 nếu duration < 20s
        - +4 nếu video vertical (width < height)
        - +2 nếu video ngang nhưng đủ độ phân giải để crop (width >= 1280 và height >= 720)
        - +4 nếu keyword/tags/name chứa cooking, preparation, mixing, cutting, baking, kneading, pouring, stirring, plating, organizing, cleaning (so khớp không phân biệt hoa thường)
        - -5 nếu có watermark, logo, brand rõ
        """
        score = 0
        
        # 1. Chấm điểm theo thời lượng (duration)
        duration = video.get("duration", 0)
        if duration >= 45:
            score += 5
        elif duration >= 30:
            score += 3
        elif duration < 20:
            score -= 5
            
        # 2. Chấm điểm theo độ phân giải / hướng quay (orientation)
        width = video.get("width", 0)
        height = video.get("height", 0)
        
        if width < height:
            score += 4  # Video dọc (vertical)
        elif width >= 1280 and height >= 720:
            score += 2  # Video ngang nhưng đủ phân giải để crop dọc
            
        # 3. Chấm điểm theo nội dung từ khóa/tags/tên
        check_words = [
            "cooking", "preparation", "mixing", "cutting", "baking", 
            "kneading", "pouring", "stirring", "plating", "organizing", "cleaning"
        ]
        
        # Lấy tất cả thông tin văn bản từ video một cách an toàn
        text_metadata = []
        if video.get("url"):
            text_metadata.append(video.get("url"))
            
        user = video.get("user")
        if isinstance(user, dict):
            user_name = user.get("name")
            if user_name:
                text_metadata.append(user_name)
                
        tags = video.get("tags")
        if tags is not None:
            if isinstance(tags, list):
                text_metadata.extend([str(t) for t in tags if t])
            else:
                text_metadata.append(str(tags))
                
        if video.get("description"):
            text_metadata.append(video.get("description"))
            
        metadata_str = " ".join([str(item) for item in text_metadata if item]).lower()
        
        # So khớp từ khóa
        if any(word in metadata_str for word in check_words):
            score += 4
            
        # 4. Trừ điểm nếu có dấu hiệu watermark/logo/brand
        avoid_words = ["watermark", "logo", "brand"]
        if any(word in metadata_str for word in avoid_words):
            score -= 5
            
        return score

    def search_and_download_best_bottom_asset(self, query: str, job_id: int, requirements: dict = None) -> dict | None:
        """
        Tìm kiếm nhiều video ứng viên (20-40 kết quả) từ Pexels,
        chấm điểm từng ứng viên và tải về video tốt nhất.
        Lọc bỏ các video dưới 30 giây trước khi chọn.
        """
        if not self.api_key or self.api_key == "YOUR_PEXELS_API_KEY_HERE":
            print("[AssetService] API Key is not set or invalid. Skipping Pexels fetch.")
            return None

        url = "https://api.pexels.com/videos/search"
        params = {
            "query": query,
            "per_page": 30,
        }
        
        try:
            print(f"[AssetService] Fetching up to 30 candidates for query: '{query}'")
            response = requests.get(url, headers=self.headers, params=params, timeout=15)
            if response.status_code != 200:
                print(f"[AssetService API Warning] Pexels returned status {response.status_code}")
                return None
                
            data = response.json()
            videos = data.get("videos", [])
            if not videos:
                return None
                
            scored_candidates = []
            for video in videos:
                score = self.score_bottom_asset(video, requirements)
                # Lấy link video phù hợp nhất của candidate này
                video_files = video.get("video_files", [])
                valid_files = [f for f in video_files if f.get("link")]
                if not valid_files:
                    continue
                
                # Sắp xếp để lấy link dọc hoặc link crop tốt nhất
                vertical_files = [f for f in valid_files if f.get("width", 0) < f.get("height", 0)]
                if vertical_files:
                    # Ưu tiên độ phân giải gần 720p nhất
                    vertical_files.sort(key=lambda x: abs((x.get("width") or 720) - 720))
                    chosen_file = vertical_files[0]
                else:
                    # Nếu ngang thì lấy link gốc có độ phân giải lớn để crop
                    valid_files.sort(key=lambda x: x.get("width", 0) * x.get("height", 0), reverse=True)
                    chosen_file = valid_files[0]
                    
                user_obj = video.get("user") or {}
                photographer_name = user_obj.get("name", "Pexels Creator") if isinstance(user_obj, dict) else "Pexels Creator"
                
                scored_candidates.append({
                    "video_obj": video,
                    "link": chosen_file["link"],
                    "width": chosen_file.get("width", video.get("width")),
                    "height": chosen_file.get("height", video.get("height")),
                    "duration": video.get("duration", 0),
                    "url": video.get("url"),
                    "photographer": photographer_name,
                    "score": score
                })
                
            # Lọc bỏ các video dưới 30 giây
            scored_candidates = [c for c in scored_candidates if c["duration"] >= 30]
            
            if not scored_candidates:
                print("[AssetService] No candidates with duration >= 30s found.")
                return None
                
            # Sắp xếp các ứng viên theo điểm số giảm dần
            scored_candidates.sort(key=lambda x: x["score"], reverse=True)
            best_candidate = scored_candidates[0]
            
            print(f"[AssetService] Selected best candidate with score={best_candidate['score']} from {len(scored_candidates)} options (duration={best_candidate['duration']}s).")
            
            # Tải tệp video về
            output_filename = f"scene_best_bottom_{job_id}_{random.randint(1000, 9999)}.mp4"
            output_path = str(ASSETS_DIR / output_filename)
            
            self._download_file(best_candidate["link"], output_path)
            self._write_asset_metadata(
                output_path,
                StockVideoCandidate(
                    provider="pexels",
                    query=query,
                    link=best_candidate["link"],
                    source_url=best_candidate["url"] or "https://www.pexels.com",
                    duration=float(best_candidate["duration"] or 0),
                    width=int(best_candidate["width"] or 0),
                    height=int(best_candidate["height"] or 0),
                    score=int(best_candidate["score"] or 0),
                    creator=best_candidate["photographer"],
                ),
            )
            
            return {
                "path": output_path,
                "source_url": best_candidate["url"],
                "duration": best_candidate["duration"],
                "width": best_candidate["width"],
                "height": best_candidate["height"],
                "score": best_candidate["score"],
                "selected_query": query,
                "provider": "pexels",
                "creator": best_candidate["photographer"],
                "license": "Pexels License",
            }
            
        except Exception as e:
            print(f"[AssetService Error] Failed in search_best_bottom_asset: {e}")
            return None
