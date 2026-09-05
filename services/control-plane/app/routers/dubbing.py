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

import os
import uuid
from pathlib import PurePosixPath
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Header, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.application.authorize_organization import AuthorizeOrganization
from app.core.oidc import VerifiedIdentity
from app.core.source_media import UnsafeSourceUrl, validate_external_video_url
from app.domain.authorization import Permission
from app.infrastructure.database import get_session
from app.infrastructure.membership_repository import SqlAlchemyOrganizationMembershipRepository
from app.infrastructure.models import MediaAsset, VideoProject, WorkflowRun, WorkflowStep
from app.routers.auth import require_identity
try:
    from app.domain.dubbing_contract import build_dubbing_workflow_package
    from app.domain.publish_metadata import resolve_publish_metadata
except ImportError:
    from worker.domain.dubbing_contract import build_dubbing_workflow_package
    from worker.domain.publish_metadata import resolve_publish_metadata

router = APIRouter(tags=["Dubbing"])


def _web_dubbing_enabled() -> bool:
    return os.getenv('ENABLE_WEB_DUBBING', 'false').strip().lower() == 'true'


def _require_web_dubbing() -> None:
    if not _web_dubbing_enabled():
        raise HTTPException(status_code=503, detail='Browser dubbing is not enabled in this environment')


@router.get('/dubbing/capabilities')
def dubbing_capabilities():
    return {'web_dubbing_enabled': _web_dubbing_enabled()}

class DubbingDispatchRequest(BaseModel):
    source_asset_id: Optional[uuid.UUID] = None
    source_url: Optional[str] = None
    file_path: Optional[str] = None
    translation_mode: Literal["faithful", "localized_adaptation"] = "faithful"
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
    organization_id: uuid.UUID
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
    enable_narration_cta: bool = False
    enable_seamless_loop_adaptation: bool = False


class SourceUploadIntentRequest(BaseModel):
    organization_id: uuid.UUID
    filename: str
    content_type: str = "video/mp4"
    byte_size: int
    checksum_sha256: str


class SourceUploadCompleteRequest(BaseModel):
    organization_id: uuid.UUID


DubbingDispatchRequest.model_rebuild()


def _authorize_source_write(identity: VerifiedIdentity, organization_id: uuid.UUID, session: Session) -> None:
    if identity.subject == "local|anonymous":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authenticated organization membership is required")
    try:
        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(identity.subject, organization_id, Permission.WORKFLOW_CREATE, identity.email)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You cannot add source media for this organization") from exc


@router.post("/dubbing/source-assets/upload-intents", status_code=status.HTTP_201_CREATED)
def create_source_upload_intent(
    payload: SourceUploadIntentRequest,
    identity: VerifiedIdentity = Depends(require_identity),
    session: Session = Depends(get_session),
):
    """Issue a scoped direct-upload URL; the browser never sends video bytes to the API."""
    _require_web_dubbing()
    _authorize_source_write(identity, payload.organization_id, session)
    max_bytes = int(os.getenv("VISIONFLOW_DUBBING_MAX_SINGLE_UPLOAD_BYTES", str(100 * 1024 * 1024)))
    if not payload.content_type.startswith("video/") or not 0 < payload.byte_size <= max_bytes:
        raise HTTPException(status_code=422, detail="File too large for current direct upload or not a video")
    if len(payload.checksum_sha256) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in payload.checksum_sha256):
        raise HTTPException(status_code=422, detail="checksum_sha256 must be a SHA-256 hex digest")
    suffix = PurePosixPath(payload.filename).suffix.lower() or ".mp4"
    asset_id = uuid.uuid4()
    key = f"visionflow/{payload.organization_id}/source/{asset_id}{suffix}"
    asset = MediaAsset(
        id=asset_id, organization_id=payload.organization_id, object_key=key, media_kind="source_video",
        content_type=payload.content_type, byte_size=payload.byte_size, checksum_sha256=payload.checksum_sha256.lower(),
        metadata_json={"status": "UPLOADING", "origin": "browser_upload", "filename": PurePosixPath(payload.filename).name},
    )
    session.add(asset)
    try:
        from worker.services.visionflow_object_storage import S3CompatibleObjectStorage, VisionFlowObjectStorageSettings
        upload_url = S3CompatibleObjectStorage(VisionFlowObjectStorageSettings.from_env()).issue_upload_url(
            key, content_type=payload.content_type, checksum_sha256=payload.checksum_sha256.lower()
        )
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=503, detail="Object storage upload is not configured") from exc
    session.commit()
    return {
        "source_asset_id": str(asset_id), "object_key": key, "upload_url": upload_url,
        "upload_mode": "single_put", "max_single_upload_bytes": max_bytes,
        "required_headers": {"Content-Type": payload.content_type, "x-amz-meta-sha256": payload.checksum_sha256.lower()},
    }


