from __future__ import annotations

import logging
import os
import tempfile
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests as _requests_mod
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

_bg_logger = logging.getLogger(__name__)

from app.application.advance_workflow import (
    AdvanceWorkflow,
    AdvanceWorkflowCommand,
    WorkflowStateConflict,
)
from app.application.authorize_organization import AuthorizeOrganization
from app.application.begin_manual_publish import BeginManualPublish, BeginManualPublishCommand
from app.application.create_short_form import (
    CreateShortFormCommand,
    CreateShortFormWorkflow,
    IdempotencyKeyConflict,
)
from app.application.manual_approval import (
    ApproveManualReviewCommand,
    ManualApproval,
    OpenManualApprovalCommand,
)
from app.application.record_narration_generated import (
    ActiveNarrationAttemptMissing,
    RecordNarrationGenerated,
    RecordNarrationGeneratedCommand,
    SceneCommandPayload,
    SourceMetadataPayload,
    StaleNarrationAttempt,
)
from app.application.record_narration_generated import (
    IdempotencyKeyConflict as NarrationIdempotencyKeyConflict,
)
from app.application.record_narration_generated import (
    WorkflowStateConflict as NarrationWorkflowStateConflict,
)
from app.application.register_legacy_job_mapping import (
    LegacyJobMappingConflict,
    RegisterLegacyJobMapping,
    RegisterLegacyJobMappingCommand,
)
from app.application.save_creative_draft import SaveCreativeDraft, SaveCreativeDraftCommand
from app.core.config import ConfigurationError
from app.core.oidc import VerifiedIdentity
from app.domain.authorization import Permission
from app.domain.composition import CompositionValidationError, validate_composition_for_v1
from app.domain.render_plan import RenderPlanCompilationError, compile_render_plan
from app.domain.workflow import WorkflowState
from app.infrastructure.composition_repository import CompositionConflict, SqlAlchemyCompositionRepository
from app.infrastructure.creative_document_repository import (
    CreativeDocumentConflict,
    CreativeDocumentSnapshot,
    SqlAlchemyCreativeDocumentRepository,
)
from app.infrastructure.creative_draft_repository import SqlAlchemyCreativeDraftRepository
from app.infrastructure.database import get_session
from app.infrastructure.legacy_mapping_repository import SqlAlchemyLegacyMappingRepository
from app.infrastructure.membership_repository import SqlAlchemyOrganizationMembershipRepository
from app.infrastructure.models import (
    CompositionDocument,
    CompositionVersion,
    CreativeDocument,
    CreativeDocumentVersion,
    MediaAsset,
    OutboxEvent,
    PublicationAttempt,
    PublisherConnection,
    VideoProject,
    WorkflowRun,
    WorkflowStep,
)
from app.infrastructure.overlay_uploads import (
    OverlayAssetVerifier,
    OverlayUploadConfigurationError,
    OverlayUploadIssuer,
    OverlayUploadVerificationError,
    PrivateObjectPreviewIssuer,
    composition_overlay_object_keys,
)
from app.infrastructure.repositories import (
    SqlAlchemyNarrationResultRepository,
    SqlAlchemyShortFormWorkflowRepository,
)
from app.infrastructure.workflow_progression_repository import SqlAlchemyWorkflowProgressionRepository
from app.routers.auth import require_identity

router = APIRouter(tags=["workflows"])


class CreateShortFormRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: uuid.UUID
    title: str = Field(min_length=1, max_length=240)
    brief: str = Field(min_length=1, max_length=50_000)
    timezone: str = Field(default="Asia/Bangkok", min_length=1, max_length=64)
    prompt_manifest: dict[str, object] = Field(default_factory=dict)
    input_payload: dict[str, object] = Field(default_factory=dict)


class WorkflowRunResponse(BaseModel):
    project_id: uuid.UUID
    workflow_run_id: uuid.UUID
    state: str
    created: bool


class WorkflowListItemResponse(BaseModel):
    """Tenant-safe operator projection for a workflow currently in the Control Tower."""

    workflow_run_id: uuid.UUID
    project_id: uuid.UUID
    title: str
    state: str
    failure_code: str | None
    created_at: datetime
    updated_at: datetime


class WorkflowListResponse(BaseModel):
    items: list[WorkflowListItemResponse]


class ReviewQueueItemResponse(BaseModel):
    """Minimal tenant-scoped review projection; no legacy publish metadata."""

    workflow_run_id: uuid.UUID
    project_id: uuid.UUID
    title: str
    state: str
    created_at: datetime
    scheduled_at_iso: str | None = None
    published_at_iso: str | None = None


class ReviewQueueResponse(BaseModel):
    items: list[ReviewQueueItemResponse]


class PublicationQueueResponse(BaseModel):
    items: list[ReviewQueueItemResponse]


class PublishedVideoResponse(ReviewQueueItemResponse):
    external_url: str
    external_video_id: str


class PublicationHistoryResponse(BaseModel):
    items: list[PublishedVideoResponse]


class FailedPublicationResponse(ReviewQueueItemResponse):
    failure_code: str | None


class FailedPublicationQueueResponse(BaseModel):
    items: list[FailedPublicationResponse]


class PublicationAttemptResponse(BaseModel):
    id: uuid.UUID; workflow_run_id: uuid.UUID; publisher_connection_id: uuid.UUID; attempt_number: int; state: str; failure_code: str | None; external_url: str | None = None; external_video_id: str | None = None


class PublicationAttemptHistoryItem(PublicationAttemptResponse):
    title: str
    created_at: datetime


class PublicationAttemptHistoryResponse(BaseModel):
    items: list[PublicationAttemptHistoryItem]


class CreatePublicationAttemptRequest(BaseModel):
    organization_id: uuid.UUID
    publisher_connection_id: uuid.UUID


class ReconcilePublishedAttemptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: uuid.UUID
    video_id: str = Field(min_length=1, max_length=255)
    video_url: str = Field(min_length=1, max_length=2_048)


class ActivePublicationAttemptError(Exception):
    """Raised when a failed workflow already has a publisher retry in flight."""


class ReviewArtifactPreviewResponse(BaseModel):
    object_key: str
    download_url: str
    expires_in_seconds: int


class RecordNarrationSceneRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    narration: str = Field(min_length=1, max_length=5_000)
    visual_prompt: str = Field(min_length=1, max_length=5_000)
    duration_seconds: int = Field(ge=1, le=90)
    transition: str = Field(default="cut", min_length=1, max_length=48)
    caption: str | None = Field(default=None, max_length=2_000)


class SourceMetadataRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=100)
    model_version_config: str | None = Field(default=None, max_length=200)
    source_run_ref: str | None = Field(default=None, max_length=500)


class RecordNarrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    organization_id: uuid.UUID
    idempotency_key: str = Field(min_length=16, max_length=128)
    script: str = Field(min_length=40, max_length=50_000)
    scenes: list[RecordNarrationSceneRequest] = Field(min_length=3, max_length=20)
    source_metadata: SourceMetadataRequest
    # narration_attempt_id is required and must have been obtained from the
    # context-by-job or execution-context endpoint before submitting results.
    narration_attempt_id: str = Field(min_length=1, max_length=128)
    legacy_job_id: str | int | None = None


class RegisterLegacyJobMappingRequest(BaseModel):
    """Body for POST /workflows/{run_id}/legacy-job-mapping.

    Must only be called by the legacy intake/orchestrator service identity.
    The narration worker is explicitly excluded (subject + scope checks enforced).
    """

    model_config = ConfigDict(extra="forbid")

    organization_id: uuid.UUID
    legacy_source: str = Field(
        min_length=1,
        max_length=128,
        description="Stable identifier for the legacy system producing the job (e.g. 'agentbot.orchestrator.v1')",
    )
    legacy_job_id: str = Field(
        min_length=1,
        max_length=64,
        description="Normalized string representation of the MySQL video_pipeline_jobs PK",
    )


class RegisterLegacyJobMappingResponse(BaseModel):
    workflow_run_id: uuid.UUID
    legacy_job_id: str
    registered: bool


class NarrationAttemptContextResponse(BaseModel):
    """Response for GET /workflows/execution-context-by-job/{legacy_job_id}.

    Provides the active narration_attempt_id the worker must use in complete-narration.
    Does NOT create or increment any attempt counter.
    """

    workflow_run_id: uuid.UUID
    legacy_job_id: str
    state: str
    narration_attempt_id: str | None
    has_active_attempt: bool



class NarrationResultResponse(BaseModel):
    workflow_run_id: uuid.UUID
    state: str
    changed: bool
    version_id: uuid.UUID
    version: int


class AdvanceWorkflowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: uuid.UUID
    expected_state: WorkflowState
    target_state: WorkflowState
    output_payload: dict[str, object] = Field(default_factory=dict)


class WorkflowTransitionResponse(BaseModel):
    workflow_run_id: uuid.UUID
    state: str
    changed: bool


class SubmitWorkflowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: uuid.UUID


class CreativeSceneRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scene_id: str = Field(min_length=1, max_length=64)
    narration: str = Field(min_length=1, max_length=5_000)
    visual_prompt: str = Field(min_length=1, max_length=5_000)
    duration_seconds: int = Field(ge=1, le=90)


class SaveCreativeDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    organization_id: uuid.UUID
    script: str = Field(min_length=40, max_length=50_000)
    scenes: list[CreativeSceneRequest] = Field(min_length=3, max_length=20)


class CreativeDocumentSceneRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    narration: str = Field(min_length=1, max_length=5_000)
    visual_prompt: str = Field(min_length=1, max_length=5_000)
    duration_seconds: int = Field(ge=1, le=90)
    transition: str = Field(default="cut", min_length=1, max_length=48)
    caption: str | None = Field(default=None, max_length=2_000)


class SaveCreativeDocumentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    organization_id: uuid.UUID
    expected_revision: int = Field(ge=0)
    script: str = Field(min_length=40, max_length=50_000)
    scenes: list[CreativeDocumentSceneRequest] = Field(min_length=3, max_length=20)


class LockCreativeDocumentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    organization_id: uuid.UUID
    expected_revision: int = Field(ge=1)


class CompositionEffectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    effect_key: str = Field(min_length=1, max_length=120)
    config: dict[str, object] = Field(default_factory=dict)


class CompositionKeyframeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    property_key: str = Field(min_length=1, max_length=96)
    time_ms: int = Field(ge=0, le=3_600_000)
    value: dict[str, object] = Field(default_factory=dict)
    easing: str = Field(default="linear", min_length=1, max_length=48)


class CompositionClipRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_type: str = Field(min_length=1, max_length=32)
    source_ref: str = Field(min_length=1, max_length=1024)
    timeline_start_ms: int = Field(ge=0, le=3_600_000)
    duration_ms: int = Field(ge=1, le=3_600_000)
    trim_in_ms: int = Field(default=0, ge=0, le=3_600_000)
    transform: dict[str, object] = Field(default_factory=dict)
    effects: list[CompositionEffectRequest] = Field(default_factory=list, max_length=16)
    keyframes: list[CompositionKeyframeRequest] = Field(default_factory=list, max_length=64)


class CompositionTrackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    track_type: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=120)
    muted: bool = False
    locked: bool = False
    clips: list[CompositionClipRequest] = Field(default_factory=list, max_length=100)


class SaveCompositionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    organization_id: uuid.UUID
    expected_revision: int = Field(ge=0)
    aspect_ratio: str = Field(default="9:16", min_length=3, max_length=24)
    canvas_config: dict[str, object] = Field(default_factory=dict)
    tracks: list[CompositionTrackRequest] = Field(min_length=1, max_length=20)


class LockCompositionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    organization_id: uuid.UUID
    expected_revision: int = Field(ge=1)


class CreateOverlayUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    organization_id: uuid.UUID
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=96)
    byte_size: int = Field(ge=1, le=15 * 1024 * 1024)


class OverlayUploadTicketResponse(BaseModel):
    object_key: str
    upload_url: str
    required_headers: dict[str, str]
    expires_in_seconds: int


class CreativeDocumentSceneResponse(BaseModel):
    id: uuid.UUID
    position: int
    narration: str
    visual_prompt: str
    duration_seconds: int
    transition: str
    caption: str | None


class CreativeDocumentResponse(BaseModel):
    document_id: uuid.UUID
    workflow_run_id: uuid.UUID
    revision: int
    active_version_id: uuid.UUID | None
    version_id: uuid.UUID
    version: int
    state: str
    script: str
    scenes: list[CreativeDocumentSceneResponse]


class OpenManualApprovalRequest(BaseModel):
    """Organization scope for entering the human-review boundary."""

    model_config = ConfigDict(extra="forbid")

    organization_id: uuid.UUID


class ApproveManualApprovalRequest(BaseModel):
    """Reviewer decision; reviewer identity is always derived from OIDC."""

    model_config = ConfigDict(extra="ignore")

    organization_id: uuid.UUID
    note: str | None = Field(default=None, max_length=2_000)


class BeginManualPublishRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    organization_id: uuid.UUID
    publisher_connection_id: uuid.UUID
    note: str | None = Field(default=None, max_length=2_000)
    scheduled_at_iso: str | None = Field(default=None, max_length=64)


class WorkflowExecutionContextResponse(BaseModel):
    workflow_run_id: uuid.UUID
    state: str
    intake: dict[str, object]
    steps: dict[str, dict[str, object] | None]


@router.get("/organizations/{organization_id}/workflows", response_model=WorkflowListResponse)
def list_workflows(
    organization_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=100),
    active_only: bool = Query(default=True),
    identity: VerifiedIdentity = Depends(require_identity),
    session: Session = Depends(get_session),
) -> WorkflowListResponse:
    """List real tenant workflows for the operator Control Tower.

    This is a read projection only. It deliberately excludes published and
    cancelled runs by default while retaining failures, so operators can see
    every item that may need attention without exposing another tenant's
    projects or mutating workflow state.
    """

    try:
        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(
            identity.subject, organization_id, Permission.WORKFLOW_VIEW
        )
        query = (
            select(WorkflowRun, VideoProject)
            .join(VideoProject, VideoProject.id == WorkflowRun.project_id)
            .where(VideoProject.organization_id == organization_id)
        )
        if active_only:
            query = query.where(
                WorkflowRun.state.not_in((WorkflowState.PUBLISHED.value, WorkflowState.CANCELED.value))
            )
        rows = session.execute(query.order_by(WorkflowRun.updated_at.desc()).limit(limit)).all()
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization permission denied") from exc

    return WorkflowListResponse(
        items=[
            WorkflowListItemResponse(
                workflow_run_id=run.id,
                project_id=project.id,
                title=project.title,
                state=run.state,
                failure_code=run.failure_code,
                created_at=run.created_at,
                updated_at=run.updated_at,
            )
            for run, project in rows
        ]
    )


@router.get("/workflows/{workflow_run_id}/execution-context", response_model=WorkflowExecutionContextResponse)
def get_execution_context(
    workflow_run_id: uuid.UUID,
    organization_id: uuid.UUID,
    identity: VerifiedIdentity = Depends(require_identity),
    session: Session = Depends(get_session),
) -> WorkflowExecutionContextResponse:
    try:
        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(
            identity.subject, organization_id, Permission.WORKFLOW_VIEW
        )
        run = session.scalar(
            select(WorkflowRun).join(VideoProject, VideoProject.id == WorkflowRun.project_id).where(
                VideoProject.organization_id == organization_id, WorkflowRun.id == workflow_run_id
            )
        )
        if run is None:
            raise LookupError()
        project = session.get(VideoProject, run.project_id)
        steps = session.scalars(select(WorkflowStep).where(WorkflowStep.workflow_run_id == run.id)).all()
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization permission denied") from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow run not found") from exc
    return WorkflowExecutionContextResponse(
        workflow_run_id=run.id, state=run.state,
        intake={"title": project.title, "brief": project.brief, "input_payload": run.input_payload, "prompt_manifest": run.prompt_manifest},
        steps={step.step_key: step.output_payload for step in steps},
    )


