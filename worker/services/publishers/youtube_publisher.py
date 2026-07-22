"""
YouTube Publisher Adapter
==========================
Wrap YouTubeStudioPublisherService.publish_video_to_youtube_studio()
theo interface SocialPublisher chuẩn.
Toàn bộ logic Playwright YouTube giữ nguyên trong YouTubeStudioPublisherService gốc.
"""
from __future__ import annotations

from worker.services.publishers.base import SocialPublisher, PublishPayload, PublishResult
from worker.services.publisher_service import YouTubeStudioPublisherService


class YouTubePublisher(SocialPublisher):
    """
    Adapter cho YouTube Studio — sử dụng Playwright Stealth.
    Delegate toàn bộ automation logic sang YouTubeStudioPublisherService gốc.
    Ngoài ra xử lý trích xuất video ID từ URL trả về.
    """

    @property
    def platform_name(self) -> str:
        return "youtube"

    def publish(self, video_path: str, payload: PublishPayload) -> PublishResult:
        print(f"[YouTubePublisher] Bắt đầu đăng YouTube Shorts: {payload.title[:80]}")
        if payload.scheduled_at:
            print(f"[YouTubePublisher] Schedule mode: {payload.scheduled_at}")

        try:
            service = YouTubeStudioPublisherService(profile_dir=self.profile_dir)
            video_url = service.publish_video_to_youtube_studio(
                video_path=video_path,
                title=payload.title,
                description=payload.description,
                tags=payload.tags,
                proxy_ip=payload.proxy_ip,
                proxy_port=payload.proxy_port,
                proxy_user=payload.proxy_user,
                proxy_pass=payload.proxy_pass,
                headless=payload.headless,
                scheduled_at=payload.scheduled_at,
            )

            if not video_url:
                return PublishResult(
                    success=False,
                    platform=self.platform_name,
                    error_message="YouTube Studio không trả về link video sau khi đăng.",
                )

            video_id = self._extract_video_id(video_url)
            print(f"[YouTubePublisher] ✅ Đăng YouTube thành công! URL: {video_url}")
            return PublishResult(
                success=True,
                platform=self.platform_name,
                external_url=video_url,
                external_video_id=video_id,
            )

        except Exception as e:
            print(f"[YouTubePublisher] ❌ Lỗi: {e}")
            return PublishResult(
                success=False,
                platform=self.platform_name,
                error_message=str(e),
            )

    # ──────────────────────────────────────────────────────────────────────────
    # Private helpers
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_video_id(url: str) -> str | None:
        """Trích xuất YouTube video ID từ các định dạng URL khác nhau."""
        if "/shorts/" in url:
            return url.split("/shorts/")[-1].split("?")[0]
        if "v=" in url:
            return url.split("v=")[-1].split("&")[0]
        if "youtu.be/" in url:
            return url.split("youtu.be/")[-1].split("?")[0]
        return None
