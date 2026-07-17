"""
TikTok Publisher Adapter
=========================
Wrap PublisherService.publish_video_to_tiktok() theo interface SocialPublisher chuẩn.
Toàn bộ logic Playwright TikTok giữ nguyên trong PublisherService gốc.
"""
from __future__ import annotations

from worker.services.publishers.base import SocialPublisher, PublishPayload, PublishResult
from worker.services.publisher_service import PublisherService


class TikTokPublisher(SocialPublisher):
    """
    Adapter cho TikTok Studio — sử dụng Playwright Stealth.
    Delegate toàn bộ automation logic sang PublisherService gốc.
    """

    @property
    def platform_name(self) -> str:
        return "tiktok"

    def publish(self, video_path: str, payload: PublishPayload) -> PublishResult:
        print(f"[TikTokPublisher] Bắt đầu đăng bài TikTok: {payload.title[:80]}")

        try:
            service = PublisherService(profile_dir=self.profile_dir)
            success = service.publish_video_to_tiktok(
                video_path=video_path,
                caption=payload.title,
                hashtags=payload.hashtags,
                force_headful=payload.force_headful,
                music_metadata=payload.music_metadata,
                comment_text=payload.comment_text,
                proxy_ip=payload.proxy_ip,
                proxy_port=payload.proxy_port,
                proxy_user=payload.proxy_user,
                proxy_pass=payload.proxy_pass,
            )

            if success:
                print(f"[TikTokPublisher] ✅ Đăng TikTok thành công!")
                return PublishResult(success=True, platform=self.platform_name)
            else:
                return PublishResult(
                    success=False,
                    platform=self.platform_name,
                    error_message="Playwright tự động đăng video không thành công.",
                )

        except Exception as e:
            print(f"[TikTokPublisher] ❌ Lỗi: {e}")
            return PublishResult(
                success=False,
                platform=self.platform_name,
                error_message=str(e),
            )