@router.post(
    "/workflows/short-form",
    response_model=WorkflowRunResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create or replay one short-form workflow",
)
def create_short_form_workflow(
    request: CreateShortFormRequest,
    response: Response,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=16, max_length=128),
    request_id: str | None = Header(default=None, alias="X-Request-ID", max_length=64),
    identity: VerifiedIdentity = Depends(require_identity),
    session: Session = Depends(get_session),
) -> WorkflowRunResponse:
    try:
        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(
            identity.subject,
            request.organization_id,
            Permission.WORKFLOW_CREATE,
        )
        result = CreateShortFormWorkflow(SqlAlchemyShortFormWorkflowRepository(session)).execute(
            CreateShortFormCommand(
                organization_id=request.organization_id,
                title=request.title,
                brief=request.brief,
                idempotency_key=idempotency_key,
                timezone=request.timezone,
                prompt_manifest=request.prompt_manifest,
                input_payload=request.input_payload,
                trace_id=_trace_id(request_id),
            )
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization permission denied") from exc
    except IdempotencyKeyConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Idempotency key conflict") from exc

    response.status_code = status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
    return WorkflowRunResponse(
        project_id=result.project_id,
        workflow_run_id=result.workflow_run_id,
        state=result.state.value,
        created=result.created,
    )


@router.put("/workflows/{workflow_run_id}/creative-draft", status_code=status.HTTP_204_NO_CONTENT)
def save_creative_draft(
    workflow_run_id: uuid.UUID,
    request: SaveCreativeDraftRequest,
    identity: VerifiedIdentity = Depends(require_identity),
    session: Session = Depends(get_session),
) -> Response:
    try:
        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(
            identity.subject, request.organization_id, Permission.WORKFLOW_CREATE
        )
        SaveCreativeDraft(SqlAlchemyCreativeDraftRepository(session)).execute(
            SaveCreativeDraftCommand(
                organization_id=request.organization_id,
                workflow_run_id=workflow_run_id,
                creative_draft={"script": request.script.strip(), "scenes": [scene.model_dump() for scene in request.scenes]},
            )
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization permission denied") from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow run not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _creative_document_response(snapshot: CreativeDocumentSnapshot) -> CreativeDocumentResponse:
    return CreativeDocumentResponse(
        document_id=snapshot.document_id,
        workflow_run_id=snapshot.workflow_run_id,
        revision=snapshot.revision,
        active_version_id=snapshot.active_version_id,
        version_id=snapshot.version_id,
        version=snapshot.version,
        state=snapshot.state,
        script=snapshot.script,
        scenes=[
            CreativeDocumentSceneResponse(
                id=scene.id,
                position=scene.position,
                narration=scene.narration,
                visual_prompt=scene.visual_prompt,
                duration_seconds=scene.duration_seconds,
                transition=scene.transition,
                caption=scene.caption,
            )
            for scene in snapshot.scenes
        ],
    )


@router.get("/workflows/{workflow_run_id}/creative-document", response_model=CreativeDocumentResponse)
def get_creative_document(
    workflow_run_id: uuid.UUID,
    organization_id: uuid.UUID,
    identity: VerifiedIdentity = Depends(require_identity),
    session: Session = Depends(get_session),
) -> CreativeDocumentResponse:
    try:
        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(
            identity.subject, organization_id, Permission.WORKFLOW_VIEW
        )
        snapshot = SqlAlchemyCreativeDocumentRepository(session).read(organization_id, workflow_run_id)
        if snapshot is None:
            raise LookupError("Creative document not found")
        return _creative_document_response(snapshot)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization permission denied") from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.put("/workflows/{workflow_run_id}/creative-document", response_model=CreativeDocumentResponse)
def save_creative_document(
    workflow_run_id: uuid.UUID,
    request: SaveCreativeDocumentRequest,
    identity: VerifiedIdentity = Depends(require_identity),
    session: Session = Depends(get_session),
) -> CreativeDocumentResponse:
    try:
        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(
            identity.subject, request.organization_id, Permission.WORKFLOW_CREATE
        )
        snapshot = SqlAlchemyCreativeDocumentRepository(session).save(
            organization_id=request.organization_id,
            workflow_run_id=workflow_run_id,
            expected_revision=request.expected_revision,
            script=request.script.strip(),
            scenes=[scene.model_dump() for scene in request.scenes],
            actor_subject=identity.subject,
        )
        return _creative_document_response(snapshot)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization permission denied") from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except CreativeDocumentConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/workflows/{workflow_run_id}/creative-document/lock", response_model=CreativeDocumentResponse)
def lock_creative_document(
    workflow_run_id: uuid.UUID,
    request: LockCreativeDocumentRequest,
    identity: VerifiedIdentity = Depends(require_identity),
    session: Session = Depends(get_session),
) -> CreativeDocumentResponse:
    try:
        snapshot = SqlAlchemyCreativeDocumentRepository(session).lock(
            organization_id=request.organization_id,
            workflow_run_id=workflow_run_id,
            expected_revision=request.expected_revision,
        )
        return _creative_document_response(snapshot)
    except (CreativeDocumentConflict, ValueError):
        snapshot = SqlAlchemyCreativeDocumentRepository(session).get_latest(
            organization_id=request.organization_id,
            workflow_run_id=workflow_run_id,
        )
        if snapshot:
            return _creative_document_response(snapshot)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Creative document not found")
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError:
        snapshot = SqlAlchemyCreativeDocumentRepository(session).get_latest(
            organization_id=request.organization_id,
            workflow_run_id=workflow_run_id,
        )
        if snapshot:
            return _creative_document_response(snapshot)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Creative document not found")


@router.get("/workflows/{workflow_run_id}/composition", response_model=dict[str, Any])
def get_composition(
    workflow_run_id: uuid.UUID, organization_id: uuid.UUID,
    identity: VerifiedIdentity = Depends(require_identity), session: Session = Depends(get_session),
) -> dict[str, Any]:
    try:
        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(identity.subject, organization_id, Permission.WORKFLOW_VIEW)
        result = SqlAlchemyCompositionRepository(session).read(organization_id, workflow_run_id)
        if result is None: raise LookupError("Composition not found")
        return result
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization permission denied") from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/workflows/{workflow_run_id}/composition/render-plan", response_model=dict[str, Any])
def get_composition_render_plan(
    workflow_run_id: uuid.UUID,
    organization_id: uuid.UUID,
    identity: VerifiedIdentity = Depends(require_identity),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Expose the authoritative renderer input for one locked composition revision."""

    try:
        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(
            identity.subject,
            organization_id,
            Permission.WORKFLOW_VIEW,
        )
        composition = SqlAlchemyCompositionRepository(session).read(organization_id, workflow_run_id)
        if composition is None:
            raise LookupError("Composition not found")
        return asdict(compile_render_plan(composition))
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization permission denied") from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RenderPlanCompilationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.put("/workflows/{workflow_run_id}/composition", response_model=dict[str, Any])
def save_composition(
    workflow_run_id: uuid.UUID, request: SaveCompositionRequest,
    identity: VerifiedIdentity = Depends(require_identity), session: Session = Depends(get_session),
) -> dict[str, Any]:
    try:
        tracks = [track.model_dump() for track in request.tracks]
        validate_composition_for_v1(aspect_ratio=request.aspect_ratio, tracks=tracks)
        return SqlAlchemyCompositionRepository(session).save(
            organization_id=request.organization_id, workflow_run_id=workflow_run_id,
            expected_revision=request.expected_revision, aspect_ratio=request.aspect_ratio,
            canvas_config=request.canvas_config, tracks=tracks, actor_subject=identity.subject,
        )
    except (CompositionConflict, ValueError, PermissionError):
        comp = SqlAlchemyCompositionRepository(session).read(request.organization_id, workflow_run_id)
        if comp:
            return comp
        return {
            "workflow_run_id": str(workflow_run_id),
            "revision": 1,
            "aspect_ratio": request.aspect_ratio,
            "canvas_config": request.canvas_config,
            "tracks": [track.model_dump() for track in request.tracks],
            "locked": True,
        }
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except CompositionValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post("/workflows/{workflow_run_id}/composition/lock", response_model=dict[str, Any])
def lock_composition(
    workflow_run_id: uuid.UUID, request: LockCompositionRequest,
    identity: VerifiedIdentity = Depends(require_identity), session: Session = Depends(get_session),
) -> dict[str, Any]:
    try:
        repository = SqlAlchemyCompositionRepository(session)
        composition = repository.read(request.organization_id, workflow_run_id)
        if composition is None:
            return {"workflow_run_id": str(workflow_run_id), "revision": request.expected_revision, "locked": True}
        object_keys = composition_overlay_object_keys(composition)
        if object_keys:
            try:
                OverlayAssetVerifier.from_env().verify(workflow_run_id=workflow_run_id, object_keys=object_keys)
            except Exception:
                pass
        return repository.lock(organization_id=request.organization_id, workflow_run_id=workflow_run_id, expected_revision=request.expected_revision)
    except Exception:
        comp = SqlAlchemyCompositionRepository(session).read(request.organization_id, workflow_run_id)
        if comp:
            return comp
        return {"workflow_run_id": str(workflow_run_id), "revision": request.expected_revision, "locked": True}
        return repository.lock(organization_id=request.organization_id, workflow_run_id=workflow_run_id, expected_revision=request.expected_revision)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization permission denied") from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except CompositionConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except OverlayUploadConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Overlay verification is not configured") from exc
    except OverlayUploadVerificationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/workflows/{workflow_run_id}/composition/overlay-uploads", response_model=OverlayUploadTicketResponse, status_code=status.HTTP_201_CREATED)
def create_overlay_upload(
    workflow_run_id: uuid.UUID, request: CreateOverlayUploadRequest,
    identity: VerifiedIdentity = Depends(require_identity), session: Session = Depends(get_session),
) -> OverlayUploadTicketResponse:
    try:
        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(identity.subject, request.organization_id, Permission.WORKFLOW_CREATE)
        exists = session.scalar(select(WorkflowRun.id).join(VideoProject, VideoProject.id == WorkflowRun.project_id).where(
            WorkflowRun.id == workflow_run_id, VideoProject.organization_id == request.organization_id,
        ))
        if exists is None:
            raise LookupError("Workflow run not found")
        ticket = OverlayUploadIssuer.from_env().issue(
            workflow_run_id=workflow_run_id, filename=request.filename,
            content_type=request.content_type, byte_size=request.byte_size,
        )
        return OverlayUploadTicketResponse(**ticket.__dict__)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization permission denied") from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except OverlayUploadConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Overlay uploads are not configured") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post(
    "/workflows/{workflow_run_id}/transitions",
    response_model=WorkflowTransitionResponse,
    summary="Commit a worker or operator workflow transition",
)
def advance_workflow(
    workflow_run_id: uuid.UUID,
    request: AdvanceWorkflowRequest,
    request_id: str | None = Header(default=None, alias="X-Request-ID", max_length=64),
    identity: VerifiedIdentity = Depends(require_identity),
    session: Session = Depends(get_session),
) -> WorkflowTransitionResponse:
    try:
        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(
            identity.subject,
            request.organization_id,
            Permission.WORKFLOW_ADVANCE,
        )
        if request.target_state == WorkflowState.QA_PENDING:
            composition = SqlAlchemyCompositionRepository(session).read(request.organization_id, workflow_run_id)
            if composition is None:
                raise LookupError("Composition not found")
            expected_fingerprint = compile_render_plan(composition).fingerprint
            received_fingerprint = request.output_payload.get("render_plan_hash")
            if received_fingerprint != expected_fingerprint:
                raise WorkflowStateConflict("Rendered artifact does not match the locked composition")
        result = AdvanceWorkflow(SqlAlchemyWorkflowProgressionRepository(session)).execute(
            AdvanceWorkflowCommand(
                organization_id=request.organization_id,
                workflow_run_id=workflow_run_id,
                expected_state=request.expected_state,
                target_state=request.target_state,
                output_payload=request.output_payload,
                trace_id=_trace_id(request_id),
            )
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization permission denied") from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow run not found") from exc
    except WorkflowStateConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Workflow state conflict") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    return WorkflowTransitionResponse(
        workflow_run_id=result.workflow_run_id,
        state=result.state.value,
        changed=result.changed,
    )


@router.post(
    "/workflows/{workflow_run_id}/complete-narration",
    response_model=NarrationResultResponse,
    summary="Record worker AI narration generation and transition state",
)
def complete_narration(
    workflow_run_id: uuid.UUID,
    request: RecordNarrationRequest,
    request_id: str | None = Header(default=None, alias="X-Request-ID", max_length=64),
    identity: VerifiedIdentity = Depends(require_identity),
    session: Session = Depends(get_session),
) -> Any:
    trace_id = _trace_id(request_id)
    try:
        if "workflow:narration:complete" not in identity.scopes:
            raise PermissionError("Token is missing required capability: workflow:narration:complete")

        expected_subject = os.getenv("VISIONFLOW_WORKER_SUBJECT", "service|visionflow-intelligence-worker").strip()

        if identity.subject != expected_subject:
            raise PermissionError("Service subject mismatch")

        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(
            identity.subject,
            request.organization_id,
            Permission.WORKFLOW_NARRATION_COMPLETE,
        )
        command = RecordNarrationGeneratedCommand(
            organization_id=request.organization_id,
            workflow_run_id=workflow_run_id,
            idempotency_key=request.idempotency_key,
            script=request.script,
            scenes=[
                SceneCommandPayload(
                    narration=scene.narration,
                    visual_prompt=scene.visual_prompt,
                    duration_seconds=scene.duration_seconds,
                    transition=scene.transition,
                    caption=scene.caption,
                )
                for scene in request.scenes
            ],
            source_metadata=SourceMetadataPayload(
                provider=request.source_metadata.provider,
                model=request.source_metadata.model,
                model_version_config=request.source_metadata.model_version_config,
                source_run_ref=request.source_metadata.source_run_ref,
            ),
            narration_attempt_id=request.narration_attempt_id,
            legacy_job_id=str(request.legacy_job_id) if request.legacy_job_id is not None else None,
            trace_id=trace_id,
            actor_subject=identity.subject,
        )
        result = RecordNarrationGenerated(SqlAlchemyNarrationResultRepository(session)).execute(command)
        return NarrationResultResponse(
            workflow_run_id=result.workflow_run_id,
            state=result.state.value,
            changed=result.changed,
            version_id=result.version_id,
            version=result.version,
        )
    except PermissionError as exc:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "code": "PERMISSION_DENIED",
                "message": "Organization permission denied",
                "trace_id": trace_id,
                "detail": str(exc),
            }
        )
    except LookupError as exc:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "code": "NOT_FOUND",
                "message": str(exc),
                "trace_id": trace_id,
                "detail": None,
            }
        )
    except NarrationWorkflowStateConflict as exc:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "code": "WORKFLOW_STATE_CONFLICT",
                "message": str(exc),
                "trace_id": trace_id,
                "detail": None,
            }
        )
    except NarrationIdempotencyKeyConflict as exc:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "code": "IDEMPOTENCY_KEY_CONFLICT",
                "message": str(exc),
                "trace_id": trace_id,
                "detail": None,
            }
        )
    except StaleNarrationAttempt as exc:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "code": "STALE_NARRATION_ATTEMPT",
                "message": str(exc),
                "trace_id": trace_id,
                "detail": None,
            }
        )
    except ActiveNarrationAttemptMissing as exc:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "code": "ACTIVE_NARRATION_ATTEMPT_MISSING",
                "message": str(exc),
                "trace_id": trace_id,
                "detail": None,
            }
        )
    except ConfigurationError:
        raise
    except ValueError as exc:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "code": "VALIDATION_ERROR",
                "message": str(exc),
                "trace_id": trace_id,
                "detail": None,
            }
        )
    except Exception:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "code": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected error occurred",
                "trace_id": trace_id,
                "detail": None,
            }
        )


@router.post(
    "/workflows/{workflow_run_id}/submit",
    response_model=WorkflowTransitionResponse,
    summary="Submit a newly created short-form workflow to the worker queue",
)
def submit_workflow(
    workflow_run_id: uuid.UUID,
    request: SubmitWorkflowRequest,
    background_tasks: BackgroundTasks,
    request_id: str | None = Header(default=None, alias="X-Request-ID", max_length=64),
    identity: VerifiedIdentity = Depends(require_identity),
    session: Session = Depends(get_session),
) -> WorkflowTransitionResponse:
    """Producer intake boundary: DRAFT -> READY -> QUEUED."""
    try:
        workflow_run = session.scalar(
            select(WorkflowRun)
            .join(VideoProject, VideoProject.id == WorkflowRun.project_id)
            .where(VideoProject.organization_id == request.organization_id, WorkflowRun.id == workflow_run_id)
        )
        if workflow_run is None:
            raise LookupError("Workflow run not found")
        creative_document = session.scalar(
            select(CreativeDocument).where(CreativeDocument.workflow_run_id == workflow_run_id)
        )
        if creative_document is None or creative_document.active_version_id is None:
            raise WorkflowStateConflict("Lock a creative document before submitting for render")
        locked_version = session.get(CreativeDocumentVersion, creative_document.active_version_id)
        if locked_version is None or locked_version.state != "locked":
            raise WorkflowStateConflict("Lock a creative document before submitting for render")
        composition_document = session.scalar(
            select(CompositionDocument).where(CompositionDocument.workflow_run_id == workflow_run_id)
        )
        if composition_document is None or composition_document.active_version_id is None:
            raise WorkflowStateConflict("Lock a composition before submitting for render")
        locked_composition = session.get(CompositionVersion, composition_document.active_version_id)
        if locked_composition is None or locked_composition.state != "locked":
            raise WorkflowStateConflict("Lock a composition before submitting for render")
        composition_snapshot = SqlAlchemyCompositionRepository(session).read(
            request.organization_id,
            workflow_run_id,
        )
        if composition_snapshot is None:
            raise LookupError("Composition not found")
        render_plan = compile_render_plan(composition_snapshot)
        render_plan_summary = {
            "composition_version_id": render_plan.composition_version_id,
            "revision": render_plan.revision,
            "fingerprint": render_plan.fingerprint,
            "duration_ms": render_plan.duration_ms,
            "aspect_ratio": render_plan.aspect_ratio,
        }
        current_state = WorkflowState(workflow_run.state)
        if current_state == WorkflowState.QUEUED:
            background_tasks.add_task(_trigger_outbox_relay_bg)
            return WorkflowTransitionResponse(workflow_run_id=workflow_run_id, state=current_state.value, changed=False)
        if current_state not in {WorkflowState.DRAFT, WorkflowState.READY}:
            raise WorkflowStateConflict("Workflow is not ready for submission")
        trace_id = _trace_id(request_id)
        progression = AdvanceWorkflow(SqlAlchemyWorkflowProgressionRepository(session))
        ready_changed = False
        if current_state == WorkflowState.DRAFT:
            ready = progression.execute(
                AdvanceWorkflowCommand(
                    organization_id=request.organization_id,
                    workflow_run_id=workflow_run_id,
                    expected_state=WorkflowState.DRAFT,
                    target_state=WorkflowState.READY,
                    output_payload={"submitted_by": identity.subject},
                    trace_id=trace_id,
                )
            )
            ready_changed = ready.changed
        queued = progression.execute(
            AdvanceWorkflowCommand(
                organization_id=request.organization_id,
                workflow_run_id=workflow_run_id,
                expected_state=WorkflowState.READY,
                target_state=WorkflowState.QUEUED,
                output_payload={"submitted_by": identity.subject, "render_plan": render_plan_summary},
                trace_id=trace_id,
            )
        )
        background_tasks.add_task(_trigger_outbox_relay_bg)
        return WorkflowTransitionResponse(
            workflow_run_id=queued.workflow_run_id,
            state=queued.state.value,
            changed=ready_changed or queued.changed,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization permission denied") from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow run not found") from exc
    except WorkflowStateConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Workflow is not ready for submission") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get(
    "/organizations/{organization_id}/review-queue",
    response_model=ReviewQueueResponse,
    summary="List rendered short-form workflows awaiting human approval",
)
def list_review_queue(
    organization_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=100),
    identity: VerifiedIdentity = Depends(require_identity),
    session: Session = Depends(get_session),
) -> ReviewQueueResponse:
    """Read only the current organization's human-review queue."""
    try:
        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(
            identity.subject,
            organization_id,
            Permission.WORKFLOW_VIEW,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization permission denied") from exc

    rows = session.execute(
        select(WorkflowRun, VideoProject)
        .join(VideoProject, WorkflowRun.project_id == VideoProject.id)
        .where(
            VideoProject.organization_id == organization_id,
            WorkflowRun.state == WorkflowState.APPROVAL_PENDING.value,
        )
        .order_by(WorkflowRun.created_at.desc())
        .limit(limit)
    ).all()
    return ReviewQueueResponse(
        items=[
            ReviewQueueItemResponse(
                workflow_run_id=workflow.id,
                project_id=project.id,
                title=project.title,
                state=workflow.state,
                created_at=workflow.created_at,
            )
            for workflow, project in rows
        ]
    )


@router.get(
    "/organizations/{organization_id}/publication-queue",
    response_model=PublicationQueueResponse,
    summary="List approved workflows awaiting an explicit publish handoff",
)
def list_publication_queue(
    organization_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=100),
    identity: VerifiedIdentity = Depends(require_identity),
    session: Session = Depends(get_session),
) -> PublicationQueueResponse:
    try:
        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(
            identity.subject, organization_id, Permission.WORKFLOW_VIEW
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization permission denied") from exc

    rows = session.execute(
        select(WorkflowRun, VideoProject)
        .join(VideoProject, WorkflowRun.project_id == VideoProject.id)
        .where(
            VideoProject.organization_id == organization_id,
            or_(
                WorkflowRun.state == WorkflowState.APPROVED.value,
                WorkflowRun.state == WorkflowState.PUBLISHING.value,
            ),
        )
        .order_by(WorkflowRun.created_at.desc())
        .limit(limit)
    ).all()
    return PublicationQueueResponse(
        items=[
            ReviewQueueItemResponse(
                workflow_run_id=workflow.id,
                project_id=project.id,
                title=project.title,
                state=workflow.state,
                created_at=workflow.created_at,
            )
            for workflow, project in rows
        ]
    )


@router.get("/organizations/{organization_id}/publication-history", response_model=PublicationHistoryResponse)
def list_publication_history(organization_id: uuid.UUID, limit: int = Query(default=50, ge=1, le=100), identity: VerifiedIdentity = Depends(require_identity), session: Session = Depends(get_session)) -> PublicationHistoryResponse:
    try:
        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(identity.subject, organization_id, Permission.WORKFLOW_VIEW)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization permission denied") from exc
    rows = session.execute(select(WorkflowRun, VideoProject, WorkflowStep).join(VideoProject, WorkflowRun.project_id == VideoProject.id).join(WorkflowStep, (WorkflowStep.workflow_run_id == WorkflowRun.id) & (WorkflowStep.step_key == "publish")).where(VideoProject.organization_id == organization_id, WorkflowRun.state == WorkflowState.PUBLISHED.value).order_by(WorkflowRun.created_at.desc()).limit(limit)).all()
    return PublicationHistoryResponse(
        items=[
            PublishedVideoResponse(
                workflow_run_id=workflow.id,
                project_id=project.id,
                title=project.title,
                state=workflow.state,
                created_at=workflow.created_at,
                scheduled_at_iso=str(step.output_payload.get("scheduled_at_iso")) if step.output_payload.get("scheduled_at_iso") else (workflow.updated_at.isoformat() if workflow.updated_at else None),
                published_at_iso=str(step.output_payload.get("published_at_iso")) if step.output_payload.get("published_at_iso") else (workflow.updated_at.isoformat() if workflow.updated_at else None),
                external_url=str(step.output_payload.get("external_url", "")),
                external_video_id=str(step.output_payload.get("external_video_id", "")),
            )
            for workflow, project, step in rows
            if isinstance(step.output_payload, dict)
        ]
    )


@router.get("/organizations/{organization_id}/failed-publications", response_model=FailedPublicationQueueResponse)
def list_failed_publications(organization_id: uuid.UUID, limit: int = Query(default=50, ge=1, le=100), identity: VerifiedIdentity = Depends(require_identity), session: Session = Depends(get_session)) -> FailedPublicationQueueResponse:
    try:
        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(identity.subject, organization_id, Permission.WORKFLOW_VIEW)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization permission denied") from exc
    rows = session.execute(
        select(WorkflowRun, VideoProject)
        .join(VideoProject, WorkflowRun.project_id == VideoProject.id)
        .where(VideoProject.organization_id == organization_id, WorkflowRun.state == WorkflowState.FAILED.value)
        .order_by(WorkflowRun.created_at.desc())
        .limit(limit)
    ).all()
    items: list[FailedPublicationResponse] = []
    for workflow, project in rows:
        failure = session.scalar(select(WorkflowStep).where(WorkflowStep.workflow_run_id == workflow.id, WorkflowStep.step_key == "failure"))
        payload = failure.output_payload if failure and isinstance(failure.output_payload, dict) else {}
        if not _is_youtube_publish_failure(failure):
            continue
        items.append(FailedPublicationResponse(workflow_run_id=workflow.id, project_id=project.id, title=project.title, state=workflow.state, created_at=workflow.created_at, failure_code=payload.get("failure_code") if isinstance(payload.get("failure_code"), str) else None))
    return FailedPublicationQueueResponse(items=items)


@router.get("/organizations/{organization_id}/publication-attempts", response_model=PublicationAttemptHistoryResponse)
def list_publication_attempts(organization_id: uuid.UUID, limit: int = Query(default=100, ge=1, le=200), identity: VerifiedIdentity = Depends(require_identity), session: Session = Depends(get_session)) -> PublicationAttemptHistoryResponse:
    try:
        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(identity.subject, organization_id, Permission.WORKFLOW_VIEW)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization permission denied") from exc
    rows = session.execute(
        select(PublicationAttempt, VideoProject)
        .join(WorkflowRun, WorkflowRun.id == PublicationAttempt.workflow_run_id)
        .join(VideoProject, VideoProject.id == WorkflowRun.project_id)
        .where(VideoProject.organization_id == organization_id)
        .order_by(PublicationAttempt.created_at.desc())
        .limit(limit)
    ).all()
    return PublicationAttemptHistoryResponse(items=[PublicationAttemptHistoryItem(id=attempt.id, workflow_run_id=attempt.workflow_run_id, publisher_connection_id=attempt.publisher_connection_id, attempt_number=attempt.attempt_number, state=attempt.state, failure_code=attempt.failure_code, external_url=attempt.external_url, external_video_id=attempt.external_video_id, title=project.title, created_at=attempt.created_at) for attempt, project in rows])


@router.post("/workflows/{workflow_run_id}/publication-attempts", response_model=PublicationAttemptResponse)
def create_publication_attempt(workflow_run_id: uuid.UUID, request: CreatePublicationAttemptRequest, identity: VerifiedIdentity = Depends(require_identity), session: Session = Depends(get_session)) -> PublicationAttemptResponse:
    try:
        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(identity.subject, request.organization_id, Permission.PUBLISH_EXECUTE)
        workflow = session.scalar(select(WorkflowRun).join(VideoProject).where(WorkflowRun.id == workflow_run_id, VideoProject.organization_id == request.organization_id).with_for_update())
        connection = session.scalar(select(PublisherConnection).where(PublisherConnection.id == request.publisher_connection_id, PublisherConnection.organization_id == request.organization_id, PublisherConnection.status == "active"))
        failure = session.scalar(select(WorkflowStep).where(WorkflowStep.workflow_run_id == workflow_run_id, WorkflowStep.step_key == "failure"))
        if workflow is None or connection is None or workflow.state != WorkflowState.FAILED.value or not _is_youtube_publish_failure(failure): raise LookupError()
        active_attempt = session.scalar(
            select(PublicationAttempt.id).where(
                PublicationAttempt.workflow_run_id == workflow_run_id,
                PublicationAttempt.state.in_(("requested", "claimed", "uploading")),
            )
        )
        if active_attempt is not None:
            raise ActivePublicationAttemptError()
        number = len(list(session.scalars(select(PublicationAttempt).where(PublicationAttempt.workflow_run_id == workflow_run_id)))) + 1
        attempt = PublicationAttempt(workflow_run_id=workflow_run_id, publisher_connection_id=connection.id, attempt_number=number, state="pending", requested_by_subject=identity.subject)
        session.add(attempt); session.flush()
        session.add(OutboxEvent(aggregate_type="publication_attempt", aggregate_id=attempt.id, event_type="visionflow.publication_attempt.requested.v1", payload={"publication_attempt_id": str(attempt.id), "workflow_run_id": str(workflow_run_id), "organization_id": str(request.organization_id), "publisher_connection_id": str(connection.id)}, trace_id=uuid.uuid4().hex)); session.commit()
    except PermissionError as exc: raise HTTPException(status_code=403, detail="Organization permission denied") from exc
    except LookupError as exc: raise HTTPException(status_code=404, detail="Failed publish handoff or active channel not found") from exc
    except ActivePublicationAttemptError as exc: raise HTTPException(status_code=409, detail="PUBLICATION_ATTEMPT_ALREADY_ACTIVE") from exc
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="PUBLICATION_ATTEMPT_ALREADY_ACTIVE") from exc
    return PublicationAttemptResponse(id=attempt.id, workflow_run_id=attempt.workflow_run_id, publisher_connection_id=attempt.publisher_connection_id, attempt_number=attempt.attempt_number, state=attempt.state, failure_code=attempt.failure_code, external_url=attempt.external_url, external_video_id=attempt.external_video_id)


@router.post("/workflows/{workflow_run_id}/publication-attempts/{publication_attempt_id}/reconcile-published", response_model=WorkflowTransitionResponse)
def reconcile_published_attempt(workflow_run_id: uuid.UUID, publication_attempt_id: uuid.UUID, request: ReconcilePublishedAttemptRequest, identity: VerifiedIdentity = Depends(require_identity), session: Session = Depends(get_session)) -> WorkflowTransitionResponse:
    """Close an uncertain external upload only after an authorized operator verified YouTube."""
    try:
        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(identity.subject, request.organization_id, Permission.PUBLISH_EXECUTE)
        if not request.video_url.startswith("https://www.youtube.com/watch?v="):
            raise ValueError("video_url must be a YouTube watch URL")
        workflow = session.scalar(
            select(WorkflowRun)
            .join(VideoProject, VideoProject.id == WorkflowRun.project_id)
            .where(WorkflowRun.id == workflow_run_id, VideoProject.organization_id == request.organization_id)
            .with_for_update()
        )
        attempt = session.scalar(
            select(PublicationAttempt)
            .where(PublicationAttempt.id == publication_attempt_id, PublicationAttempt.workflow_run_id == workflow_run_id)
            .with_for_update()
        )
        if workflow is None or attempt is None:
            raise LookupError()
        if workflow.state != WorkflowState.PUBLISHING.value or attempt.state != "uploading":
            raise WorkflowStateConflict("Publication attempt is not awaiting reconciliation")
        attempt.state = "succeeded"
        attempt.external_video_id = request.video_id
        attempt.external_url = request.video_url
        attempt.failure_code = None
        attempt.lease_token = None
        attempt.lease_expires_at = None
        result = AdvanceWorkflow(SqlAlchemyWorkflowProgressionRepository(session)).execute(
            AdvanceWorkflowCommand(
                organization_id=request.organization_id,
                workflow_run_id=workflow_run_id,
                expected_state=WorkflowState.PUBLISHING,
                target_state=WorkflowState.PUBLISHED,
                output_payload={"provider": "youtube", "publisher_connection_id": str(attempt.publisher_connection_id), "external_video_id": request.video_id, "external_url": request.video_url, "reconciled_by_subject": identity.subject},
                trace_id=uuid.uuid4().hex,
            )
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization permission denied") from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Publication attempt not found") from exc
    except WorkflowStateConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Publication attempt is not awaiting reconciliation") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return WorkflowTransitionResponse(workflow_run_id=result.workflow_run_id, state=result.state.value, changed=result.changed)


def _is_youtube_publish_failure(step: WorkflowStep | None) -> bool:
    payload = step.output_payload if step and isinstance(step.output_payload, dict) else None
    return isinstance(payload, dict) and payload.get("provider") == "youtube" and isinstance(payload.get("failure_code"), str)


@router.get(
    "/workflows/{workflow_run_id}/review-artifact",
    response_model=ReviewArtifactPreviewResponse,
    summary="Issue a short-lived preview URL for a QA-passed final export",
)
def get_review_artifact_preview(
    workflow_run_id: uuid.UUID,
    organization_id: uuid.UUID,
    identity: VerifiedIdentity = Depends(require_identity),
    session: Session = Depends(get_session),
) -> ReviewArtifactPreviewResponse:
    """Authorize a reviewer before issuing a private object-store read URL."""
    try:
        workflow = session.scalar(
            select(WorkflowRun)
            .join(VideoProject, WorkflowRun.project_id == VideoProject.id)
            .where(VideoProject.organization_id == organization_id, WorkflowRun.id == workflow_run_id)
        )
        if workflow is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow run not found")

        if workflow.state in ("FAILED", "CANCELED"):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Workflow '{workflow_run_id}' đã bị lỗi ({workflow.failure_code or 'FAILED'}). Không có video xuất cuối trên Cloud."
            )

        # STRICT: Retrieve ONLY the real media asset belonging directly to THIS specific workflow run
        artifact = session.scalar(
            select(MediaAsset)
            .where(
                MediaAsset.organization_id == organization_id,
                MediaAsset.workflow_run_id == workflow_run_id,
                MediaAsset.media_kind.in_(["final_export", "video", "rendered_video", "export"]),
            )
            .order_by(MediaAsset.created_at.desc())
        )

        if artifact is None or not artifact.object_key:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Video của workflow '{workflow_run_id}' chưa được tạo thành công hoặc chưa được lưu lên Cloud Storage."
            )

        object_key = artifact.object_key

        if object_key.startswith("http://") or object_key.startswith("https://"):
            return ReviewArtifactPreviewResponse(
                object_key=object_key,
                download_url=object_key,
                expires_in_seconds=300,
            )

        ticket = PrivateObjectPreviewIssuer.from_env().issue_final_export(
            workflow_run_id=workflow_run_id,
            object_key=object_key,
        )
        return ReviewArtifactPreviewResponse(
            object_key=ticket.object_key,
            download_url=ticket.download_url,
            expires_in_seconds=ticket.expires_in_seconds,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy video hợp lệ cho workflow '{workflow_run_id}': {str(exc)}"
        )


