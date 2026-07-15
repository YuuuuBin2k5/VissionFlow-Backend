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

    def find_video(
        self,
        category: str,
        keywords: str = "",
        min_duration_seconds: float = 0,
    ) -> dict | None:
        category_dir = self.root / category
        category_dir.mkdir(parents=True, exist_ok=True)

        candidates = []
        keyword_tokens = self._tokens(keywords)
        for path in category_dir.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in self.VIDEO_EXTENSIONS:
                continue
            metadata = self._probe_video(path)
            if not metadata:
                continue
            if metadata["duration"] < min_duration_seconds:
                continue
            metadata["score"] = self._score(path, metadata, keyword_tokens)
            candidates.append(metadata)

        if not candidates:
            print(
                f"[LocalAssetLibrary] No local video for category={category}, "
                f"min_duration={min_duration_seconds}s"
            )
            return None

        candidates.sort(key=lambda item: item["score"], reverse=True)
        best_score = candidates[0]["score"]
        top_pool = [item for item in candidates if item["score"] >= best_score - 2]
        chosen = random.choice(top_pool[:8])
        print(
            f"[LocalAssetLibrary] Selected {chosen['path']} "
            f"({chosen['duration']:.1f}s, {chosen['width']}x{chosen['height']})"
        )
        return chosen

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
        score = len(keyword_tokens.intersection(name_tokens)) * 4
        width = metadata.get("width") or 0
        height = metadata.get("height") or 0
        if height >= width:
            score += 6
        elif width and height:
            score += 2
        if metadata.get("duration", 0) >= 60:
            score += 4
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
