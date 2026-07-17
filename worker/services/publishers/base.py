"""
Social Publisher Base — Adapter Pattern
=========================================
Định nghĩa giao diện chuẩn (contract) cho tất cả nền tảng publish.
Mỗi platform (TikTok, YouTube, Instagram...) phải implement SocialPublisher.

Điều này đảm bảo Open/Closed Principle: thêm nền tảng mới = thêm file mới,
không bao giờ cần sửa publish_use_case.py.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PublishPayload:
    """
    Dữ liệu đầu vào chuẩn cho mọi platform publish.
    Mọi SocialPublisher đều nhận cùng payload này.
    """
    title: str
    description: str
    hashtags: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    comment_text: Optional[str] = None
    music_metadata: Optional[dict] = None

    # Proxy configuration
    proxy_ip: Optional[str] = None
    proxy_port: Optional[int] = None
    proxy_user: Optional[str] = None
    proxy_pass: Optional[str] = None

    # Tùy chọn trình duyệt
    headless: bool = False
    force_headful: bool = True


@dataclass
class PublishResult:
    """
    Kết quả trả về chuẩn từ mọi platform publish.
    Dù publish TikTok hay YouTube, use case luôn nhận kiểu dữ liệu này.
    """
    success: bool
    platform: str
    external_url: Optional[str] = None
    external_video_id: Optional[str] = None
    error_message: Optional[str] = None


class SocialPublisher(ABC):
    """
    Abstract Adapter — interface chuẩn cho tất cả nền tảng mạng xã hội.

    Quy tắc implement:
    - Khi thành công: trả về PublishResult(success=True, external_url=...)
    - Khi thất bại: KHÔNG raise exception, trả về PublishResult(success=False, error_message=...)
    - Mọi log nên dùng prefix [ClassName] để dễ trace
    """

    def __init__(self, profile_dir: str):
        self.profile_dir = profile_dir

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Tên platform (vd: 'tiktok', 'youtube'). Dùng trong log và DB."""
        ...

    @abstractmethod
    def publish(self, video_path: str, payload: PublishPayload) -> PublishResult:
        """
        Thực thi đăng tải video lên nền tảng.

        Args:
            video_path: Đường dẫn tuyệt đối tới file video .mp4
            payload:    Metadata đầy đủ (title, hashtags, proxy, ...)

        Returns:
            PublishResult với success=True/False và thông tin bổ sung.
        """
        ...
