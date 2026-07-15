"""
Video Job Repository — Repository Pattern
==========================================
Tập trung toàn bộ truy vấn SQL liên quan đến bảng video_pipeline_jobs.
Use case và Application layer KHÔNG được viết SQL trực tiếp.
"""
from __future__ import annotations

import json
from typing import Optional

from worker.infrastructure.database import get_db_connection


class VideoJobRepository:
    """
    Repository pattern cho bảng video_pipeline_jobs.

    Lợi ích:
    - Use case code chỉ gọi method có tên rõ nghĩa, không biết SQL tồn tại
    - Thay đổi schema DB chỉ cần sửa file này, không đụng application layer
    - Dễ mock trong unit test (chỉ cần mock class này)
    """

    # ── Read operations ────────────────────────────────────────────────────────

    def find_by_id(self, job_id: int) -> Optional[dict]:
        """Lấy toàn bộ thông tin 1 job kèm campaign topic/audience."""
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT j.*, c.topic, c.target_audience
                    FROM video_pipeline_jobs j
                    LEFT JOIN channels_campaign c ON j.campaign_id = c.id
                    WHERE j.id = %s
                    """,
                    (job_id,),
                )
                return cursor.fetchone()
        finally:
            conn.close()

    # ── State transitions ──────────────────────────────────────────────────────

    def update_state(self, job_id: int, state: str, error_trace: Optional[str] = None) -> None:
        """Cập nhật pipeline_state. Nếu có error_trace thì ghi luôn vào error_log_trace."""
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                if error_trace is not None:
                    cursor.execute(
                        "UPDATE video_pipeline_jobs SET pipeline_state = %s, error_log_trace = %s WHERE id = %s",
                        (state, error_trace, job_id),
                    )
                else:
                    cursor.execute(
                        "UPDATE video_pipeline_jobs SET pipeline_state = %s WHERE id = %s",
                        (state, job_id),
                    )
        finally:
            conn.close()

    def clear_error_and_set_state(self, job_id: int, state: str) -> None:
        """Xoá lỗi cũ và đặt trạng thái mới (dùng khi bắt đầu render lại)."""
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE video_pipeline_jobs SET pipeline_state = %s, error_log_trace = NULL WHERE id = %s",
                    (state, job_id),
                )
        finally:
            conn.close()

    # ── Script / Script result ─────────────────────────────────────────────────

    def save_script_result(
        self,
        job_id: int,
        hook: str,
        full_script: str,
        scenes_layout_json: dict | list,
        seo_tags: dict,
    ) -> None:
        """Lưu kết quả LLM script generation sau bước B2."""
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE video_pipeline_jobs
                    SET hook_text_3s = %s, full_voice_script = %s,
                        scenes_layout_json = %s, seo_tags_metadata = %s,
                        pipeline_state = 'AI_PARSED'
                    WHERE id = %s
                    """,
                    (
                        hook,
                        full_script,
                        json.dumps(scenes_layout_json, ensure_ascii=False),
                        json.dumps(seo_tags, ensure_ascii=False),
                        job_id,
                    ),
                )
        finally:
            conn.close()

    def save_audio_path(self, job_id: int, audio_path: str) -> None:
        """Lưu đường dẫn file audio sau bước TTS."""
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE video_pipeline_jobs SET audio_file_path = %s, pipeline_state = 'AUDIO_COMPOSED' WHERE id = %s",
                    (audio_path, job_id),
                )
        finally:
            conn.close()

    def mark_assets_ready(self, job_id: int) -> None:
        """Đánh dấu đã tải đủ asset video nền."""
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE video_pipeline_jobs SET pipeline_state = 'ASSETS_READY' WHERE id = %s",
                    (job_id,),
                )
        finally:
            conn.close()

    # ── Final render result ────────────────────────────────────────────────────

    def save_render_result(
        self,
        job_id: int,
        video_output_path: str,
        seo_tags: dict,
    ) -> None:
        """Lưu đường dẫn video đầu ra sau khi render thành công."""
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE video_pipeline_jobs
                    SET video_output_path = %s, seo_tags_metadata = %s,
                        pipeline_state = 'RENDERED_SUBTITLED'
                    WHERE id = %s
                    """,
                    (
                        video_output_path,
                        json.dumps(seo_tags, ensure_ascii=False),
                        job_id,
                    ),
                )
        finally:
            conn.close()

    def save_published(self, job_id: int) -> None:
        """Đánh dấu job đã được publish thành công."""
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE video_pipeline_jobs SET pipeline_state = 'PUBLISHED' WHERE id = %s",
                    (job_id,),
                )
        finally:
            conn.close()
