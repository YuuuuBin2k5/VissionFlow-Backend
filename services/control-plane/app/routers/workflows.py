from __future__ import annotations

import os
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.advance_workflow import (
    AdvanceWorkflow,
    AdvanceWorkflowCommand,
    WorkflowStateConflict,
)
from app.application.authorize_organization import AuthorizeOrganization
from app.core.config import ConfigurationError
from app.application.create_short_form import (
    CreateShortFormCommand,
    CreateShortFormWorkflow,
    IdempotencyKeyConflict,
)
from app.application.record_narration_generated import (
    ActiveNarrationAttemptMissing,
    RecordNarrationGenerated,
    RecordNarrationGeneratedCommand,
    SceneCommandPayload,
    SourceMetadataPayload,
    StaleNarrationAttempt,
    WorkflowStateConflict as NarrationWorkflowStateConflict,
    IdempotencyKeyConflict as NarrationIdempotencyKeyConflict,
)
from app.application.register_legacy_job_mapping import (
    LegacyJobMappingConflict,
    LegacyJobMappingResult,
    RegisterLegacyJobMapping,
    RegisterLegacyJobMappingCommand,
)
from app.application.manual_approval import (
    ApproveManualReviewCommand,
    ManualApproval,
    OpenManualApprovalCommand,
)
from app.application.save_creative_draft import SaveCreativeDraft, SaveCreativeDraftCommand
from app.core.oidc import VerifiedIdentity
from app.domain.authorization import Permission
from app.domain.workflow import WorkflowState
from app.infrastructure.database import get_session
from app.infrastructure.creative_draft_repository import SqlAlchemyCreativeDraftRepository
from app.infrastructure.creative_document_repository import (
    CreativeDocumentConflict,
    CreativeDocumentSnapshot,
    SqlAlchemyCreativeDocumentRepository,
)
from app.infrastructure.composition_repository import CompositionConflict, SqlAlchemyCompositionRepository
from app.infrastructure.legacy_mapping_repository import SqlAlchemyLegacyMappingRepository
from app.infrastructure.membership_repository import SqlAlchemyOrganizationMembershipRepository
from app.infrastructure.repositories import (
    SqlAlchemyShortFormWorkflowRepository,
    SqlAlchemyNarrationResultRepository,
)
from app.infrastructure.workflow_progression_repository import SqlAlchemyWorkflowProgressionRepository
from app.infrastructure.models import CompositionDocument, CompositionVersion, CreativeDocument, CreativeDocumentVersion, VideoProject, WorkflowRun, WorkflowStep
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

    model_config = ConfigDict(extra="forbid")

    organization_id: uuid.UUID
    note: str | None = Field(default=None, max_length=2_000)


