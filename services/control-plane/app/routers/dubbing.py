"""
Dubbing Router — Phiên bản PostgreSQL thuần
=============================================
Đã bỏ hoàn toàn pymysql / MySQL. Tất cả dữ liệu
được lưu vào PostgreSQL (Control Plane DB) thông qua
SQLAlchemy, cùng pattern với workflows.py.

Luồng:
  POST /dubbing/dispatch
    → Tạo VideoProject + WorkflowRun (state=RENDERING)
    → Ghi DubbingJob vào workflow_runs.input_payload (thay thế video_pipeline_jobs MySQL)
    → Trả về workflow_run_id làm job_id
  GET /dubbing/status/{workflow_run_id}
    → Đọc WorkflowRun.state + WorkflowStep logs từ PostgreSQL
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.database import get_session
from app.infrastructure.models import MediaAsset, Organization, VideoProject, WorkflowRun, WorkflowStep

router = APIRouter(tags=["Dubbing"])


class DubbingDispatchRequest(BaseModel):
    source_url: Optional[str] = None
    file_path: Optional[str] = None
    voice_code: str = "edge-nam-minh"
    target_language: str = "auto"
    voice_gender: str = "female"
    aspect_ratio: str = "vertical_blur"
    burn_subtitles: bool = True
    blur_original_subtitles: bool = True
    blur_region_height_ratio: float = 0.20
    logo_handle: str = "@GocChiemNghiemYuuBin"
    caption_preset: str = "montserrat"
    mute_original_audio: bool = False
    auto_publish_enabled: bool = False
    auto_publish_channel: str = "goc_chiem_nghiem"
    auto_publish_mode: str = "immediate"
    scheduled_at_iso: Optional[str] = None
    organization_id: Optional[str] = None   # optional — mặc định dùng org đầu tiên


@router.post("/dubbing/dispatch", status_code=status.HTTP_201_CREATED)
def dispatch_dubbing_job(
    payload: DubbingDispatchRequest,
    session: Session = Depends(get_session),
):
    """
    Đăng ký công việc Lồng Tiếng & Vietsub Tự Động (AI Dubbing Job).
    Lưu toàn bộ vào PostgreSQL. Không cần MySQL.
    """
    if not payload.source_url and not payload.file_path:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Vui lòng cung cấp đường dẫn link video (source_url) hoặc đường dẫn tệp tải lên (file_path).",
        )

    # Lấy Organization
    if payload.organization_id:
        org = session.get(Organization, uuid.UUID(payload.organization_id))
    else:
        org = session.scalars(select(Organization)).first()

    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy Organization.")

    metadata = {
        "dub_source_url": payload.source_url,
        "dub_source_path": payload.file_path,
        "voice_code": payload.voice_code,
        "target_language": payload.target_language,
        "voice_gender": payload.voice_gender,
        "aspect_ratio": payload.aspect_ratio,
        "burn_subtitles": payload.burn_subtitles,
        "blur_original_subtitles": payload.blur_original_subtitles,
        "blur_region_height_ratio": payload.blur_region_height_ratio,
        "logo_handle": payload.logo_handle,
        "caption_preset": payload.caption_preset,
        "mute_original_audio": payload.mute_original_audio,
        "auto_publish_enabled": payload.auto_publish_enabled,
        "auto_publish_channel": payload.auto_publish_channel,
        "auto_publish_mode": payload.auto_publish_mode,
        "scheduled_at_iso": payload.scheduled_at_iso,
        "render_mode": "TRANSLATE_DUB",
    }

    clean_title = f"[DUB] {payload.source_url or payload.file_path or 'Video Lồng Tiếng Tự Động'}"[:240]

    # Tạo VideoProject + WorkflowRun trong PostgreSQL
    proj = VideoProject(
        organization_id=org.id,
        title=clean_title,
        brief=payload.source_url or payload.file_path or "AI Dubbing Video",
        format_profile="short_vertical",
        timezone="Asia/Bangkok",
    )
    session.add(proj)
    session.flush()

    workflow_run_id = uuid.uuid4()
    wf = WorkflowRun(
        id=workflow_run_id,
        project_id=proj.id,
        state="RENDERING",
        idempotency_key=f"dub-{uuid.uuid4().hex}",
        prompt_manifest=metadata,
        input_payload=metadata,
    )
    session.add(wf)
    session.flush()
    session.commit()

    return {
        "job_id": str(workflow_run_id),
        "workflow_run_id": str(workflow_run_id),
        "status": "queued",
        "message": "Đã khởi tạo công việc lồng tiếng tự động thành công!",
        "metadata": metadata,
    }


@router.get("/dubbing/status/{job_id}")
def get_dubbing_job_status(
    job_id: str,
    session: Session = Depends(get_session),
):
    """
    Kiểm tra trạng thái & log tiến trình lồng tiếng AI.
    job_id là WorkflowRun UUID (từ PostgreSQL).
    """
    # Thử parse UUID
    try:
        wf_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="job_id không hợp lệ (cần UUID)")

    wf = session.get(WorkflowRun, wf_uuid)
    if not wf:
        raise HTTPException(status_code=404, detail="Không tìm thấy công việc lồng tiếng này.")

    # Đọc WorkflowStep logs (các bước render)
    steps = session.scalars(
        select(WorkflowStep).where(WorkflowStep.workflow_run_id == wf_uuid)
    ).all()

    logs = [
        {
            "module_name": s.step_key,
            "log_level": s.state,
            "message": str(s.output_payload) if s.output_payload else "",
        }
        for s in steps
    ]

    # Lấy R2 object key nếu đã render xong
    asset = session.scalars(
        select(MediaAsset).where(
            MediaAsset.workflow_run_id == wf_uuid,
            MediaAsset.media_kind == "final_export",
        )
    ).first()

    return {
        "job_id": str(wf.id),
        "workflow_run_id": str(wf.id),
        "state": wf.state,
        "output_path": asset.object_key if asset else None,
        "error": wf.failure_detail,
        "logs": logs,
    }