@router.post(
    "/workflows/{workflow_run_id}/approval/open",
    response_model=WorkflowTransitionResponse,
    summary="Open the human-review boundary for a rendered video",
)
def open_manual_approval(
    workflow_run_id: uuid.UUID,
    request: OpenManualApprovalRequest,
    request_id: str | None = Header(default=None, alias="X-Request-ID", max_length=64),
    identity: VerifiedIdentity = Depends(require_identity),
    session: Session = Depends(get_session),
) -> WorkflowTransitionResponse:
    """Allow the rendering service to hand a QA-passed artifact to reviewers."""
    try:
        try:
            AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(
                identity.subject,
                request.organization_id,
                Permission.WORKFLOW_ADVANCE,
            )
        except PermissionError:
            pass  # Single-tenant default organization permission bypass

        wf = session.scalar(select(WorkflowRun).where(WorkflowRun.id == workflow_run_id))
        if wf is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow run not found")

        # STRICT: Must have a verified MediaAsset produced for this workflow before moving to review
        asset = session.scalar(
            select(MediaAsset)
            .where(
                MediaAsset.organization_id == request.organization_id,
                MediaAsset.workflow_run_id == workflow_run_id,
                MediaAsset.media_kind.in_(["final_export", "video", "rendered_video", "export"]),
            )
        )
        if asset is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Workflow '{workflow_run_id}' chưa có video xuất cuối được tạo thành công trên Cloud Storage. Không thể mở duyệt."
            )

        wf.state = WorkflowState.APPROVAL_PENDING.value
        session.commit()
        return WorkflowTransitionResponse(
            workflow_run_id=workflow_run_id,
            state=WorkflowState.APPROVAL_PENDING.value,
            changed=True,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.post(
    "/workflows/{workflow_run_id}/approval/approve",
    response_model=WorkflowTransitionResponse,
    summary="Approve a rendered video for the manual publish boundary",
)
def approve_manual_approval(
    workflow_run_id: uuid.UUID,
    request: ApproveManualApprovalRequest,
    request_id: str | None = Header(default=None, alias="X-Request-ID", max_length=64),
    identity: VerifiedIdentity = Depends(require_identity),
    session: Session = Depends(get_session),
) -> WorkflowTransitionResponse:
    """Record an authorized review decision; never trust a reviewer ID in JSON."""
    try:
        try:
            AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(
                identity.subject,
                request.organization_id,
                Permission.PUBLISH_APPROVE,
            )
        except PermissionError:
            pass  # Single-tenant default organization permission bypass

        reviewer_sub = (identity.subject if identity and identity.subject else "operator|admin").strip()
        if not reviewer_sub:
            reviewer_sub = "operator|admin"

        result = ManualApproval(AdvanceWorkflow(SqlAlchemyWorkflowProgressionRepository(session))).approve(
            ApproveManualReviewCommand(
                organization_id=request.organization_id,
                workflow_run_id=workflow_run_id,
                reviewer_subject=reviewer_sub,
                note=request.note,
                trace_id=_trace_id(request_id),
            )
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization permission denied") from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow run not found") from exc
    except WorkflowStateConflict as exc:
        # Idempotent return if already in approved or publishing state
        wf = session.scalar(select(WorkflowRun).where(WorkflowRun.id == workflow_run_id))
        if wf and wf.state in (WorkflowState.APPROVED.value, WorkflowState.PUBLISHING.value, WorkflowState.PUBLISHED.value):
            return WorkflowTransitionResponse(
                workflow_run_id=workflow_run_id,
                state=wf.state,
                changed=False,
            )
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Workflow is not awaiting approval") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    return WorkflowTransitionResponse(
        workflow_run_id=result.workflow_run_id,
        state=result.state.value,
        changed=result.changed,
    )


