"""
Publisher Factory — Factory Pattern
=====================================
Registry trung tâm: platform name → Publisher class.

Để thêm nền tảng mới (Instagram, Snapchat, Facebook Reels...):
  1. Tạo file: worker/services/publishers/instagram_publisher.py
  2. Kế thừa SocialPublisher và implement publish()
  3. Thêm 1 dòng vào PLATFORM_REGISTRY bên dưới
  → Không cần sửa bất kỳ file nào khác (OCP compliant)
"""
from __future__ import annotations

import os

from worker.services.publishers.base import SocialPublisher


def _build_platform_registry() -> dict[str, type[SocialPublisher]]:
    """
    Lazy-load publisher classes để tránh ImportError khi Playwright
    chưa được cài đặt trong môi trường kiểm thử / CI.
    """
    registry: dict = {}
    try:
        from worker.services.publishers.tiktok_publisher import TikTokPublisher
        registry["tiktok"] = TikTokPublisher
    except ImportError:
        pass
    try:
        from worker.services.publishers.youtube_publisher import YouTubePublisher
        registry["youtube"] = YouTubePublisher
    except ImportError:
        pass
    return registry

# ── Registry: platform → Publisher class ─────────────────────────────────────
PLATFORM_REGISTRY: dict[str, type[SocialPublisher]] = _build_platform_registry()


def get_publisher(
    platform: str,
    profile_dir: str,
) -> SocialPublisher:
    """
    Factory function: tạo đúng publisher cho platform được yêu cầu.

    Args:
        platform:    Tên nền tảng ('tiktok', 'youtube', ...).
        profile_dir: Đường dẫn tuyệt đối thư mục Chrome profile.

    Returns:
        Instance của SocialPublisher phù hợp.

    Raises:
        ValueError: Nếu platform chưa có trong registry.
    """
    publisher_class = PLATFORM_REGISTRY.get(platform.lower())
    if not publisher_class:
        supported = ", ".join(PLATFORM_REGISTRY.keys())
        raise ValueError(
            f"Platform '{platform}' chưa được đăng ký. "
            f"Hỗ trợ hiện tại: {supported}"
        )
    return publisher_class(profile_dir=profile_dir)


def resolve_profile_dir(platform: str, platform_connection_id: int | None, worker_dir: str) -> str:
    """
    Chuẩn hóa tên thư mục Chrome profile theo platform và connection ID.
    Tách logic này ra khỏi use case để dễ kiểm thử và tái sử dụng.
    """
    if platform == "youtube":
        dir_name = (
            f"chrome_profile_youtube_{platform_connection_id}"
            if platform_connection_id
            else "chrome_profile_youtube"
        )
    else:
        dir_name = (
            f"chrome_profile_{platform_connection_id}"
            if platform_connection_id
            else "chrome_profile"
        )
    return os.path.join(worker_dir, dir_name)
