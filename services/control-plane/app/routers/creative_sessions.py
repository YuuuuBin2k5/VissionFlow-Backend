from __future__ import annotations

import uuid
from typing import Any
from fastapi import APIRouter, Depends, Query, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from app.core.oidc import VerifiedIdentity
from app.domain.authorization import Permission
from app.application.authorize_organization import AuthorizeOrganization
from app.infrastructure.database import get_session
from app.infrastructure.membership_repository import SqlAlchemyOrganizationMembershipRepository
from app.routers.auth import require_identity
from app.infrastructure.models import CreativeSession

import logging

from app.application.manage_creative_session import (
    ManageCreativeSession,
    CreativeSessionError,
    CreativeSessionConflict,
    CreativeSessionAlreadyBound,
    ProviderRateLimited,
    ProviderUnavailable,
    PromptBaselineUnavailable,
    IdempotencyPayloadMismatch,
)
from app.infrastructure.adapters.gemini_adapter import GeminiCreativePlanningAdapter

router = APIRouter(tags=["creative_sessions"])


# Request models
class CreateSessionRequest(BaseModel):
    creation_spec: dict
    idempotency_key: str = Field(min_length=16, max_length=128)


class UpdateSpecRequest(BaseModel):
    organization_id: uuid.UUID
    expected_revision: int
    idempotency_key: str = Field(min_length=16, max_length=128)
    creation_spec: dict


class SendMessageRequest(BaseModel):
    organization_id: uuid.UUID
    message: str = Field(min_length=1, max_length=10000)
    expected_session_revision: int
    idempotency_key: str = Field(min_length=16, max_length=128)


class CreateProposalRequest(BaseModel):
    organization_id: uuid.UUID
    expected_session_revision: int
    idempotency_key: str = Field(min_length=16, max_length=128)
    title: str = Field(min_length=1, max_length=240)
    brief: str = Field(min_length=1, max_length=50000)
    script: str = Field(min_length=40, max_length=50000)
    scenes: list[dict] = Field(min_length=3, max_length=20)


class AcceptProposalRequest(BaseModel):
    organization_id: uuid.UUID
    expected_revision: int
    idempotency_key: str = Field(min_length=16, max_length=128)


class CreateWorkflowDraftRequest(BaseModel):
    organization_id: uuid.UUID
    accepted_proposal_id: uuid.UUID
    idempotency_key: str = Field(min_length=16, max_length=128)


def _get_manager(session) -> ManageCreativeSession:
    # Use real adapter config falling back to env if enabled
    import os
    env_enabled = os.getenv("VISIONFLOW_GEMINI_ENV_FALLBACK_ENABLED", "false").lower() == "true"
    env_key = os.getenv("GEMINI_API_KEY")
    adapter = GeminiCreativePlanningAdapter()

    # We pass session maker wrapper to the manager service
    from sqlalchemy.orm import sessionmaker
    sm = sessionmaker(bind=session.bind)
    return ManageCreativeSession(
        session_maker=sm,
        provider_adapter=adapter,
        env_fallback_enabled=env_enabled,
        env_fallback_key=env_key,
    )


logger_router = logging.getLogger(__name__)


def _handle_exception(exc: Exception) -> JSONResponse:
    """Helper to map exception categories into RFC 7807 problem responses."""
    # Log 5xx-class exceptions with full detail to surface root cause in Render logs
    if isinstance(exc, (ProviderUnavailable, PromptBaselineUnavailable)):
        logger_router.error(
            "[503] %s: %s", type(exc).__name__, exc, exc_info=True
        )
    if isinstance(exc, ValidationError):
        # `creation_spec` is deliberately validated in the application layer so
        # the same invariant applies to create and update commands.  Convert
        # that safe, expected validation failure into a client error instead of
        # letting it escape as an unhandled 500 (which browsers then report as
        # a misleading CORS failure).
        errors = [
            {
                "field": ".".join(str(part) for part in error["loc"]),
                "message": error["msg"],
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={
                "type": "VALIDATION_ERROR",
                "title": "Validation Error",
                "detail": "The creative session specification is invalid.",
                "errors": errors,
            },
        )
    if isinstance(exc, CreativeSessionAlreadyBound):
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "type": "CREATIVE_SESSION_ALREADY_BOUND",
                "title": "Creative Session Already Bound",
                "detail": str(exc),
            }
        )
    elif isinstance(exc, CreativeSessionConflict):
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "type": "CREATIVE_SESSION_CONFLICT",
                "title": "Creative Session Conflict",
                "detail": str(exc),
            }
        )
    elif isinstance(exc, IdempotencyPayloadMismatch):
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "type": "IDEMPOTENCY_PAYLOAD_MISMATCH",
                "title": "Idempotency Payload Mismatch",
                "detail": str(exc),
            }
        )
    elif isinstance(exc, ProviderRateLimited):
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={
                "type": "PROVIDER_RATE_LIMITED",
                "title": "Provider Rate Limited",
                "detail": str(exc),
            }
        )
    elif isinstance(exc, ProviderUnavailable):
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "type": "PROVIDER_UNAVAILABLE",
                "title": "Provider Unavailable",
                "detail": str(exc),
            }
        )
    elif isinstance(exc, PromptBaselineUnavailable):
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "type": "PROMPT_BASELINE_UNAVAILABLE",
                "title": "Prompt Baseline Unavailable",
                "detail": str(exc),
            }
        )
    elif isinstance(exc, CreativeSessionError):
        logger_router.error("[400] CreativeSessionError: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "type": "BAD_REQUEST",
                "title": "Bad Request",
                "detail": str(exc),
            }
        )

    raise exc


