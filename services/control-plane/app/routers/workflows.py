from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.advance_workflow import (
    AdvanceWorkflow,
    AdvanceWorkflowCommand,
    WorkflowStateConflict,
)
from app.application.authorize_organization import AuthorizeOrganization
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
from app.core.oidc import VerifiedIdentity
from app.domain.authorization import Permission
from app.domain.workflow import WorkflowState
from app.infrastructure.database import get_session
from app.infrastructure.membership_repository import SqlAlchemyOrganizationMembershipRepository
from app.infrastructure.repositories import SqlAlchemyShortFormWorkflowRepository
from app.infrastructure.workflow_progression_repository import SqlAlchemyWorkflowProgressionRepository
from app.infrastructure.models import VideoProject, WorkflowRun, WorkflowStep
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


def _trace_id(request_id: str | None) -> str:
    normalized = (request_id or "").replace("-", "")
    if len(normalized) == 32 and all(character in "0123456789abcdefABCDEF" for character in normalized):
        return normalized.lower()
    return uuid.uuid4().hex
