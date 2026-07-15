"""
Publish Target Repository — Repository Pattern
===============================================
Tập trung toàn bộ truy vấn SQL liên quan đến bảng publish_targets.
"""
from __future__ import annotations

from typing import Optional

from worker.infrastructure.database import get_db_connection


class PublishTargetRepository:
    """
    Repository pattern cho bảng publish_targets.
    Mọi trạng thái publish được ghi qua đây, không viết SQL trực tiếp trong use case.
    """

    def find_by_id(self, target_id: int) -> Optional[dict]:
        """Lấy thông tin 1 publish target theo ID."""
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT * FROM publish_targets WHERE id = %s LIMIT 1",
                    (target_id,),
                )
                return cursor.fetchone()
        finally:
            conn.close()

    def find_by_job_id(self, job_id: int) -> Optional[dict]:
        """Lấy publish target mặc định của 1 job (lấy bản ghi đầu tiên)."""
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT platform_connection_id, platform FROM publish_targets WHERE job_id = %s LIMIT 1",
                    (job_id,),
                )
                return cursor.fetchone()
        finally:
            conn.close()

    def find_detail_by_id(self, target_id: int) -> Optional[dict]:
        """Lấy title/description/tags của 1 publish target (dùng cho ghi đè SEO)."""
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT title, description, tags FROM publish_targets WHERE id = %s",
                    (target_id,),
                )
                return cursor.fetchone()
        finally:
            conn.close()

    # ── State transitions ──────────────────────────────────────────────────────

    def mark_publishing(self, target_id: int) -> None:
        """Đánh dấu target đang trong quá trình đăng bài."""
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE publish_targets SET status = 'PUBLISHING', error_log = NULL WHERE id = %s",
                    (target_id,),
                )
        finally:
            conn.close()

    def mark_published(
        self,
        target_id: int,
        external_url: Optional[str] = None,
        external_video_id: Optional[str] = None,
    ) -> None:
        """Đánh dấu target đã publish thành công, lưu URL và video ID nếu có."""
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE publish_targets
                    SET status = 'PUBLISHED', external_url = %s,
                        external_video_id = %s, error_log = NULL
                    WHERE id = %s
                    """,
                    (external_url, external_video_id, target_id),
                )
        finally:
            conn.close()

    def mark_published_by_job(
        self,
        job_id: int,
        platform: str,
        platform_connection_id: int,
        external_url: Optional[str] = None,
        external_video_id: Optional[str] = None,
    ) -> None:
        """Đánh dấu published cho target của 1 job (khi không có target_id cụ thể)."""
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE publish_targets
                    SET status = 'PUBLISHED', external_url = %s,
                        external_video_id = %s, error_log = NULL
                    WHERE job_id = %s AND platform = %s AND platform_connection_id = %s
                    """,
                    (external_url, external_video_id, job_id, platform, platform_connection_id),
                )
        finally:
            conn.close()

    def mark_failed(
        self,
        error_message: str,
        target_id: Optional[int] = None,
        job_id: Optional[int] = None,
        platform: Optional[str] = None,
        platform_connection_id: Optional[int] = None,
    ) -> None:
        """Đánh dấu target thất bại và lưu thông điệp lỗi."""
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                if target_id:
                    cursor.execute(
                        """
                        UPDATE publish_targets
                        SET status = 'FAILED', error_log = %s, updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                        """,
                        (error_message, target_id),
                    )
                elif job_id and platform and platform_connection_id:
                    cursor.execute(
                        """
                        UPDATE publish_targets
                        SET status = 'FAILED', error_log = %s, updated_at = CURRENT_TIMESTAMP
                        WHERE job_id = %s AND platform = %s AND platform_connection_id = %s
                        """,
                        (error_message, job_id, platform, platform_connection_id),
                    )
        finally:
            conn.close()