@router.post("/organizations/{organization_id}/creative-sessions")
def create_session(
    organization_id: uuid.UUID,
    body: CreateSessionRequest,
    identity: VerifiedIdentity = Depends(require_identity),
    session=Depends(get_session),
):
    try:
        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(
            identity.subject, organization_id, Permission.WORKFLOW_CREATE
        )
        manager = _get_manager(session)
        sess_id = manager.create_session(
            organization_id=organization_id,
            creation_spec_dict=body.creation_spec,
            idempotency_key=body.idempotency_key,
        )
        return {"session_id": str(sess_id)}
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization permission denied") from exc
    except Exception as exc:
        return _handle_exception(exc)


@router.get("/creative-sessions/{session_id}")
def get_session_details(
    session_id: uuid.UUID,
    organization_id: uuid.UUID = Query(...),
    message_limit: int = Query(default=20, ge=1, le=100),
    message_offset: int = Query(default=0, ge=0),
    proposal_limit: int = Query(default=20, ge=1, le=100),
    proposal_offset: int = Query(default=0, ge=0),
    identity: VerifiedIdentity = Depends(require_identity),
    session=Depends(get_session),
):
    try:
        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(
            identity.subject, organization_id, Permission.WORKFLOW_VIEW
        )
        manager = _get_manager(session)
        res = manager.get_session_details(
            session_id=session_id,
            organization_id=organization_id,
            message_limit=message_limit,
            message_offset=message_offset,
            proposal_limit=proposal_limit,
            proposal_offset=proposal_offset,
        )
        return res
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization permission denied") from exc
    except CreativeSessionError as exc:
        # Cross-tenant mapping protection to hide existences
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Creative session not found.") from exc
    except Exception as exc:
        return _handle_exception(exc)


@router.get("/creative-sessions/{session_id}/proposals/{proposal_id}")
def get_proposal_details(
    session_id: uuid.UUID,
    proposal_id: uuid.UUID,
    organization_id: uuid.UUID = Query(...),
    identity: VerifiedIdentity = Depends(require_identity),
    session=Depends(get_session),
):
    try:
        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(
            identity.subject, organization_id, Permission.WORKFLOW_VIEW
        )
        manager = _get_manager(session)
        res = manager.get_proposal_details(
            session_id=session_id,
            proposal_id=proposal_id,
            organization_id=organization_id,
        )
        return res
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization permission denied") from exc
    except CreativeSessionError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found.") from exc
    except Exception as exc:
        return _handle_exception(exc)


@router.patch("/creative-sessions/{session_id}/creation-spec")
def update_creation_spec(
    session_id: uuid.UUID,
    body: UpdateSpecRequest,
    identity: VerifiedIdentity = Depends(require_identity),
    session=Depends(get_session),
):
    try:
        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(
            identity.subject, body.organization_id, Permission.WORKFLOW_CREATE
        )
        manager = _get_manager(session)
        res = manager.update_creation_spec(
            session_id=session_id,
            organization_id=body.organization_id,
            creation_spec_dict=body.creation_spec,
            expected_revision=body.expected_revision,
            idempotency_key=body.idempotency_key,
        )
        return res
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization permission denied") from exc
    except CreativeSessionError as exc:
        # Check if session exists for tenant mapping lookup, else 404
        sess = session.get(CreativeSession, session_id)
        if not sess or sess.organization_id != body.organization_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Creative session not found.")
        return _handle_exception(exc)
    except Exception as exc:
        return _handle_exception(exc)


