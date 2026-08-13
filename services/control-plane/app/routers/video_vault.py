"""
Video Vault API Router
======================
API Router phục vụ cho trang Kho Video Cloud (Cloud Video Vault).
Cung cấp các endpoint:
- GET /organizations/{organization_id}/video-vault: Liệt kê tất cả video assets trên Cloud R2 kèm metadata phong phú (SEO title, brief, description, hashtags, duration, byte size, status, download presigned URL).
- DELETE /organizations/{organization_id}/video-vault/{asset_id}: Xóa một video asset (Xóa record DB + Xóa file R2 Object Store).
- DELETE /organizations/{organization_id}/video-vault/bulk: Xóa hàng loạt video assets được chọn.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.application.authorize_organization import AuthorizeOrganization
from app.core.oidc import VerifiedIdentity
from app.domain.authorization import Permission
from app.infrastructure.database import get_session
from app.infrastructure.membership_repository import SqlAlchemyOrganizationMembershipRepository
from app.infrastructure.models import (
    CreativeProposal,
    MediaAsset,
    PublishApproval,
    PublicationAttempt,
    PublisherConnection,
    VideoProject,
    WorkflowRun,
    WorkflowStep,
)
from app.infrastructure.overlay_uploads import (
    OverlayUploadConfigurationError,
    OverlayUploadVerificationError,
    PrivateObjectPreviewIssuer,
)
from app.routers.auth import require_identity

logger = logging.getLogger(__name__)

router = APIRouter(tags=["video-vault"])


class VideoVaultItemResponse(BaseModel):
    id: uuid.UUID
    workflow_run_id: uuid.UUID | None
    project_id: uuid.UUID | None
    title: str
    brief: str | None
    description: str | None
    hashtags: list[str]
    voice_used: str | None
    target_language: str | None
    object_key: str
    download_url: str
    media_kind: str
    content_type: str
    byte_size: int
    checksum_sha256: str
    workflow_state: str
    publication_state: str  # "published", "pending_review", "not_published", "failed"
    external_url: str | None
    created_at: datetime
    updated_at: datetime


class VideoVaultListResponse(BaseModel):
    items: list[VideoVaultItemResponse]
    total_count: int
    total_byte_size: int
    published_count: int
    rendered_count: int
    failed_or_cancelled_count: int


class BulkDeleteVideoVaultRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)


def _authorize(session: Session, identity: VerifiedIdentity, organization_id: uuid.UUID, permission: str = Permission.WORKFLOW_VIEW) -> None:
    try:
        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(
            identity.subject, organization_id, permission
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization permission denied") from exc


def _delete_r2_object(object_key: str) -> None:
    """Xóa file khỏi Cloud Storage R2/S3 nếu có thể."""
    if not object_key or object_key.startswith("http://") or object_key.startswith("https://"):
        return
    try:
        issuer = PrivateObjectPreviewIssuer.from_env()
        clean_key = object_key.split("?")[0]
        if "visionflow/" in clean_key:
            clean_key = "visionflow/" + clean_key.split("visionflow/", 1)[1]
        issuer._client.delete_object(Bucket=issuer._bucket, Key=clean_key)
        logger.info("Deleted R2 object key: %s", clean_key)
    except Exception as err:
        logger.warning("Non-fatal error deleting R2 object key %s: %s", object_key, err)


@router.get(
    "/organizations/{organization_id}/video-vault",
    response_model=VideoVaultListResponse,
)
def list_video_vault_assets(
    organization_id: uuid.UUID,
    state_filter: str | None = Query(default=None, alias="filter"),
    identity: VerifiedIdentity = Depends(require_identity),
    session: Session = Depends(get_session),
) -> VideoVaultListResponse:
    """Truy vấn tất cả video asset của tổ chức kèm thông tin SEO/Metadata/Cloud Presigned Link."""
    _authorize(session, identity, organization_id, Permission.WORKFLOW_VIEW)

    # Truy vấn tất cả MediaAsset của org (media_kind == 'final_export' hoặc 'rendered_video' hoặc 'overlay')
    query = (
        select(MediaAsset, WorkflowRun, VideoProject)
        .outerjoin(WorkflowRun, WorkflowRun.id == MediaAsset.workflow_run_id)
        .outerjoin(VideoProject, VideoProject.id == WorkflowRun.project_id)
        .where(MediaAsset.organization_id == organization_id)
        .order_by(MediaAsset.created_at.desc())
    )

    rows = session.execute(query).all()

    # Thống kê
    total_byte_size = 0
    published_count = 0
    rendered_count = 0
    failed_or_cancelled_count = 0

    preview_issuer = None
    try:
        preview_issuer = PrivateObjectPreviewIssuer.from_env()
    except Exception:
        pass

    items: list[VideoVaultItemResponse] = []

    for asset, wf_run, project in rows:
        total_byte_size += asset.byte_size or 0
        wf_state = wf_run.state if wf_run else "UNKNOWN"

        if wf_state in ("FAILED", "CANCELLED"):
            failed_or_cancelled_count += 1
        elif wf_state in ("RENDERED", "APPROVAL_PENDING", "APPROVED", "PUBLISHING", "PUBLISHED"):
            rendered_count += 1

        # Lấy thông tin bài đăng
        pub_attempt = None
        if wf_run:
            pub_attempt = session.scalar(
                select(PublicationAttempt)
                .where(PublicationAttempt.workflow_run_id == wf_run.id)
                .order_by(PublicationAttempt.attempt_number.desc())
            )

        pub_state = "not_published"
        ext_url = None
        if pub_attempt:
            ext_url = pub_attempt.external_url
            if pub_attempt.state == "published" or ext_url:
                pub_state = "published"
                published_count += 1
            elif pub_attempt.state == "failed":
                pub_state = "failed"
            elif pub_attempt.state in ("requested", "claimed", "uploading"):
                pub_state = "pending_review"

        # Tách tiêu đề, mô tả SEO và hashtags từ project hoặc manifest
        manifest = wf_run.prompt_manifest if wf_run else {}
        input_payload = wf_run.input_payload if wf_run else {}

        title = (
            (project.title if project else None)
            or manifest.get("title")
            or manifest.get("dub_source_url")
            or input_payload.get("dub_source_url")
            or f"Video Asset #{str(asset.id)[:8]}"
        )

        brief = project.brief if project else None
        description = manifest.get("seo_description") or manifest.get("description") or input_payload.get("description") or brief
        hashtags = manifest.get("hashtags") or input_payload.get("hashtags") or []
        if isinstance(hashtags, str):
            hashtags = [tag.strip() for tag in hashtags.split(",") if tag.strip()]

        voice_code = manifest.get("voice_code") or input_payload.get("voice_code") or asset.metadata_json.get("voice_code")
        target_lang = manifest.get("target_language") or input_payload.get("target_language") or asset.metadata_json.get("target_language") or "vi"

        # Tính Presigned Download URL từ R2
        download_url = asset.object_key
        if asset.object_key and not (asset.object_key.startswith("http://") or asset.object_key.startswith("https://")):
            try:
                issuer = preview_issuer or PrivateObjectPreviewIssuer.from_env()
                ticket = issuer.issue_final_export(
                    workflow_run_id=asset.workflow_run_id or (wf_run.id if wf_run else asset.id),
                    object_key=asset.object_key,
                )
                download_url = ticket.download_url
            except Exception as err:
                logger.warning("Error generating presigned URL for asset %s: %s", asset.id, err)
                download_url = f"https://ec302240fdb8cad9ae6c9b685f14eeec.r2.cloudflarestorage.com/vision-flow/{asset.object_key.split('?')[0]}"

        # Phân loại filter
        if state_filter:
            norm_filter = state_filter.lower().strip()
            if norm_filter == "published" and pub_state != "published":
                continue
            if norm_filter == "rendered" and wf_state not in ("RENDERED", "APPROVAL_PENDING", "APPROVED"):
                continue
            if norm_filter == "failed" and wf_state not in ("FAILED", "CANCELLED"):
                continue

        items.append(
            VideoVaultItemResponse(
                id=asset.id,
                workflow_run_id=asset.workflow_run_id,
                project_id=wf_run.project_id if wf_run else None,
                title=title,
                brief=brief,
                description=description,
                hashtags=hashtags,
                voice_used=voice_code,
                target_language=target_lang,
                object_key=asset.object_key,
                download_url=download_url,
                media_kind=asset.media_kind,
                content_type=asset.content_type,
                byte_size=asset.byte_size,
                checksum_sha256=asset.checksum_sha256,
                workflow_state=wf_state,
                publication_state=pub_state,
                external_url=ext_url,
                created_at=asset.created_at,
                updated_at=asset.updated_at,
            )
        )

    return VideoVaultListResponse(
        items=items,
        total_count=len(items),
        total_byte_size=total_byte_size,
        published_count=published_count,
        rendered_count=rendered_count,
        failed_or_cancelled_count=failed_or_cancelled_count,
    )


@router.delete(
    "/organizations/{organization_id}/video-vault/{asset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_video_vault_asset(
    organization_id: uuid.UUID,
    asset_id: uuid.UUID,
    identity: VerifiedIdentity = Depends(require_identity),
    session: Session = Depends(get_session),
) -> None:
    """Xóa một video asset khỏi Cloud Vault (Xóa DB MediaAsset + R2 file)."""
    _authorize(session, identity, organization_id, Permission.WORKFLOW_DELETE)

    asset = session.scalar(
        select(MediaAsset).where(
            MediaAsset.id == asset_id,
            MediaAsset.organization_id == organization_id,
        )
    )
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video asset not found")

    object_key = asset.object_key

    # Xóa các bản ghi liên quan trong publish_approvals để tránh vi phạm khóa ngoại RESTRICT
    session.execute(
        delete(PublishApproval).where(PublishApproval.export_asset_id == asset_id)
    )

    session.delete(asset)
    session.commit()

    # Xóa file vật lý trên R2 Cloud Storage
    _delete_r2_object(object_key)


@router.delete(
    "/organizations/{organization_id}/video-vault/bulk",
    status_code=status.HTTP_204_NO_CONTENT,
)
def bulk_delete_video_vault_assets(
    organization_id: uuid.UUID,
    request: BulkDeleteVideoVaultRequest,
    identity: VerifiedIdentity = Depends(require_identity),
    session: Session = Depends(get_session),
) -> None:
    """Xóa hàng loạt các video asset được chọn trong Cloud Vault."""
    _authorize(session, identity, organization_id, Permission.WORKFLOW_DELETE)

    assets = session.scalars(
        select(MediaAsset).where(
            MediaAsset.id.in_(request.asset_ids),
            MediaAsset.organization_id == organization_id,
        )
    ).all()

    if not assets:
        return

    object_keys = [a.object_key for a in assets]
    asset_ids = [a.id for a in assets]

    # Xóa các bản ghi liên quan trong publish_approvals trước
    session.execute(
        delete(PublishApproval).where(PublishApproval.export_asset_id.in_(asset_ids))
    )

    for asset in assets:
        session.delete(asset)
    session.commit()

    # Xóa các file vật lý trên R2 Cloud Storage
    for key in object_keys:
        _delete_r2_object(key)
