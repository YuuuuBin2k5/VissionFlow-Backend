from __future__ import annotations

import logging
from typing import Any, Dict, Optional
import requests

logger = logging.getLogger(__name__)

TIKTOK_API_BASE = "https://open.tiktokapis.com"
TIKTOK_AUTH_BASE = "https://www.tiktok.com"


class TikTokApiException(Exception):
    def __init__(self, message: str, error_code: Optional[str] = None, status_code: Optional[int] = None):
        super().__init__(message)
        self.error_code = error_code
        self.status_code = status_code


class TikTokApiClient:
    """
    Client chuẩn hóa tích hợp TikTok Content Posting API v2 (Cách 1).
    Hỗ trợ:
      - OAuth 2.0 Token Exchange & Refresh
      - User Profile & Channel Info
      - Query Creator Capabilities
      - Direct Post (Đăng trực tiếp lên profile)
      - Share to Draft / Inbox (Gửi vào bản nháp trên app TikTok)
      - Status Polling
    """

    def __init__(self, timeout: int = 25):
        self.timeout = timeout

    def exchange_authorization_code(
        self,
        code: str,
        client_key: str,
        client_secret: str,
        redirect_uri: str,
    ) -> Dict[str, Any]:
        """Đổi authorization code lấy access_token và refresh_token."""
        url = f"{TIKTOK_API_BASE}/v2/oauth/token/"
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        data = {
            "client_key": client_key,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }

        try:
            resp = requests.post(url, headers=headers, data=data, timeout=self.timeout)
            payload = resp.json()
        except Exception as exc:
            raise TikTokApiException(f"Lỗi kết nối TikTok OAuth token exchange: {exc!s}") from exc

        if resp.status_code != 200 or payload.get("error", {}).get("code") != "ok":
            err_msg = payload.get("error", {}).get("message") or resp.text
            err_code = payload.get("error", {}).get("code")
            raise TikTokApiException(f"TikTok token exchange failed: {err_msg}", error_code=err_code, status_code=resp.status_code)

        return payload.get("data", {})

    def refresh_access_token(
        self,
        refresh_token: str,
        client_key: str,
        client_secret: str,
    ) -> Dict[str, Any]:
        """Làm mới access token khi hết hạn."""
        url = f"{TIKTOK_API_BASE}/v2/oauth/token/"
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        data = {
            "client_key": client_key,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }

        try:
            resp = requests.post(url, headers=headers, data=data, timeout=self.timeout)
            payload = resp.json()
        except Exception as exc:
            raise TikTokApiException(f"Lỗi kết nối refresh token TikTok: {exc!s}") from exc

        if resp.status_code != 200 or payload.get("error", {}).get("code") != "ok":
            err_msg = payload.get("error", {}).get("message") or resp.text
            raise TikTokApiException(f"TikTok refresh token failed: {err_msg}", status_code=resp.status_code)

        return payload.get("data", {})

    def get_user_info(self, access_token: str) -> Dict[str, Any]:
        """Lấy thông tin profile người dùng TikTok (open_id, display_name, avatar_url)."""
        url = f"{TIKTOK_API_BASE}/v2/user/info/?fields=open_id,union_id,avatar_url,display_name,username"
        headers = {"Authorization": f"Bearer {access_token}"}

        try:
            resp = requests.get(url, headers=headers, timeout=self.timeout)
            payload = resp.json()
        except Exception as exc:
            raise TikTokApiException(f"Lỗi gọi TikTok user info: {exc!s}") from exc

        if resp.status_code != 200 or payload.get("error", {}).get("code") != "ok":
            err_msg = payload.get("error", {}).get("message") or resp.text
            raise TikTokApiException(f"TikTok user info failed: {err_msg}", status_code=resp.status_code)

        return payload.get("data", {}).get("user", {})

    def query_creator_info(self, access_token: str) -> Dict[str, Any]:
        """Kiểm tra quyền hạn và cài đặt của creator trên TikTok."""
        url = f"{TIKTOK_API_BASE}/v2/post/publish/creator_info/query/"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        }

        try:
            resp = requests.post(url, headers=headers, json={}, timeout=self.timeout)
            payload = resp.json()
        except Exception as exc:
            logger.warning("Không thể query creator info từ TikTok: %s", exc)
            return {}

        return payload.get("data", {})

    def init_video_publish(
        self,
        access_token: str,
        video_url: str,
        title: str,
        post_mode: str = "DIRECT_POST",
        privacy_level: str = "PUBLIC_TO_EVERYONE",
        disable_comment: bool = False,
        disable_duet: bool = False,
        disable_stitch: bool = False,
        is_aigc: bool = True,
    ) -> Dict[str, Any]:
        """
        Khởi tạo đăng video lên TikTok qua URL (PULL_FROM_URL).
        Hỗ trợ:
          - post_mode = 'DIRECT_POST': Đăng trực tiếp lên hồ sơ kênh
          - post_mode = 'SHARE_TO_DRAFT': Đưa video vào hòm thư Bản nháp trên app TikTok
        """
        if post_mode.upper() == "SHARE_TO_DRAFT":
            endpoint = f"{TIKTOK_API_BASE}/v2/post/publish/inbox/video/init/"
        else:
            endpoint = f"{TIKTOK_API_BASE}/v2/post/publish/video/init/"

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        }

        post_info = {
            "title": title[:2200],  # TikTok caption limit
            "privacy_level": privacy_level,
            "disable_comment": disable_comment,
            "disable_duet": disable_duet,
            "disable_stitch": disable_stitch,
            "is_aigc": is_aigc,
            "brand_content_toggle": False,
            "brand_organic_toggle": False,
        }

        source_info = {
            "source": "PULL_FROM_URL",
            "video_url": video_url,
        }

        payload = {
            "post_info": post_info,
            "source_info": source_info,
        }

        try:
            resp = requests.post(endpoint, headers=headers, json=payload, timeout=self.timeout)
            data = resp.json()
        except Exception as exc:
            raise TikTokApiException(f"Lỗi khởi tạo đăng TikTok video: {exc!s}") from exc

        if resp.status_code != 200 or data.get("error", {}).get("code") != "ok":
            err_msg = data.get("error", {}).get("message") or resp.text
            err_code = data.get("error", {}).get("code")
            raise TikTokApiException(f"TikTok publish init failed: {err_msg}", error_code=err_code, status_code=resp.status_code)

        return data.get("data", {})

    def fetch_publish_status(self, access_token: str, publish_id: str) -> Dict[str, Any]:
        """Kiểm tra tiến độ xuất bản video theo publish_id."""
        url = f"{TIKTOK_API_BASE}/v2/post/publish/status/fetch/"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        }

        try:
            resp = requests.post(url, headers=headers, json={"publish_id": publish_id}, timeout=self.timeout)
            data = resp.json()
        except Exception as exc:
            raise TikTokApiException(f"Lỗi truy vấn trạng thái xuất bản TikTok: {exc!s}") from exc

        return data.get("data", {})