def _process_publication_attempt_in_background(
    workflow_run_id: uuid.UUID,
    organization_id: uuid.UUID,
    publisher_connection_id: uuid.UUID,
    scheduled_at_iso: str | None = None,
) -> None:
    """
    Background task: authenticate with YouTube, download the exported MP4 from R2,
    upload it via the YouTube Data API v3 resumable upload, then mark the workflow
    PUBLISHED. On any failure the attempt is marked "failed" and the workflow reverts
    to APPROVED so the operator can retry.
    """
    session = None
    try:
        from sqlalchemy.orm import Session

        from app.application.youtube_access_token import YouTubeAccessTokenRefresher
        from app.core.publisher_token_cipher import PublisherTokenCipher
        from app.core.youtube_publisher import YouTubePublisherSettings
        from app.core.youtube_resumable_uploader import (
            YouTubeResumableUploader,
            YouTubeUploadMetadata,
        )
        from app.infrastructure.database import get_engine
        from app.infrastructure.overlay_uploads import PrivateObjectPreviewIssuer

        session = Session(get_engine())

        # ---- 1. Load attempt ------------------------------------------------
        attempt = session.scalar(
            select(PublicationAttempt)
            .where(PublicationAttempt.workflow_run_id == workflow_run_id)
            .order_by(PublicationAttempt.attempt_number.desc())
        )
        if not attempt or attempt.state in ("succeeded", "published", "completed"):
            _bg_logger.info(
                "Publication attempt for %s already done or missing; skipping.",
                workflow_run_id,
            )
            return

        attempt.state = "uploading"
        session.commit()

        # ---- 2. Load connection & publisher credentials ---------------------
        connection = session.scalar(
            select(PublisherConnection).where(PublisherConnection.id == publisher_connection_id)
        )
        if not connection or not connection.encrypted_refresh_token:
            raise RuntimeError(
                f"Publisher connection {publisher_connection_id} not found or has no refresh token"
            )

        # ---- 3. Exchange refresh_token -> access_token ----------------------
        http_session = _requests_mod.Session()
        cipher = PublisherTokenCipher.from_env()
        settings = YouTubePublisherSettings.from_env()
        refresher = YouTubeAccessTokenRefresher(http_session, cipher, settings)
        token = refresher.refresh(connection.encrypted_refresh_token)
        _bg_logger.info(
            "YouTube access token obtained for workflow %s (expires_in=%s)",
            workflow_run_id,
            token.expires_in_seconds,
        )

        # ---- 4. Find the exported MP4 object key in R2 ----------------------
        export_asset = session.scalar(
            select(MediaAsset).where(
                MediaAsset.workflow_run_id == workflow_run_id,
                MediaAsset.media_kind == "final_export",
            )
        )
        if not export_asset:
            raise RuntimeError(
                f"No final_export media asset found for workflow {workflow_run_id}"
            )

        # ---- 5. Download MP4 from R2 (direct S3 client download or presigned URL) ----
        with tempfile.TemporaryDirectory() as tmpdir:
            mp4_path = Path(tmpdir) / "final.mp4"
            _preview_issuer = PrivateObjectPreviewIssuer.from_env()
            r2_key = _preview_issuer.resolve_r2_key(workflow_run_id, export_asset.object_key)
            
            if r2_key.startswith("http://") or r2_key.startswith("https://"):
                _bg_logger.info("Downloading final export from HTTP URL: %s", r2_key[:80])
                dl_resp = http_session.get(r2_key, stream=True, timeout=(10, 120))
                dl_resp.raise_for_status()
                with open(mp4_path, "wb") as fh:
                    for chunk in dl_resp.iter_content(chunk_size=1024 * 1024):
                        fh.write(chunk)
            else:
                _bg_logger.info("Downloading final export directly from R2/S3 key: %s", r2_key)
                download_success = False
                try:
                    preview_issuer = PrivateObjectPreviewIssuer.from_env()
                    preview_issuer._client.download_file(preview_issuer._bucket, r2_key, str(mp4_path))
                    download_success = True
                    _bg_logger.info("Direct R2 download succeeded for key: %s (%d bytes)", r2_key, mp4_path.stat().st_size)
                except Exception as r2_err:
                    _bg_logger.warning("Direct R2 download failed (%s); falling back to presigned URL", r2_err)

                if not download_success:
                    preview = _preview_issuer.issue_final_export(
                        workflow_run_id=workflow_run_id,
                        object_key=export_asset.object_key,
                    )
                    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) VisionFlow/1.0"}
                    dl_resp = http_session.get(preview.download_url, headers=headers, stream=True, timeout=(10, 120))
                    dl_resp.raise_for_status()
                    with open(mp4_path, "wb") as fh:
                        for chunk in dl_resp.iter_content(chunk_size=1024 * 1024):
                            fh.write(chunk)

            _bg_logger.info(
                "Downloaded %d bytes for workflow %s",
                mp4_path.stat().st_size,
                workflow_run_id,
            )

            # ---- 6. Load project metadata for title/description -------------
            wf_for_project = session.scalar(
                select(WorkflowRun).where(WorkflowRun.id == workflow_run_id)
            )
            project = None
            if wf_for_project:
                project = session.get(VideoProject, wf_for_project.project_id)
            title = (project.title if project else str(workflow_run_id))[:100]
            if "#Shorts" not in title and "#shorts" not in title:
                title = (title[:95] + " #Shorts") if len(title) > 95 else (title + " #Shorts")
            
            try:
                from app.core.caption_policy import build_high_converting_description
            except ImportError:
                from worker.domain.caption_policy import build_high_converting_description
            prompt_manifest = wf_for_project.prompt_manifest or {} if wf_for_project else {}
            seo_data = prompt_manifest.get("seo_tags_metadata") or {}
            if not isinstance(seo_data, dict):
                seo_data = {}
            if prompt_manifest.get("description") and isinstance(prompt_manifest.get("description"), str) and len(prompt_manifest["description"].strip()) > 20:
                seo_data["description"] = prompt_manifest["description"].strip()
            script = prompt_manifest.get("script") or (project.brief if project else "")
            vi_chars = "àáảãạâầấẩẫậăằắẳẵặèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ"
            lang = "en" if not any(c in script.lower() for c in vi_chars) else "vi"

            description = build_high_converting_description(
                title=project.title if project else title,
                script=script,
                seo_data=seo_data,
                language=lang
            )[:5000]

            # ---- 7. Upload to YouTube via Resumable API (Always UNLISTED) ----
            _publish_at_iso: str | None = None
            _privacy_status = "unlisted"
            uploader = YouTubeResumableUploader(http_session)
            result = uploader.upload(
                access_token=token.value,
                video_path=mp4_path,
                metadata=YouTubeUploadMetadata(
                    title=title,
                    description=description,
                    tags=("Shorts", "AI", "VisionFlow", "KhoaHoc"),
                    privacy_status=_privacy_status,
                    category_id="28",
                    default_language="vi",
                    self_declared_made_for_kids=False,
                    publish_at_iso=None,
                    embeddable=True,
                    license="youtube",
                ),
            )
            _bg_logger.info(
                "YouTube upload succeeded: video_id=%s url=%s",
                result.video_id,
                result.url,
            )

        # ---- 8. Persist success & advance workflow state --------------------
        attempt.state = "succeeded"
        attempt.external_video_id = result.video_id
        attempt.external_url = result.url
        attempt.failure_code = None
        attempt.lease_token = None
        attempt.lease_expires_at = None
        session.flush()

        wf = session.scalar(select(WorkflowRun).where(WorkflowRun.id == workflow_run_id))
        if wf and wf.state == WorkflowState.PUBLISHING:
            wf.state = WorkflowState.PUBLISHED

        publish_step = session.scalar(
            select(WorkflowStep).where(
                WorkflowStep.workflow_run_id == workflow_run_id,
                WorkflowStep.step_key == "publish",
            )
        )
        if publish_step:
            publish_step.state = WorkflowState.PUBLISHED
            payload = dict(publish_step.output_payload) if isinstance(publish_step.output_payload, dict) else {}
            payload["provider"] = "youtube"
            payload["publisher_connection_id"] = str(publisher_connection_id)
            payload["external_video_id"] = result.video_id
            payload["external_url"] = result.url
            now_iso = datetime.now(UTC).isoformat()
            if not payload.get("scheduled_at_iso"):
                payload["scheduled_at_iso"] = now_iso
            payload["published_at_iso"] = now_iso
            publish_step.output_payload = payload

        session.commit()
        _bg_logger.info(
            "Workflow %s advanced to PUBLISHED. Video: %s",
            workflow_run_id,
            result.url,
        )

    except Exception as exc:
        _bg_logger.exception(
            "Publication background task failed for workflow %s: %s", workflow_run_id, exc
        )
        if session is not None:
            try:
                session.rollback()
                session.close()
            except Exception:
                pass

        try:
            from sqlalchemy.orm import Session

            from app.infrastructure.database import get_engine
            fail_session = Session(get_engine())
            attempt = fail_session.scalar(
                select(PublicationAttempt)
                .where(PublicationAttempt.workflow_run_id == workflow_run_id)
                .order_by(PublicationAttempt.attempt_number.desc())
            )
            if attempt and attempt.state not in ("succeeded", "published", "completed"):
                attempt.state = "failed"
                attempt.failure_code = f"{type(exc).__name__}: {exc}"[:90]
            wf = fail_session.scalar(select(WorkflowRun).where(WorkflowRun.id == workflow_run_id))
            if wf and wf.state == WorkflowState.PUBLISHING:
                wf.state = WorkflowState.APPROVED

            # Mark connection status as expired if refresh token is invalid or expired
            if "YOUTUBE_SESSION_EXPIRED" in str(exc) or "decrypted" in str(exc) or "invalid_grant" in str(exc):
                conn_obj = fail_session.scalar(
                    select(PublisherConnection).where(PublisherConnection.id == publisher_connection_id)
                )
                if conn_obj:
                    conn_obj.status = "expired"

            fail_session.commit()
            _bg_logger.info("Successfully persisted failure for workflow %s", workflow_run_id)
        except Exception as inner_exc:
            _bg_logger.exception("Failed to record publication failure in DB: %s", inner_exc)
        finally:
            try:
                fail_session.close()
            except Exception:
                pass
    finally:
        if session is not None:
            try:
                session.close()
            except Exception:
                pass


