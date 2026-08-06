import json
import random
from pathlib import Path

try:
    from moviepy.editor import VideoFileClip
except ImportError:
    from moviepy import VideoFileClip

from worker.config import LOCAL_ASSETS_DIR


class LocalAssetLibraryService:
    VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}

    def __init__(self):
        self.root = LOCAL_ASSETS_DIR
        self.cache_path = self.root / ".asset_cache.json"
        self.used_paths: set[str] = set()

    def find_video(
        self,
        category: str,
        keywords: str = "",
        min_duration_seconds: float = 0,
        exclude_used: bool = True,
        target_duration: float | None = None,
    ) -> dict | None:
        """
        Tìm chọn video từ kho tài nguyên cục bộ dựa vào phân cảnh kịch bản:
        1. Xếp hạng chất lượng video (4K/1080p, Khung dọc 9:16, độ phân giải cao).
        2. Luân phiên thay đổi ngẫu nhiên tránh trùng lặp file giữa các phân cảnh.
        3. Tự động tính toán khung cắt (seek window) ngẫu nhiên từ video dài.
        """
        category_dir = self.root / category
        category_dir.mkdir(parents=True, exist_ok=True)

        candidates = []
        keyword_tokens = self._tokens(keywords)

        # Lặp quét tất cả các file video trong thư mục phân loại
        for path in category_dir.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in self.VIDEO_EXTENSIONS:
                continue
            metadata = self._probe_video(path)
            if not metadata:
                continue
            if metadata["duration"] < min_duration_seconds:
                continue
            
            # Tính điểm chất lượng chuẩn HD/4K + Độ tương thích từ khóa
            metadata["score"] = self._score(path, metadata, keyword_tokens)
            candidates.append(metadata)

        if not candidates:
            # Fallback quét toàn bộ thư mục gốc LOCAL_ASSETS_DIR nếu thư mục phân loại rỗng
            for path in self.root.rglob("*"):
                if not path.is_file() or path.suffix.lower() not in self.VIDEO_EXTENSIONS:
                    continue
                metadata = self._probe_video(path)
                if metadata and metadata["duration"] >= min_duration_seconds:
                    metadata["score"] = self._score(path, metadata, keyword_tokens)
                    candidates.append(metadata)

        if not candidates:
            print(
                f"[LocalAssetLibrary] No local video for category={category}, "
                f"min_duration={min_duration_seconds}s"
            )
            return None

        # 1. Lọc bớt các video đã sử dụng trước đó trong cùng luồng video (Anti-Repetition Rotation)
        unused_candidates = [c for c in candidates if c["path"] not in self.used_paths]
        pool = unused_candidates if (unused_candidates and exclude_used) else candidates

        # 2. Xếp hạng danh sách video theo tổng điểm chất lượng giảm dần
        pool.sort(key=lambda item: item["score"], reverse=True)
        best_score = pool[0]["score"]

        # 3. Lấy Pool Top 5 video chất lượng cao nhất để chọn ngẫu nhiên có trọng số
        top_pool = [item for item in pool if item["score"] >= best_score - 4][:5]
        chosen = dict(random.choice(top_pool))
        self.used_paths.add(chosen["path"])

        # 4. Tự động tính toán khoảng trích xuất ngẫu nhiên (Smart Sub-clip Window) nếu video quá dài
        clip_dur = chosen["duration"]
        if target_duration and target_duration > 0 and clip_dur > (target_duration + 2.0):
            max_start = clip_dur - target_duration - 0.5
            start_time = round(random.uniform(1.0, max(1.0, max_start)), 2)
            end_time = round(start_time + target_duration, 2)
        else:
            start_time = 0.0
            end_time = round(min(clip_dur, target_duration or clip_dur), 2)

        chosen["start_time"] = start_time
        chosen["end_time"] = end_time

        print(
            f"[LocalAssetLibrary Smart Pick] Selected '{Path(chosen['path']).name}' "
            f"(Score: {chosen['score']}, Res: {chosen['width']}x{chosen['height']}, "
            f"Segment: {start_time}s -> {end_time}s / Total: {clip_dur:.1f}s)"
        )
        return chosen

    def reset_rotation_cache(self):
        """Xóa bộ nhớ đệm luân phiên thay đổi video cho phiên render mới."""
        self.used_paths.clear()

    def _probe_video(self, path: Path) -> dict | None:
        cache = self._read_cache()
        key = str(path.resolve())
        stat = path.stat()
        cached = cache.get(key)
        if cached and cached.get("mtime") == stat.st_mtime and cached.get("size") == stat.st_size:
            return cached

        clip = None
        try:
            clip = VideoFileClip(str(path))
            metadata = {
                "path": str(path),
                "duration": float(clip.duration or 0),
                "width": int(clip.w or 0),
                "height": int(clip.h or 0),
                "source": "local",
                "mtime": stat.st_mtime,
                "size": stat.st_size,
            }
            cache[key] = metadata
            self._write_cache(cache)
            return metadata
        except Exception as exc:
            print(f"[LocalAssetLibrary Warning] Failed to probe {path}: {exc}")
            return None
        finally:
            if clip:
                clip.close()

    def _score(self, path: Path, metadata: dict, keyword_tokens: set[str]) -> int:
        name_tokens = self._tokens(path.stem.replace("_", " ").replace("-", " "))
        score = len(keyword_tokens.intersection(name_tokens)) * 6

        width = metadata.get("width") or 0
        height = metadata.get("height") or 0
        dur = metadata.get("duration", 0)
        size = metadata.get("size", 0)

        # 1. Chấm điểm độ phân giải HD/4K
        if height >= 2160 or width >= 2160:
            score += 15  # 4K Ultra-HD
        elif height >= 1920 or width >= 1920:
            score += 10  # 1080p Full-HD
        elif height >= 1280 or width >= 1280:
            score += 5   # 720p HD

        # 2. Ưu tiên khung hình dọc (Portrait 9:16)
        if height > width:
            score += 12
        elif width and height:
            score += 3

        # 3. Ưu tiên video có mật độ chất lượng / dung lượng cao
        if size >= 20_000_000:
            score += 5
        elif size >= 5_000_000:
            score += 2

        # 4. Ưu tiên video có độ dài đủ để trích xuất đa dạng
        if dur >= 30:
            score += 6

        return score

    def _tokens(self, text: str) -> set[str]:
        return {
            token.strip().lower()
            for token in str(text or "").replace(",", " ").split()
            if len(token.strip()) >= 3
        }

    def _read_cache(self) -> dict:
        try:
            if self.cache_path.exists():
                return json.loads(self.cache_path.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _write_cache(self, cache: dict):
        try:
            self.cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            print(f"[LocalAssetLibrary Warning] Failed to write cache: {exc}")