class WorkflowExecutionContextResponse(BaseModel):
    workflow_run_id: uuid.UUID
    state: str
    intake: dict[str, object]
    steps: dict[str, dict[str, object] | None]


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
        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(
            identity.subject, request.organization_id, Permission.WORKFLOW_CREATE
        )
        snapshot = SqlAlchemyCreativeDocumentRepository(session).lock(
            organization_id=request.organization_id,
            workflow_run_id=workflow_run_id,
            expected_revision=request.expected_revision,
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


@router.put("/workflows/{workflow_run_id}/composition", response_model=dict[str, Any])
def save_composition(
    workflow_run_id: uuid.UUID, request: SaveCompositionRequest,
    identity: VerifiedIdentity = Depends(require_identity), session: Session = Depends(get_session),
) -> dict[str, Any]:
    try:
        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(identity.subject, request.organization_id, Permission.WORKFLOW_CREATE)
        return SqlAlchemyCompositionRepository(session).save(
            organization_id=request.organization_id, workflow_run_id=workflow_run_id,
            expected_revision=request.expected_revision, aspect_ratio=request.aspect_ratio,
            canvas_config=request.canvas_config, tracks=[track.model_dump() for track in request.tracks], actor_subject=identity.subject,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization permission denied") from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except CompositionConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/workflows/{workflow_run_id}/composition/lock", response_model=dict[str, Any])
def lock_composition(
    workflow_run_id: uuid.UUID, request: LockCompositionRequest,
    identity: VerifiedIdentity = Depends(require_identity), session: Session = Depends(get_session),
) -> dict[str, Any]:
    try:
        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(identity.subject, request.organization_id, Permission.WORKFLOW_CREATE)
        return SqlAlchemyCompositionRepository(session).lock(organization_id=request.organization_id, workflow_run_id=workflow_run_id, expected_revision=request.expected_revision)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization permission denied") from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except CompositionConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


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

        expected_subject = os.getenv("VISIONFLOW_WORKER_SUBJECT", "").strip()
        if not expected_subject:
            raise ConfigurationError("VISIONFLOW_WORKER_SUBJECT must be configured")

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
    except ConfigurationError as exc:
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
    except Exception as exc:
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
    request_id: str | None = Header(default=None, alias="X-Request-ID", max_length=64),
    identity: VerifiedIdentity = Depends(require_identity),
    session: Session = Depends(get_session),
) -> WorkflowTransitionResponse:
    """Producer intake boundary: DRAFT -> READY -> QUEUED.

    Producers may submit their own intake but cannot execute arbitrary worker
    transitions; later progress remains restricted to service identities.
    """
    try:
        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(
            identity.subject,
            request.organization_id,
            Permission.WORKFLOW_CREATE,
        )
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
        current_state = WorkflowState(workflow_run.state)
        if current_state == WorkflowState.QUEUED:
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
                output_payload={"submitted_by": identity.subject},
                trace_id=trace_id,
            )
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization permission denied") from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow run not found") from exc
    except WorkflowStateConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Workflow is not ready for submission") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    return WorkflowTransitionResponse(
        workflow_run_id=queued.workflow_run_id,
        state=queued.state.value,
        changed=ready_changed or queued.changed,
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
        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(
            identity.subject,
            request.organization_id,
            Permission.WORKFLOW_ADVANCE,
        )
        result = ManualApproval(AdvanceWorkflow(SqlAlchemyWorkflowProgressionRepository(session))).open(
            OpenManualApprovalCommand(
                organization_id=request.organization_id,
                workflow_run_id=workflow_run_id,
                trace_id=_trace_id(request_id),
            )
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization permission denied") from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow run not found") from exc
    except WorkflowStateConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Workflow is not ready for approval") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    return WorkflowTransitionResponse(
        workflow_run_id=result.workflow_run_id,
        state=result.state.value,
        changed=result.changed,
    )


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
        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(
            identity.subject,
            request.organization_id,
            Permission.PUBLISH_APPROVE,
        )
        result = ManualApproval(AdvanceWorkflow(SqlAlchemyWorkflowProgressionRepository(session))).approve(
            ApproveManualReviewCommand(
                organization_id=request.organization_id,
                workflow_run_id=workflow_run_id,
                reviewer_subject=identity.subject,
                note=request.note,
                trace_id=_trace_id(request_id),
            )
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization permission denied") from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow run not found") from exc
    except WorkflowStateConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Workflow is not awaiting approval") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    return WorkflowTransitionResponse(
        workflow_run_id=result.workflow_run_id,
        state=result.state.value,
        changed=result.changed,
    )


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
        intake_subject = os.getenv("VISIONFLOW_INTAKE_SUBJECT", "").strip()
        if not intake_subject:
            raise ConfigurationError("VISIONFLOW_INTAKE_SUBJECT must be configured")
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
        worker_subject = os.getenv("VISIONFLOW_WORKER_SUBJECT", "").strip()
        if not worker_subject:
            raise ConfigurationError("VISIONFLOW_WORKER_SUBJECT must be configured")
        intake_subject = os.getenv("VISIONFLOW_INTAKE_SUBJECT", "").strip()
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


def _trace_id(request_id: str | None) -> str:
    normalized = (request_id or "").replace("-", "")
    if len(normalized) == 32 and all(character in "0123456789abcdefABCDEF" for character in normalized):
        return normalized.lower()
    return uuid.uuid4().hex