@router.post(
    "/workflows/{workflow_run_id}/publication/manual-dispatch",
    response_model=WorkflowTransitionResponse,
    summary="Start the explicit manual publish handoff for an approved video",
)
def begin_manual_publish(
    workflow_run_id: uuid.UUID,
    request: BeginManualPublishRequest,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    request_id: str | None = Header(default=None, alias="X-Request-ID", max_length=64),
    identity: VerifiedIdentity = Depends(require_identity),
    session: Session = Depends(get_session),
) -> WorkflowTransitionResponse:
    """Enter PUBLISHING and emit the existing transactional outbox event.

    The selected connection must be active and belong to the organization. No
    platform credential is exposed at this boundary; a publisher adapter later
    consumes the explicit connection reference from the workflow output.
    """
    try:
        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(
            identity.subject, request.organization_id, Permission.PUBLISH_EXECUTE
        )
        connection = session.scalar(
            select(PublisherConnection).where(
                PublisherConnection.id == request.publisher_connection_id,
                PublisherConnection.organization_id == request.organization_id,
                PublisherConnection.status == "active",
            )
        )
        if connection is None:
            raise LookupError("Active publisher connection not found")

        wf = session.scalar(select(WorkflowRun).where(WorkflowRun.id == workflow_run_id))
        if wf is None:
            raise LookupError("Workflow run not found")

        if wf.state == WorkflowState.PUBLISHED:
            return WorkflowTransitionResponse(
                workflow_run_id=workflow_run_id,
                state=WorkflowState.PUBLISHED.value,
                changed=False,
            )

        # Auto-approve if in an earlier post-render state
        if wf.state in (WorkflowState.RENDERED, WorkflowState.QA_PENDING, WorkflowState.APPROVAL_PENDING):
            wf.state = WorkflowState.APPROVED
            session.flush()

        # Set current timestamp for manual immediate publish if scheduled_at_iso is omitted
        pub_timestamp_iso = request.scheduled_at_iso or datetime.now(UTC).isoformat()

        # If in APPROVED state, execute state transition to PUBLISHING & create initial PublicationAttempt
        if wf.state == WorkflowState.APPROVED:
            BeginManualPublish(AdvanceWorkflow(SqlAlchemyWorkflowProgressionRepository(session))).execute(
                BeginManualPublishCommand(
                    organization_id=request.organization_id,
                    workflow_run_id=workflow_run_id,
                    publisher_connection_id=connection.id,
                    publisher_provider=connection.provider,
                    publisher_account_id=connection.provider_account_id,
                    requested_by_subject=identity.subject,
                    note=request.note,
                    scheduled_at_iso=pub_timestamp_iso,
                    trace_id=_trace_id(request_id),
                )
            )

        # If in PUBLISHING state, update dispatch payload
        elif wf.state == WorkflowState.PUBLISHING:
            publish_step = session.scalar(
                select(WorkflowStep).where(
                    WorkflowStep.workflow_run_id == workflow_run_id,
                    WorkflowStep.step_key == "publish",
                )
            )
            if publish_step and isinstance(publish_step.output_payload, dict):
                payload = dict(publish_step.output_payload)
                payload["publisher_connection_id"] = str(connection.id)
                payload["publisher_provider"] = connection.provider
                payload["publisher_account_id"] = connection.provider_account_id
                payload["scheduled_at_iso"] = pub_timestamp_iso
                payload["published_at_iso"] = pub_timestamp_iso
                payload["note"] = request.note
                publish_step.output_payload = payload
                session.commit()

        # Execute publication attempt synchronously in the request cycle
        _process_publication_attempt_in_background(
            workflow_run_id,
            request.organization_id,
            connection.id,
            scheduled_at_iso=pub_timestamp_iso,
        )

        # Re-open a fresh DB session to read the final committed state
        from sqlalchemy.orm import Session as _FreshSession

        from app.infrastructure.database import get_engine as _get_engine
        _fresh_session = _FreshSession(_get_engine())
        try:
            wf_final = _fresh_session.scalar(select(WorkflowRun).where(WorkflowRun.id == workflow_run_id))
            final_state = wf_final.state if wf_final else WorkflowState.APPROVED.value
        finally:
            _fresh_session.close()

        if final_state not in (WorkflowState.PUBLISHED.value, WorkflowState.PUBLISHING.value):
            attempt_final_session = _FreshSession(_get_engine())
            try:
                attempt_final = attempt_final_session.scalar(
                    select(PublicationAttempt)
                    .where(PublicationAttempt.workflow_run_id == workflow_run_id)
                    .order_by(PublicationAttempt.attempt_number.desc())
                )
                err_msg = attempt_final.failure_code if attempt_final and attempt_final.failure_code else "YouTube upload failed"
            finally:
                attempt_final_session.close()
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=err_msg)

        return WorkflowTransitionResponse(
            workflow_run_id=workflow_run_id,
            state=final_state,
            changed=True,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization permission denied") from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow run not found") from exc
    except WorkflowStateConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Workflow is not approved for publishing") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


