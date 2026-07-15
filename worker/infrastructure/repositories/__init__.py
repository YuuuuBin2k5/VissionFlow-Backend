"""
Infrastructure Repositories Package
=====================================
Xuất các Repository classes để sử dụng trong application layer.

Cách dùng đúng:
    from worker.infrastructure.repositories import VideoJobRepository
    repo = VideoJobRepository()
    job = repo.find_by_id(job_id)   # Không viết SQL ở use case
"""
from worker.infrastructure.repositories.video_job_repository import VideoJobRepository
from worker.infrastructure.repositories.publish_target_repository import PublishTargetRepository

__all__ = ["VideoJobRepository", "PublishTargetRepository"]