@router.post("/creative-sessions/{session_id}/messages")
def send_message(
    session_id: uuid.UUID,
    body: SendMessageRequest,
    identity: VerifiedIdentity = Depends(require_identity),
    session=Depends(get_session),
):
    try:
        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(
            identity.subject, body.organization_id, Permission.WORKFLOW_CREATE
        )
        manager = _get_manager(session)
        res = manager.send_creative_session_message(
            session_id=session_id,
            organization_id=body.organization_id,
            message=body.message,
            expected_session_revision=body.expected_session_revision,
            idempotency_key=body.idempotency_key,
        )
        return res
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization permission denied") from exc
    except CreativeSessionError as exc:
        sess = session.get(CreativeSession, session_id)
        if not sess or sess.organization_id != body.organization_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Creative session not found.")
        return _handle_exception(exc)
    except Exception as exc:
        return _handle_exception(exc)


@router.post("/creative-sessions/{session_id}/proposals")
def create_manual_proposal(
    session_id: uuid.UUID,
    body: CreateProposalRequest,
    identity: VerifiedIdentity = Depends(require_identity),
    session=Depends(get_session),
):
    try:
        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(
            identity.subject, body.organization_id, Permission.WORKFLOW_CREATE
        )
        manager = _get_manager(session)
        proposal_id = manager.create_manual_proposal(
            session_id=session_id,
            organization_id=body.organization_id,
            expected_session_revision=body.expected_session_revision,
            idempotency_key=body.idempotency_key,
            title=body.title,
            brief=body.brief,
            script=body.script,
            scenes=body.scenes,
        )
        return {"proposal_id": str(proposal_id)}
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization permission denied") from exc
    except CreativeSessionError as exc:
        sess = session.get(CreativeSession, session_id)
        if not sess or sess.organization_id != body.organization_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Creative session not found.")
        return _handle_exception(exc)
    except Exception as exc:
        return _handle_exception(exc)


@router.post("/creative-sessions/{session_id}/proposals/{proposal_id}/revisions")
def create_proposal_revision(
    session_id: uuid.UUID,
    proposal_id: uuid.UUID,
    body: CreateProposalRequest,
    identity: VerifiedIdentity = Depends(require_identity),
    session=Depends(get_session),
):
    try:
        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(
            identity.subject, body.organization_id, Permission.WORKFLOW_CREATE
        )
        manager = _get_manager(session)
        rev_id = manager.create_proposal_revision(
            session_id=session_id,
            parent_proposal_id=proposal_id,
            organization_id=body.organization_id,
            expected_session_revision=body.expected_session_revision,
            idempotency_key=body.idempotency_key,
            title=body.title,
            brief=body.brief,
            script=body.script,
            scenes=body.scenes,
        )
        return {"proposal_id": str(rev_id)}
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization permission denied") from exc
    except CreativeSessionError as exc:
        sess = session.get(CreativeSession, session_id)
        if not sess or sess.organization_id != body.organization_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Creative session not found.")
        return _handle_exception(exc)
    except Exception as exc:
        return _handle_exception(exc)


@router.post("/creative-sessions/{session_id}/proposals/{proposal_id}/accept")
def accept_proposal(
    session_id: uuid.UUID,
    proposal_id: uuid.UUID,
    body: AcceptProposalRequest,
    identity: VerifiedIdentity = Depends(require_identity),
    session=Depends(get_session),
):
    try:
        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(
            identity.subject, body.organization_id, Permission.WORKFLOW_CREATE
        )
        manager = _get_manager(session)
        res = manager.accept_proposal(
            session_id=session_id,
            proposal_id=proposal_id,
            organization_id=body.organization_id,
            expected_revision=body.expected_revision,
            idempotency_key=body.idempotency_key,
        )
        return res
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization permission denied") from exc
    except CreativeSessionError as exc:
        sess = session.get(CreativeSession, session_id)
        if not sess or sess.organization_id != body.organization_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Creative session not found.")
        return _handle_exception(exc)
    except Exception as exc:
        return _handle_exception(exc)


@router.post("/creative-sessions/{session_id}/create-workflow-draft")
def create_workflow_draft(
    session_id: uuid.UUID,
    body: CreateWorkflowDraftRequest,
    identity: VerifiedIdentity = Depends(require_identity),
    session=Depends(get_session),
):
    try:
        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(
            identity.subject, body.organization_id, Permission.WORKFLOW_CREATE
        )
        manager = _get_manager(session)
        res = manager.create_workflow_draft_from_session(
            session_id=session_id,
            organization_id=body.organization_id,
            accepted_proposal_id=body.accepted_proposal_id,
            client_idempotency_key=body.idempotency_key,
        )
        return res
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization permission denied") from exc
    except CreativeSessionError as exc:
        sess = session.get(CreativeSession, session_id)
        if not sess or sess.organization_id != body.organization_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Creative session not found.")
        return _handle_exception(exc)
    except Exception as exc:
        return _handle_exception(exc)
