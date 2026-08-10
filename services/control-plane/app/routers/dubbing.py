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
    logo_handle: str = "GócChiêmNghiệm||YuuuBin"
    caption_preset: str = "montserrat"
    mute_original_audio: bool = False
    auto_publish_enabled: bool = False
    auto_publish_channel: str = "goc_chiem_nghiem"
    auto_publish_mode: str = "immediate"
    scheduled_at_iso: Optional[str] = None
    organization_id: Optional[str] = None   # optional — mặc định dùng org đầu tiên
    storytelling_framework: Optional[str] = "mid_action_open"
    enable_word_karaoke: bool = True
    bgm_preset: Optional[str] = "relaxing_chill"
    bgm_custom_url: Optional[str] = None
    bgm_volume: float = 0.18
    enable_bgm: bool = True
    enable_audio_ducking: bool = True
    enable_bgm_fade: bool = True
    smart_dynamic_blur: bool = True
    vocal_removal_mode: Optional[str] = "ffmpeg_phase_cancel"
    blur_original_logo: bool = True


DubbingDispatchRequest.model_rebuild()


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

    # Handshake session parameter
    if not hasattr(session, "scalars"):
        try:
            from app.infrastructure.database import get_engine
            session = Session(get_engine())
        except Exception:
            session = None

    org = None
    if session and hasattr(session, "scalars"):
        if payload.organization_id:
            org = session.get(Organization, uuid.UUID(payload.organization_id))
        else:
            org = session.scalars(select(Organization)).first()

    org_id = org.id if org else uuid.uuid4()

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
        "storytelling_framework": payload.storytelling_framework,
        "enable_word_karaoke": payload.enable_word_karaoke,
        "bgm_preset": payload.bgm_preset,
        "bgm_custom_url": payload.bgm_custom_url,
        "bgm_volume": payload.bgm_volume,
        "enable_bgm": payload.enable_bgm,
        "enable_audio_ducking": payload.enable_audio_ducking,
        "enable_bgm_fade": payload.enable_bgm_fade,
        "smart_dynamic_blur": payload.smart_dynamic_blur,
        "vocal_removal_mode": payload.vocal_removal_mode,
        "blur_original_logo": payload.blur_original_logo,
        "render_mode": "TRANSLATE_DUB",
    }

    lang_tag = (payload.target_language or "vi").upper()
    if lang_tag == "AUTO":
        lang_tag = "VI"

    display_name = payload.file_path or "Video Lồng Tiếng Tự Động"
    if payload.source_url:
        if "douyin.com" in payload.source_url.lower():
            display_name = "Video Douyin Lồng Tiếng"
        elif "tiktok.com" in payload.source_url.lower():
            display_name = "Video TikTok Lồng Tiếng"
        elif "youtube.com" in payload.source_url.lower() or "youtu.be" in payload.source_url.lower():
            display_name = "Video YouTube Lồng Tiếng"
        else:
            display_name = "Video Lồng Tiếng AI"
    clean_title = f"[{lang_tag}-DUB] {display_name}"

    workflow_run_id = uuid.uuid4()
    metadata["workflow_run_id"] = str(workflow_run_id)

    # Tạo VideoProject + WorkflowRun trong PostgreSQL
    if session and hasattr(session, "add"):
        proj = VideoProject(
            organization_id=org_id,
            title=clean_title,
            brief=payload.source_url or payload.file_path or "AI Dubbing Video",
            format_profile="short_vertical",
            timezone="Asia/Bangkok",
        )
        session.add(proj)
        session.flush()

        wf = WorkflowRun(
            id=workflow_run_id,
            project_id=proj.id,
            state="QUEUED",   # process_queued_jobs.py sẽ pick up và chạy DubbingStrategy
            idempotency_key=f"dub-{uuid.uuid4().hex}",
            legacy_job_id=f"dub-{workflow_run_id}",
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

    download_url = None
    if asset:
        try:
            from worker.services.visionflow_object_storage import S3CompatibleObjectStorage, VisionFlowObjectStorageSettings
            storage = S3CompatibleObjectStorage(VisionFlowObjectStorageSettings.from_env())
            download_url = storage.generate_presigned_download_url(asset.object_key, expires_in_seconds=3600)
        except Exception:
            pass

    manifest = wf.prompt_manifest or {}
    seo_metadata = manifest.get("seo") or {}
    proj = session.get(VideoProject, wf.project_id) if wf.project_id else getattr(wf, "project", None)
    
    raw_proj_title = proj.title if proj else None
    ai_generated_title = seo_metadata.get("title")
    
    if ai_generated_title:
        video_title = ai_generated_title
    elif raw_proj_title and not any(kw in raw_proj_title for kw in ["Video Douyin", "Video TikTok", "Video YouTube", "Lồng Tiếng Tự Động", "Lồng Tiếng AI"]):
        video_title = raw_proj_title
    else:
        video_title = raw_proj_title or "Video Lồng Tiếng AI Mới"

    channel_key = manifest.get("auto_publish_channel") or "goc_chiem_nghiem"
    raw_summary = seo_metadata.get("caption_seo") or (proj.brief if proj else "")
    video_hashtags = seo_metadata.get("hashtags") or ["#VisionFlow", "#AIDubbing", "#YuuBin"]

    from worker.services.video_metadata_strategy import format_channel_description
    video_description = format_channel_description(raw_summary, channel_key=channel_key, hashtags=video_hashtags)

    return {
        "job_id": str(wf.id),
        "workflow_run_id": str(wf.id),
        "state": wf.state,
        "video_title": video_title,
        "video_description": video_description,
        "video_hashtags": video_hashtags,
        "output_path": asset.object_key if asset else None,
        "download_url": download_url,
        "error": wf.failure_detail,
        "logs": logs,
    }

