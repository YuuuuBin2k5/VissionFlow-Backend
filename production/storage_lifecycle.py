"""
Storage Lifecycle Manager for VisionFlow Auto Production System (Phase 7 - Section 17).
Enforces formal segregation across RAW, DERIVED, TEMP, and FINAL media tiers,
with automated garbage collection of intermediate temporary files.
"""

from __future__ import annotations

import logging
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from production.contracts import StorageTier

logger = logging.getLogger("visionflow.production.storage_lifecycle")

MEDIA_ROOT = Path(os.getenv("VISIONFLOW_MEDIA_CACHE", ".media_cache")).resolve()


class StorageLifecycleManager:
    """
    Coordinates multi-tier media storage and retention policies:
    - RAW: Uploaded source videos/assets (protected from deletion)
    - DERIVED: Extracted scene clips, TTS synthesis cache, keyframes (long-term reusable)
    - TEMP: Concatenation lists, uncompressed wav files, temporary ffmpeg frames (short-lived, pruned by GC)
    - FINAL: Broadcast-ready MP4 Shorts and 3D cover cards (permanent publishable assets)
    """

    def __init__(self, media_root: Optional[Path] = None):
        self.root = media_root or MEDIA_ROOT
        self.raw_dir = self.root / "raw"
        self.derived_dir = self.root / "derived"
        self.temp_dir = self.root / "temp"
        self.final_dir = self.root / "exports"

        for d in (self.raw_dir, self.derived_dir, self.temp_dir, self.final_dir):
            d.mkdir(parents=True, exist_ok=True)

    def get_tier_path(self, tier: StorageTier) -> Path:
        if tier == StorageTier.RAW:
            return self.raw_dir
        elif tier == StorageTier.DERIVED:
            return self.derived_dir
        elif tier == StorageTier.TEMP:
            return self.temp_dir
        elif tier == StorageTier.FINAL:
            return self.final_dir
        return self.temp_dir

    def create_temp_workspace(self, run_id: str) -> Path:
        work_dir = self.temp_dir / run_id
        work_dir.mkdir(parents=True, exist_ok=True)
        return work_dir

    def cleanup_temp_files(
        self,
        max_age_seconds: int = 3600,
        active_run_ids: Optional[Set[str]] = None,
    ) -> int:
        """
        Garbage-collects temporary render chunks and concat lists older than max_age_seconds.
        Never touches RAW, DERIVED, or FINAL tiers.
        """
        now = time.time()
        deleted_count = 0
        active_set = active_run_ids or set()

        if not self.temp_dir.exists():
            return 0

        for item in self.temp_dir.iterdir():
            if item.name in active_set:
                continue  # Skip active runs
            try:
                mtime = item.stat().st_mtime
                if now - mtime > max_age_seconds:
                    if item.is_dir():
                        shutil.rmtree(item, ignore_errors=True)
                    else:
                        item.unlink(missing_ok=True)
                    deleted_count += 1
            except Exception as e:
                logger.warning("Error cleaning temp item %s: %s", item, e)

        logger.info("Cleaned up %d temporary files from %s", deleted_count, self.temp_dir)
        return deleted_count

    def get_storage_stats(self) -> Dict[str, Any]:
        """
        Calculates storage consumption across all 4 tiers.
        """
        stats: Dict[str, Any] = {}
        for tier, path in [
            ("RAW", self.raw_dir),
            ("DERIVED", self.derived_dir),
            ("TEMP", self.temp_dir),
            ("FINAL", self.final_dir),
        ]:
            total_bytes = 0
            file_count = 0
            if path.exists():
                for root, _, files in os.walk(path):
                    for f in files:
                        try:
                            fp = os.path.join(root, f)
                            total_bytes += os.path.getsize(fp)
                            file_count += 1
                        except Exception:
                            pass
            stats[tier] = {
                "path": str(path),
                "file_count": file_count,
                "size_bytes": total_bytes,
                "size_mb": round(total_bytes / (1024 * 1024), 2),
            }
        return stats


storage_lifecycle = StorageLifecycleManager()
