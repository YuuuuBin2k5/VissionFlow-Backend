"""
Publishers Package
==================
Export các thành phần của Publisher Adapter layer.

Để thêm nền tảng mới:
  1. Tạo <platform>_publisher.py kế thừa SocialPublisher
  2. Thêm vào PLATFORM_REGISTRY trong publisher_factory.py
"""
from __future__ import annotations

from worker.services.publishers.base import SocialPublisher, PublishPayload, PublishResult
from worker.services.publishers.publisher_factory import get_publisher, resolve_profile_dir, PLATFORM_REGISTRY

__all__ = [
    "SocialPublisher",
    "PublishPayload",
    "PublishResult",
    "get_publisher",
    "resolve_profile_dir",
    "PLATFORM_REGISTRY",
]