@router.post("/dubbing/source-assets/{asset_id}/complete")
def complete_source_upload(
    asset_id: uuid.UUID,
    payload: SourceUploadCompleteRequest,
    identity: VerifiedIdentity = Depends(require_identity),
    session: Session = Depends(get_session),
):
    _require_web_dubbing()
    _authorize_source_write(identity, payload.organization_id, session)
    asset = session.get(MediaAsset, asset_id)
    if not asset or asset.organization_id != payload.organization_id or asset.media_kind != "source_video":
        raise HTTPException(status_code=404, detail="Source video asset was not found")
    try:
        from worker.services.visionflow_object_storage import S3CompatibleObjectStorage, VisionFlowObjectStorageSettings
        head = S3CompatibleObjectStorage(VisionFlowObjectStorageSettings.from_env()).head_object(asset.object_key)
    except Exception as exc:
        raise HTTPException(status_code=409, detail="Uploaded source video cannot be verified yet") from exc
    if int(head.get("ContentLength") or 0) != asset.byte_size:
        raise HTTPException(status_code=409, detail="Uploaded source video size does not match the upload intent")
    head_content_type = str(head.get("ContentType") or "").lower()
    if not head_content_type.startswith("video/"):
        raise HTTPException(status_code=409, detail="Uploaded source object is not a video")
    uploaded_checksum = str((head.get("Metadata") or {}).get("sha256") or "").lower()
    if uploaded_checksum != asset.checksum_sha256.lower():
        raise HTTPException(status_code=409, detail="Uploaded source checksum does not match the upload intent")
    asset.metadata_json = {**(asset.metadata_json or {}), "status": "READY", "storage_etag": str(head.get("ETag") or "").strip('"')}
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(asset, "metadata_json")
    session.commit()
    return {"source_asset_id": str(asset.id), "status": "READY"}