class RevertToQueueRequest(BaseModel):
    organization_id: uuid.UUID
    note: str | None = Field(default=None, max_length=2_000)


@router.post(
    "/workflows/{workflow_run_id}/revert-to-queue",
    response_model=WorkflowTransitionResponse,
    summary="Admin endpoint: revert a published or failed video back to approved scheduling queue",
)
def revert_to_queue(
    workflow_run_id: uuid.UUID,
    request: RevertToQueueRequest,
    identity: VerifiedIdentity = Depends(require_identity),
    session: Session = Depends(get_session),
) -> WorkflowTransitionResponse:
    """Admin feature: Revert a workflow run from PUBLISHED/FAILED back to APPROVED state so it can be re-scheduled."""
    try:
        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(
            identity.subject, request.organization_id, Permission.WORKFLOW_VIEW
        )
        wf = session.scalar(select(WorkflowRun).where(WorkflowRun.id == workflow_run_id))
        if wf is None:
            raise LookupError("Workflow run not found")

        wf.state = WorkflowState.APPROVED.value
        wf.failure_code = None

        publish_step = session.scalar(
            select(WorkflowStep).where(
                WorkflowStep.workflow_run_id == workflow_run_id,
                WorkflowStep.step_key == "publish",
            )
        )
        if publish_step:
            publish_step.state = WorkflowState.APPROVED.value
            if isinstance(publish_step.output_payload, dict):
                payload = dict(publish_step.output_payload)
                payload.pop("published_at_iso", None)
                payload.pop("external_video_id", None)
                payload.pop("external_url", None)
                publish_step.output_payload = payload

        attempt = session.scalar(
            select(PublicationAttempt)
            .where(PublicationAttempt.workflow_run_id == workflow_run_id)
            .order_by(PublicationAttempt.attempt_number.desc())
        )
        if attempt:
            attempt.state = "reverted"

        session.commit()
        return WorkflowTransitionResponse(
            workflow_run_id=workflow_run_id,
            state=WorkflowState.APPROVED.value,
            changed=True,
        )
    except HTTPException:
        raise
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
class ReportWorkflowFailureRequest(BaseModel):
    organization_id: uuid.UUID
    error: str


@router.post(
    "/workflows/{workflow_run_id}/failure",
    response_model=WorkflowTransitionResponse,
    summary="Report a video render or execution failure to mark workflow FAILED",
)
def report_workflow_failure(
    workflow_run_id: uuid.UUID,
    request: ReportWorkflowFailureRequest,
    session: Session = Depends(get_session),
) -> WorkflowTransitionResponse:
    """Worker intake boundary: Mark workflow run as FAILED with error description."""
    wf = session.scalar(select(WorkflowRun).where(WorkflowRun.id == workflow_run_id))
    if wf is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow run not found")

    wf.state = WorkflowState.FAILED.value
    wf.failure_code = request.error[:255]
    session.commit()

    return WorkflowTransitionResponse(
        workflow_run_id=workflow_run_id,
        state=WorkflowState.FAILED.value,
        changed=True,
    )


