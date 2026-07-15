"""
Music Reactive Render Strategy
================================
Xử lý render video Music Reactive và Music Remix Reactive.
Di chuyển từ handle_music_reactive_render() trong render_use_case.py cũ.
"""
from __future__ import annotations

import json

from worker.application.render_strategies.base import RenderStrategy
from worker.domain.render_contract import RenderContract, RenderMode
from worker.infrastructure.database import get_db_connection, log_realtime_progress
from worker.infrastructure.repositories import VideoJobRepository
from worker.domain.job_metadata import parse_job_metadata


class MusicReactiveStrategy(RenderStrategy):
    """
    Strategy cho video Music Reactive (phân tích FFT / audio reactive).
    Áp dụng khi: render_mode = MUSIC_REACTIVE hoặc MUSIC_REMIX_REACTIVE.
    """

    def can_handle(self, contract: RenderContract) -> bool:
        return contract.is_music_reactive

    async def execute(self, job: dict, contract: RenderContract) -> str:
        job_id = contract.job_id
        metadata = parse_job_metadata(job)
        repo = VideoJobRepository()

        def _update_state(state: str, message: str):
            repo.update_state(job_id, state)
            log_realtime_progress(job_id, state, "INFO", message)

        _update_state("SIGNAL_PROCESSING",
                      "Bắt đầu phân tích FFT/audio-reactive data cho video music reactive...")

        from worker.services.music_reactive_service import MusicReactiveService
        service = MusicReactiveService()

        try:
            result = service.render_music_reactive_video(
                job=job, metadata=metadata, job_id=job_id, progress=_update_state
            )
        except RuntimeError as first_error:
            if "blackout frame" not in str(first_error).lower():
                raise
            log_realtime_progress(job_id, "QUALITY_CHECK", "WARN",
                                  f"Phát hiện blackout frame: {first_error}. Thử lại với background fallback...")
            metadata.pop("background_video_path", None)
            result = service.render_music_reactive_video(
                job=job, metadata=metadata, job_id=job_id, progress=_update_state
            )

        # Lưu kết quả
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE video_pipeline_jobs
                    SET video_output_path = %s, scenes_layout_json = %s,
                        pipeline_state = 'RENDERED_SUBTITLED', error_log_trace = NULL
                    WHERE id = %s
                    """,
                    (result["video_path"], json.dumps(result["metadata"], ensure_ascii=False), job_id),
                )
        finally:
            conn.close()

        log_realtime_progress(job_id, "QUALITY_CHECK", "SUCCESS",
                              f"Music reactive video đã render xong: {result['video_path']}")
        return result["video_path"]