@router.post("/dubbing/dispatch", status_code=status.HTTP_201_CREATED)
def dispatch_dubbing_job(
    payload: DubbingDispatchRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    identity: VerifiedIdentity = Depends(require_identity),
    session: Session = Depends(get_session),
):
    """
    Đăng ký công việc Lồng Tiếng & Vietsub Tự Động (AI Dubbing Job).
    Lưu toàn bộ vào PostgreSQL. Không cần MySQL.
    """
    if not payload.source_asset_id and not payload.source_url and not payload.file_path:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Vui lòng cung cấp đường dẫn link video (source_url) hoặc đường dẫn tệp tải lên (file_path).",
        )

    if identity.subject == "local|anonymous":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authenticated organization membership is required")
    try:
        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(
            identity.subject, payload.organization_id, Permission.WORKFLOW_CREATE, identity.email
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You cannot create a dubbing workflow for this organization") from exc

    if payload.source_url:
        if os.getenv("ENABLE_DUBBING_URL_IMPORT", "false").strip().lower() != "true":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="URL dubbing is disabled until secure URL import is enabled")
        try:
            payload.source_url = validate_external_video_url(payload.source_url)
        except UnsafeSourceUrl as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    source_asset = None
    if payload.source_asset_id:
        _require_web_dubbing()
        source_asset = session.get(MediaAsset, payload.source_asset_id)
        if not source_asset or source_asset.organization_id != payload.organization_id or source_asset.media_kind != "source_video":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source video asset was not found in this organization")
        if (source_asset.metadata_json or {}).get("status") != "READY":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Source video is not ready for dubbing")

    # Replays return exactly the original workflow for a caller-owned key.
    request_key = (idempotency_key or "").strip()
    if request_key:
        existing = session.scalars(
            select(WorkflowRun).join(VideoProject).where(
                VideoProject.organization_id == payload.organization_id,
                WorkflowRun.idempotency_key == f"dub:{payload.organization_id}:{request_key}",
            )
        ).first()
        if existing:
            return {"job_id": str(existing.id), "workflow_run_id": str(existing.id), "status": existing.state.lower(), "message": "Existing dubbing workflow returned (idempotent replay)."}

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
        "translation_mode": payload.translation_mode,
        "enable_narration_cta": payload.enable_narration_cta,
        "enable_seamless_loop_adaptation": payload.enable_seamless_loop_adaptation,
    }
    metadata["source_asset_id"] = str(payload.source_asset_id) if payload.source_asset_id else None
    metadata["dubbing_workflow"] = build_dubbing_workflow_package(metadata, source_asset_id=metadata["source_asset_id"])

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
    proj = VideoProject(
            organization_id=payload.organization_id,
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
            idempotency_key=f"dub:{payload.organization_id}:{request_key}" if request_key else f"dub-{uuid.uuid4().hex}",
            legacy_job_id=f"dub-{workflow_run_id}",
            prompt_manifest=metadata,
            input_payload=metadata,
    )
    session.add(wf)
    try:
        session.flush()
        session.commit()
    except IntegrityError:
        # The DB unique key closes the race between the initial replay lookup
        # and two simultaneous browser/Telegram retries.
        session.rollback()
        if request_key:
            existing = session.scalars(
                select(WorkflowRun).join(VideoProject).where(
                    VideoProject.organization_id == payload.organization_id,
                    WorkflowRun.idempotency_key == f"dub:{payload.organization_id}:{request_key}",
                )
            ).first()
            if existing:
                return {"job_id": str(existing.id), "workflow_run_id": str(existing.id), "status": existing.state.lower(), "message": "Existing dubbing workflow returned (idempotent replay)."}
        raise

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
    organization_id: uuid.UUID,
    identity: VerifiedIdentity = Depends(require_identity),
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
    project = session.get(VideoProject, wf.project_id) if wf.project_id else None
    if not project or project.organization_id != organization_id:
        raise HTTPException(status_code=404, detail="Không tìm thấy công việc lồng tiếng này.")
    try:
        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(identity.subject, organization_id, Permission.WORKFLOW_VIEW, identity.email)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You cannot view this dubbing workflow") from exc

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
    proj = project
    
    raw_proj_title = proj.title if proj else None
    ai_generated_title = seo_metadata.get("title")
    
    if ai_generated_title:
        video_title = ai_generated_title
    elif raw_proj_title and not any(kw in raw_proj_title for kw in ["Video Douyin", "Video TikTok", "Video YouTube", "Lồng Tiếng Tự Động", "Lồng Tiếng AI"]):
        video_title = raw_proj_title
    else:
        video_title = raw_proj_title or "Video Lồng Tiếng AI Mới"

    resolved = resolve_publish_metadata(
        content_metadata=manifest.get("publish_metadata"),
        user_metadata=manifest.get("publish_metadata_user"),
        fallback={"youtube": {"title": raw_proj_title, "description": proj.brief if proj else ""}},
    )
    video_title = resolved.title.value if resolved.title else video_title
    video_description = resolved.description.value if resolved.description else (proj.brief if proj else "")
    video_hashtags = resolved.hashtags.value if resolved.hashtags else []

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
        "review": {
            "source": (manifest.get("dubbing_workflow") or {}).get("source", {}),
            "source_transcript": [
                {"start": row.get("start"), "end": row.get("end"),
                 "source_text": row.get("source_text") or row.get("text") or ""}
                for row in (manifest.get("dubbing_workflow") or {}).get("translation", {}).get("timeline", [])
            ],
            "translation": (manifest.get("dubbing_workflow") or {}).get("translation", {}),
            "dubbing": (manifest.get("dubbing_workflow") or {}).get("dubbing", {}),
            "subtitle_settings": {"burn_subtitles": manifest.get("burn_subtitles"), "caption_preset": manifest.get("caption_preset")},
            "audio_settings": {"mute_original_audio": manifest.get("mute_original_audio")},
            "render_output": {"asset_id": str(asset.id), "object_key": asset.object_key} if asset else None,
            "publish_metadata": manifest.get("publish_metadata") or {},
        },
    }