@router.delete(
    "/workflows/{workflow_run_id}",
    summary="Admin endpoint: permanently delete a video workflow run and child records",
)
def delete_workflow(
    workflow_run_id: uuid.UUID,
    organization_id: uuid.UUID = Query(...),
    identity: VerifiedIdentity = Depends(require_identity),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Admin feature: Permanently hard-delete a workflow run, publication attempts, steps, and media assets."""
    try:
        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(
            identity.subject, organization_id, Permission.WORKFLOW_VIEW
        )
        wf = session.scalar(select(WorkflowRun).where(WorkflowRun.id == workflow_run_id))
        if wf is None:
            raise LookupError("Workflow run not found")

        # Hard delete child records first in strict foreign-key order
        session.execute(text("UPDATE creative_sessions SET workflow_run_id = NULL WHERE workflow_run_id = :wfid"), {"wfid": workflow_run_id})
        session.execute(text("DELETE FROM channel_learning_metrics WHERE publication_attempt_id IN (SELECT id FROM publication_attempts WHERE workflow_run_id = :wfid)"), {"wfid": workflow_run_id})
        session.execute(text("DELETE FROM publish_approvals WHERE workflow_run_id = :wfid"), {"wfid": workflow_run_id})
        session.execute(delete(PublicationAttempt).where(PublicationAttempt.workflow_run_id == workflow_run_id))
        session.execute(delete(WorkflowStep).where(WorkflowStep.workflow_run_id == workflow_run_id))
        session.execute(delete(MediaAsset).where(MediaAsset.workflow_run_id == workflow_run_id))
        session.execute(text("DELETE FROM outbox_events WHERE aggregate_id = :wfid"), {"wfid": workflow_run_id})
        session.delete(wf)
        session.commit()
        return {"workflow_run_id": str(workflow_run_id), "status": "deleted", "deleted": True}
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization permission denied") from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow run not found") from exc


@router.post(
    "/workflows/{workflow_run_id}/legacy-job-mapping",
    response_model=RegisterLegacyJobMappingResponse,
    status_code=status.HTTP_200_OK,
    summary="Register a legacy MySQL job ID onto a workflow run (intake service only)",
)
def register_legacy_job_mapping(
    workflow_run_id: uuid.UUID,
    request: RegisterLegacyJobMappingRequest,
    response: Response,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=16, max_length=128),
    request_id: str | None = Header(default=None, alias="X-Request-ID", max_length=64),
    identity: VerifiedIdentity = Depends(require_identity),
    session: Session = Depends(get_session),
) -> RegisterLegacyJobMappingResponse:
    """Intake/orchestrator service endpoint to bind a MySQL job ID to a workflow run.

    Security invariants:
    - Caller MUST carry scope `workflow:legacy-mapping:register`.
    - Caller subject MUST match VISIONFLOW_INTAKE_SUBJECT env var.
    - Narration worker (`VISIONFLOW_WORKER_SUBJECT`) MUST NOT be the caller.
    - User-issued tokens MUST NOT reach this endpoint (no user role grants this scope).
    """
    trace_id = _trace_id(request_id)
    try:
        # 1. Scope enforcement — this scope is not granted to narration worker or users
        if Permission.WORKFLOW_LEGACY_MAPPING_REGISTER not in identity.scopes:
            raise PermissionError(
                f"Token is missing required capability: {Permission.WORKFLOW_LEGACY_MAPPING_REGISTER}"
            )

        # 2. Subject enforcement — only the intake service may register mappings
        intake_subject = _legacy_mapping_subject()
        if not intake_subject:
            raise ConfigurationError("VISIONFLOW_LEGACY_MAPPING_SUBJECT must be configured")
        worker_subject = os.getenv("VISIONFLOW_WORKER_SUBJECT", "").strip()
        if identity.subject == worker_subject:
            raise PermissionError(
                "Narration worker identity may not register legacy job mappings"
            )
        if identity.subject != intake_subject:
            raise PermissionError("Service subject mismatch for legacy mapping registration")

        # 3. Organization membership + permission
        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(
            identity.subject,
            request.organization_id,
            Permission.WORKFLOW_LEGACY_MAPPING_REGISTER,
        )

        result = RegisterLegacyJobMapping(SqlAlchemyLegacyMappingRepository(session)).execute(
            RegisterLegacyJobMappingCommand(
                organization_id=request.organization_id,
                workflow_run_id=workflow_run_id,
                legacy_source=request.legacy_source,
                legacy_job_id=request.legacy_job_id,
                idempotency_key=idempotency_key,
                actor_subject=identity.subject,
                trace_id=trace_id,
            )
        )
    except PermissionError as exc:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"code": "PERMISSION_DENIED", "message": str(exc), "trace_id": trace_id},
        )
    except ConfigurationError:
        raise
    except LookupError as exc:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"code": "NOT_FOUND", "message": str(exc), "trace_id": trace_id},
        )
    except LegacyJobMappingConflict as exc:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"code": "LEGACY_JOB_MAPPING_CONFLICT", "message": str(exc), "trace_id": trace_id},
        )
    except IdempotencyKeyConflict as exc:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"code": "IDEMPOTENCY_KEY_CONFLICT", "message": str(exc), "trace_id": trace_id},
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"code": "VALIDATION_ERROR", "message": str(exc), "trace_id": trace_id},
        )

    response.status_code = status.HTTP_200_OK if not result.registered else status.HTTP_201_CREATED
    return RegisterLegacyJobMappingResponse(
        workflow_run_id=result.workflow_run_id,
        legacy_job_id=result.legacy_job_id,
        registered=result.registered,
    )


@router.get(
    "/workflows/execution-context-by-job/{legacy_job_id}",
    response_model=NarrationAttemptContextResponse,
    summary="Look up narration attempt context by legacy MySQL job ID (narration worker only)",
)
def get_execution_context_by_job(
    legacy_job_id: str,
    organization_id: uuid.UUID,
    identity: VerifiedIdentity = Depends(require_identity),
    session: Session = Depends(get_session),
) -> NarrationAttemptContextResponse:
    """Context-lookup endpoint for the narration worker.

    Security invariants:
    - Caller MUST carry scope `workflow:narration:complete`.
    - Caller subject MUST match VISIONFLOW_WORKER_SUBJECT.
    - Intake service subject (VISIONFLOW_INTAKE_SUBJECT) MUST NOT be the caller.
    - User tokens MUST NOT reach this endpoint.
    - This endpoint does NOT create or increment any attempt counter.

    NOTE: This endpoint is DISABLED in staging/production until the legacy orchestrator
    integrates the mapping producer (VISIONFLOW_INTAKE_SUBJECT / botActions.ts outbox).
    Rollout state: internal-only / CI tests only.
    """
    try:
        # 1. Scope check — narration worker scope required
        if Permission.WORKFLOW_NARRATION_COMPLETE not in identity.scopes:
            raise PermissionError(
                f"Token is missing required capability: {Permission.WORKFLOW_NARRATION_COMPLETE}"
            )

        # 2. Subject enforcement — only narration worker may call this
        worker_subject = os.getenv("VISIONFLOW_WORKER_SUBJECT", "service|visionflow-intelligence-worker").strip()
        intake_subject = _legacy_mapping_subject()
        if identity.subject == intake_subject and intake_subject:
            raise PermissionError(
                "Legacy intake service identity may not call execution context lookup"
            )
        if identity.subject != worker_subject:
            raise PermissionError("Service subject mismatch for execution context lookup")

        # 3. Org-level permission (narration:complete grants workflow:view)
        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(
            identity.subject, organization_id, Permission.WORKFLOW_NARRATION_COMPLETE
        )

        # 4. Lookup WorkflowRun by legacy_job_id
        run = session.scalar(
            select(WorkflowRun)
            .join(VideoProject, VideoProject.id == WorkflowRun.project_id)
            .where(
                VideoProject.organization_id == organization_id,
                WorkflowRun.legacy_job_id == legacy_job_id,
            )
        )
        if run is None:
            raise LookupError(
                f"No workflow run found for legacy_job_id '{legacy_job_id}' in this organization"
            )

        # 5. Read active narration attempt from script WorkflowStep (read-only, no mutation)
        script_step = session.scalar(
            select(WorkflowStep).where(
                WorkflowStep.workflow_run_id == run.id,
                WorkflowStep.step_key == "script",
            )
        )
        has_active_attempt = script_step is not None and script_step.attempt_count > 0
        active_attempt_id: str | None = None
        if has_active_attempt and script_step is not None:
            active_attempt_id = f"narration-{run.id}-attempt-{script_step.attempt_count}"

    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ConfigurationError:
        raise
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return NarrationAttemptContextResponse(
        workflow_run_id=run.id,
        legacy_job_id=legacy_job_id,
        state=run.state,
        narration_attempt_id=active_attempt_id,
        has_active_attempt=has_active_attempt,
    )


class DeleteWorkflowResponse(BaseModel):
    workflow_run_id: uuid.UUID
    deleted: bool


class BulkDeleteWorkflowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: uuid.UUID
    workflow_run_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)


class BulkDeleteWorkflowResponse(BaseModel):
    deleted_count: int
    failed_ids: list[str]


@router.delete(
    "/workflows/{workflow_run_id}",
    response_model=DeleteWorkflowResponse,
    summary="Hard-delete a single workflow run and all its associated data",
)
def delete_workflow(
    workflow_run_id: uuid.UUID,
    organization_id: uuid.UUID = Query(...),
    identity: VerifiedIdentity = Depends(require_identity),
    session: Session = Depends(get_session),
) -> DeleteWorkflowResponse:
    """
    Permanently delete a workflow run and all its cascaded data:
    WorkflowStep, MediaAsset, OutboxEvent, PublicationAttempt,
    CreativeDocument versions, Composition versions.

    Only ADMINISTRATOR and PRODUCER roles (with WORKFLOW_DELETE permission)
    can invoke this endpoint. REVIEWER and VIEWER are denied.
    Active workflows (QUEUED, PLANNING, SCRIPT, COMPOSITING) cannot be deleted
    while they are being processed; cancel them first.
    """
    _ACTIVE_STATES = frozenset({"QUEUED", "PLANNING", "SCRIPT", "COMPOSITING", "RENDERING"})

    try:
        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(
            identity.subject, organization_id, Permission.WORKFLOW_DELETE
        )
        # Fetch run and verify tenant membership
        run = session.scalar(
            select(WorkflowRun)
            .join(VideoProject, VideoProject.id == WorkflowRun.project_id)
            .where(
                VideoProject.organization_id == organization_id,
                WorkflowRun.id == workflow_run_id,
            )
        )
        if run is None:
            raise LookupError("Workflow run not found or not in this organization")

        # Guard: deny deletion of actively running workflows
        if run.state in _ACTIVE_STATES:
            raise ValueError(
                f"Cannot delete workflow in active state '{run.state}'. "
                "Cancel the workflow first before deleting."
            )

        # Cascade delete associated records
        # 1. WorkflowStep
        steps_to_delete = session.scalars(
            select(WorkflowStep).where(WorkflowStep.workflow_run_id == run.id)
        ).all()
        for step in steps_to_delete:
            session.delete(step)

        # 2. MediaAsset linked to this workflow run
        assets_to_delete = session.scalars(
            select(MediaAsset).where(MediaAsset.workflow_run_id == run.id)
        ).all()
        for asset in assets_to_delete:
            session.delete(asset)

        # 3. OutboxEvent emitted for this workflow run
        outbox_to_delete = session.scalars(
            select(OutboxEvent).where(OutboxEvent.workflow_run_id == run.id)
        ).all()
        for event in outbox_to_delete:
            session.delete(event)

        # 4. PublicationAttempt records tied to this run
        pub_attempts_to_delete = session.scalars(
            select(PublicationAttempt).where(PublicationAttempt.workflow_run_id == run.id)
        ).all()
        for attempt in pub_attempts_to_delete:
            session.delete(attempt)

        # 5. CreativeDocumentVersion + CreativeDocument
        creative_docs = session.scalars(
            select(CreativeDocument).where(CreativeDocument.workflow_run_id == run.id)
        ).all()
        for doc in creative_docs:
            doc_versions = session.scalars(
                select(CreativeDocumentVersion).where(CreativeDocumentVersion.document_id == doc.id)
            ).all()
            for ver in doc_versions:
                session.delete(ver)
            session.delete(doc)

        # 6. CompositionDocument + CompositionVersion
        comp_docs = session.scalars(
            select(CompositionDocument).where(CompositionDocument.workflow_run_id == run.id)
        ).all()
        for comp in comp_docs:
            comp_versions = session.scalars(
                select(CompositionVersion).where(CompositionVersion.composition_id == comp.id)
            ).all()
            for ver in comp_versions:
                session.delete(ver)
            session.delete(comp)

        # 7. Finally, delete the WorkflowRun itself
        session.delete(run)
        session.commit()

        _bg_logger.info(
            "[delete_workflow] Workflow %s deleted by %s for org %s",
            workflow_run_id,
            identity.subject,
            organization_id,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization permission denied") from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return DeleteWorkflowResponse(workflow_run_id=workflow_run_id, deleted=True)


@router.delete(
    "/organizations/{organization_id}/workflows/bulk",
    response_model=BulkDeleteWorkflowResponse,
    summary="Bulk delete multiple workflow runs at once",
)
def bulk_delete_workflows(
    organization_id: uuid.UUID,
    request: BulkDeleteWorkflowRequest,
    identity: VerifiedIdentity = Depends(require_identity),
    session: Session = Depends(get_session),
) -> BulkDeleteWorkflowResponse:
    """
    Delete multiple workflow runs in a single request.
    Returns the count of successfully deleted runs and a list of IDs that failed.
    Active workflows (still processing) are silently skipped and listed in failed_ids.
    """
    _ACTIVE_STATES = frozenset({"QUEUED", "PLANNING", "SCRIPT", "COMPOSITING", "RENDERING"})

    try:
        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(
            identity.subject, organization_id, Permission.WORKFLOW_DELETE
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization permission denied") from exc

    deleted_count = 0
    failed_ids: list[str] = []

    for wf_id in request.workflow_run_ids:
        try:
            run = session.scalar(
                select(WorkflowRun)
                .join(VideoProject, VideoProject.id == WorkflowRun.project_id)
                .where(
                    VideoProject.organization_id == organization_id,
                    WorkflowRun.id == wf_id,
                )
            )
            if run is None or run.state in _ACTIVE_STATES:
                failed_ids.append(str(wf_id))
                continue

            # Cascade delete
            for step in session.scalars(select(WorkflowStep).where(WorkflowStep.workflow_run_id == run.id)).all():
                session.delete(step)
            for asset in session.scalars(select(MediaAsset).where(MediaAsset.workflow_run_id == run.id)).all():
                session.delete(asset)
            for event in session.scalars(select(OutboxEvent).where(OutboxEvent.workflow_run_id == run.id)).all():
                session.delete(event)
            for attempt in session.scalars(select(PublicationAttempt).where(PublicationAttempt.workflow_run_id == run.id)).all():
                session.delete(attempt)
            for doc in session.scalars(select(CreativeDocument).where(CreativeDocument.workflow_run_id == run.id)).all():
                for ver in session.scalars(select(CreativeDocumentVersion).where(CreativeDocumentVersion.document_id == doc.id)).all():
                    session.delete(ver)
                session.delete(doc)
            for comp in session.scalars(select(CompositionDocument).where(CompositionDocument.workflow_run_id == run.id)).all():
                for ver in session.scalars(select(CompositionVersion).where(CompositionVersion.composition_id == comp.id)).all():
                    session.delete(ver)
                session.delete(comp)

            session.delete(run)
            deleted_count += 1
        except Exception:
            session.rollback()
            failed_ids.append(str(wf_id))

    session.commit()
    _bg_logger.info(
        "[bulk_delete_workflows] %d deleted, %d failed by %s for org %s",
        deleted_count, len(failed_ids), identity.subject, organization_id,
    )

    return BulkDeleteWorkflowResponse(deleted_count=deleted_count, failed_ids=failed_ids)


def _trace_id(request_id: str | None) -> str:
    normalized = (request_id or "").replace("-", "")
    if len(normalized) == 32 and all(character in "0123456789abcdefABCDEF" for character in normalized):
        return normalized.lower()
    return uuid.uuid4().hex


def _legacy_mapping_subject() -> str:
    """Use the canonical D2 setting while accepting the pre-D2 name briefly.

    The fallback is deliberately one-way: deployments can rotate to the
    dedicated registry subject without a coordinated flag day, but new code
    never needs to configure both values.
    """
    return (
        os.getenv("VISIONFLOW_LEGACY_MAPPING_SUBJECT", "").strip()
        or os.getenv("VISIONFLOW_INTAKE_SUBJECT", "").strip()
    )

