"""
Dubbing Bridge — Worker → Control Plane
========================================
Được gọi từ DubbingStrategy (worker) sau khi render xong để:
  - Cập nhật WorkflowRun.state → APPROVAL_PENDING
  - Ghi MediaAsset (R2 key) vào PostgreSQL
  - Video xuất hiện trong Review Queue / Control Tower

NOTE: Từ khi dubbing.py được viết lại dùng PostgreSQL trực tiếp,
workflow_run_id UUID có sẵn trong input_payload.
Bridge này tìm WorkflowRun qua trường legacy_job_id để cập nhật.
"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Optional

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from app.infrastructure.models import MediaAsset, Organization, VideoProject, WorkflowRun

_log = logging.getLogger(__name__)


def sync_dubbing_job_to_control_plane(
    job_id: int,
    title: str,
    metadata: dict,
    state: str = "APPROVAL_PENDING",
    r2_object_key: Optional[str] = None,
    byte_size: int = 0,
    workflow_run_id: Optional[str] = None,
) -> str:
    """
    Cập nhật WorkflowRun trong PostgreSQL sau khi Worker render xong.

    Ưu tiên tìm theo workflow_run_id (UUID) nếu có;
    fallback sang legacy_job_id = 'dub-<job_id>' nếu được tạo từ MySQL bridge cũ.
    Nếu không tìm thấy, tự tạo mới (backward compat).
    """
    db_url = os.getenv("DATABASE_URL") or os.getenv("VISIONFLOW_DATABASE_URL")
    if not db_url:
        _log.warning("[dubbing_bridge] DATABASE_URL not set, skipping sync.")
        return ""

    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+psycopg://", 1)

    try:
        from app.infrastructure.database import get_engine
        engine = get_engine()
    except Exception:
        engine = create_engine(db_url)

    with Session(engine) as session:
        # 1. Tìm WorkflowRun
        wf = None
        if workflow_run_id:
            try:
                wf = session.get(WorkflowRun, uuid.UUID(workflow_run_id))
            except (ValueError, Exception):
                pass

        if not wf:
            legacy_key = f"dub-{job_id}"
            wf = session.scalars(
                select(WorkflowRun).where(WorkflowRun.legacy_job_id == legacy_key)
            ).first()

        if not wf:
            # Tạo mới (backward compat với job được tạo từ MySQL)
            org = session.scalars(select(Organization)).first()
            if not org:
                _log.error("[dubbing_bridge] No Organization found, cannot create WorkflowRun.")
                return ""

            clean_title = (title or "Video Lồng Tiếng AI")[:240]
            proj = VideoProject(
                organization_id=org.id,
                title=clean_title,
                brief=metadata.get("dub_source_url") or "AI Dubbing Video",
                format_profile="short_vertical",
                timezone="Asia/Bangkok",
            )
            session.add(proj)
            session.flush()

            wf = WorkflowRun(
                id=uuid.uuid4(),
                project_id=proj.id,
                state=state,
                idempotency_key=f"dub-idem-{job_id}-{uuid.uuid4().hex[:6]}",
                legacy_job_id=f"dub-{job_id}",
                prompt_manifest=metadata,
                input_payload=metadata,
            )
            session.add(wf)
            session.flush()
        else:
            # Cập nhật state & tiêu đề bài viết & mô tả SEO tự động sinh
            wf.state = state
            seo_data = metadata.get("seo") or {}
            ai_title = seo_data.get("title") or title
            ai_caption = seo_data.get("caption_seo") or metadata.get("hook") or ""

            if ai_title and hasattr(wf, "project") and wf.project:
                wf.project.title = str(ai_title)[:240]
                if ai_caption:
                    wf.project.brief = str(ai_caption)[:500]
            wf.prompt_manifest = {**(wf.prompt_manifest or {}), **metadata}

        # 2. Ghi MediaAsset nếu có R2 key
        if r2_object_key:
            # Tìm theo workflow_run_id hoặc object_key (tránh unique violation)
            asset = session.scalars(
                select(MediaAsset).where(
                    (MediaAsset.workflow_run_id == wf.id)
                    | (MediaAsset.object_key == r2_object_key)
                )
            ).first()

            org_id = session.scalar(
                select(VideoProject.organization_id).where(VideoProject.id == wf.project_id)
            )

            if not asset:
                asset = MediaAsset(
                    organization_id=org_id,
                    workflow_run_id=wf.id,
                    object_key=r2_object_key,
                    media_kind="final_export",
                    content_type="video/mp4",
                    byte_size=byte_size or 1048576,
                    checksum_sha256="0" * 64,
                    metadata_json={"source": "dubbing_strategy"},
                )
                session.add(asset)
            else:
                asset.workflow_run_id = wf.id
                asset.object_key = r2_object_key
                if byte_size:
                    asset.byte_size = byte_size

        session.commit()
        _log.info("[dubbing_bridge] Synced job_id=%s → workflow_run_id=%s state=%s", job_id, wf.id, state)
        return str(wf.id)
