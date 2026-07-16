from __future__ import annotations

import uuid
import hmac
import secrets
from os import getenv
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import requests
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.authorize_organization import AuthorizeOrganization
from app.application.advance_workflow import AdvanceWorkflow, AdvanceWorkflowCommand, WorkflowStateConflict
from app.application.youtube_access_token import YouTubeAccessTokenRefresher
from app.core.config import ConfigurationError
from app.core.publisher_oauth_state import issue_state
from app.core.publisher_oauth_state import verify_state
from app.core.publisher_token_cipher import PublisherTokenCipher
from app.core.youtube_publisher import YouTubePublisherSettings
from app.core.oidc import VerifiedIdentity
from app.domain.authorization import Permission
from app.domain.workflow import WorkflowState
from app.infrastructure.database import get_session
from app.infrastructure.membership_repository import SqlAlchemyOrganizationMembershipRepository
from app.infrastructure.publisher_oauth_repository import PublisherOAuthAttemptRepository
from app.infrastructure.models import MediaAsset, PublicationAttempt, PublishApproval, PublisherConnection
from app.infrastructure.models import VideoProject, WorkflowRun, WorkflowStep
from app.infrastructure.workflow_progression_repository import SqlAlchemyWorkflowProgressionRepository
from app.infrastructure.overlay_uploads import PrivateObjectPreviewIssuer, OverlayUploadConfigurationError, OverlayUploadVerificationError
from app.routers.auth import require_identity

router = APIRouter(prefix="/integrations", tags=["integrations"])

class OAuthStartResponse(BaseModel): authorization_url: str
class PublisherConnectionResponse(BaseModel): id: uuid.UUID; provider: str; provider_account_id: str; display_name: str; status: str
class YouTubePublishManifest(BaseModel): workflow_run_id: uuid.UUID; publisher_connection_id: uuid.UUID; title: str; description: str; artifact_download_url: str; artifact_expires_in_seconds: int; artifact_byte_size: int; artifact_checksum_sha256: str; access_token: str; access_token_expires_in_seconds: int
class CompleteYouTubePublishRequest(BaseModel): organization_id: uuid.UUID; publisher_connection_id: uuid.UUID; video_id: str; video_url: str
class FailYouTubePublishRequest(BaseModel): organization_id: uuid.UUID; publisher_connection_id: uuid.UUID; failure_code: str
class ClaimPublicationAttemptRequest(BaseModel): organization_id: uuid.UUID
class YouTubePublicationAttemptManifest(YouTubePublishManifest): publication_attempt_id: uuid.UUID; attempt_number: int; lease_token: str
class CompletePublicationAttemptRequest(BaseModel): organization_id: uuid.UUID; publisher_connection_id: uuid.UUID; lease_token: str; video_id: str; video_url: str
class FailPublicationAttemptRequest(BaseModel): organization_id: uuid.UUID; publisher_connection_id: uuid.UUID; lease_token: str; failure_code: str
class FailPublicationAttemptTerminalRequest(BaseModel): organization_id: uuid.UUID; failure_code: str

@router.get("/publisher-connections", response_model=list[PublisherConnectionResponse])
def list_publisher_connections(organization_id: uuid.UUID, identity: VerifiedIdentity = Depends(require_identity), session: Session = Depends(get_session)) -> list[PublisherConnectionResponse]:
    try:
        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(identity.subject, organization_id, Permission.WORKFLOW_VIEW)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Organization permission denied") from exc
    rows = session.scalars(select(PublisherConnection).where(PublisherConnection.organization_id == organization_id).order_by(PublisherConnection.created_at.desc())).all()
    return [PublisherConnectionResponse(id=row.id, provider=row.provider, provider_account_id=row.provider_account_id, display_name=row.display_name, status=row.status) for row in rows]

@router.post("/youtube/oauth/start", response_model=OAuthStartResponse)
def start_youtube_oauth(organization_id: uuid.UUID, identity: VerifiedIdentity = Depends(require_identity), session: Session = Depends(get_session)) -> OAuthStartResponse:
    try:
        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(identity.subject, organization_id, Permission.PUBLISH_EXECUTE)
        settings = YouTubePublisherSettings.from_env()
        state, digest, expires = issue_state(organization_id, identity.subject)
        PublisherOAuthAttemptRepository(session).create(organization_id=organization_id, provider="youtube", state_digest=digest, requested_by_subject=identity.subject, expires_at=datetime.fromtimestamp(expires, UTC))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Organization permission denied") from exc
    except (ConfigurationError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="YouTube integration is unavailable") from exc
    query = urlencode({"client_id":settings.client_id,"redirect_uri":settings.redirect_uri,"response_type":"code","scope":"https://www.googleapis.com/auth/youtube.upload","access_type":"offline","prompt":"consent","state":state})
    return OAuthStartResponse(authorization_url=f"https://accounts.google.com/o/oauth2/v2/auth?{query}")


@router.get("/youtube/oauth/callback")
def complete_youtube_oauth(code: str, state: str, session: Session = Depends(get_session)) -> RedirectResponse:
    try:
        payload = verify_state(state)
        organization_id = uuid.UUID(str(payload["o"]))
        subject = str(payload["s"])
        nonce_digest = __import__("hashlib").sha256(str(payload["n"]).encode()).hexdigest()
        PublisherOAuthAttemptRepository(session).consume(organization_id=organization_id, provider="youtube", state_digest=nonce_digest, requested_by_subject=subject)
        settings = YouTubePublisherSettings.from_env()
        token = requests.post("https://oauth2.googleapis.com/token", data={"code": code, "client_id": settings.client_id, "client_secret": settings.client_secret, "redirect_uri": settings.redirect_uri, "grant_type": "authorization_code"}, timeout=(3, 20))
        if token.status_code != 200: raise ValueError("Google authorization code exchange failed")
        tokens = token.json()
        refresh_token = tokens.get("refresh_token")
        access_token = tokens.get("access_token")
        if not isinstance(refresh_token, str) or not isinstance(access_token, str): raise ValueError("Google did not return reusable OAuth credentials")
        channel = requests.get("https://www.googleapis.com/youtube/v3/channels", params={"part":"id,snippet","mine":"true"}, headers={"Authorization": f"Bearer {access_token}"}, timeout=(3, 20))
        data = channel.json() if channel.status_code == 200 else {}
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict): raise ValueError("Google account has no uniquely selectable YouTube channel")
        item = items[0]; channel_id = item.get("id"); snippet = item.get("snippet")
        title = snippet.get("title") if isinstance(snippet, dict) else None
        if not isinstance(channel_id, str) or not isinstance(title, str): raise ValueError("YouTube channel identity is invalid")
        connection = session.scalar(select(PublisherConnection).where(PublisherConnection.organization_id == organization_id, PublisherConnection.provider == "youtube", PublisherConnection.provider_account_id == channel_id))
        encrypted = PublisherTokenCipher.from_env().encrypt(refresh_token)
        if connection is None:
            session.add(PublisherConnection(organization_id=organization_id, provider="youtube", provider_account_id=channel_id, display_name=title, encrypted_refresh_token=encrypted, scopes={"granted": tokens.get("scope", "https://www.googleapis.com/auth/youtube.upload")}, status="active", connected_by_subject=subject))
        else:
            connection.display_name, connection.encrypted_refresh_token, connection.status, connection.connected_by_subject = title, encrypted, "active", subject
        session.commit()
    except (ValueError, requests.RequestException) as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail="YouTube connection could not be completed") from exc
    return RedirectResponse(_console_callback_url(), status_code=status.HTTP_303_SEE_OTHER)


def _console_callback_url() -> str:
    """Return a configured console origin only; never trust a browser redirect parameter."""
    origins = [value.strip().rstrip("/") for value in (getenv("VISIONFLOW_WEB_ORIGINS") or "").split(",") if value.strip()]
    if not origins or not origins[0].startswith("https://"):
        raise ConfigurationError("VISIONFLOW_WEB_ORIGINS must contain an HTTPS console origin")
    return f"{origins[0]}/?youtube_oauth=connected"


@router.get("/youtube/publish-manifests/{workflow_run_id}", response_model=YouTubePublishManifest)
def get_youtube_publish_manifest(workflow_run_id: uuid.UUID, organization_id: uuid.UUID, identity: VerifiedIdentity = Depends(require_identity), session: Session = Depends(get_session)) -> YouTubePublishManifest:
    """Issue one short-lived, service-only manifest for an approved publish handoff."""
    try:
        _require_publisher_identity(identity)
        workflow = session.scalar(select(WorkflowRun).join(VideoProject).where(VideoProject.organization_id == organization_id, WorkflowRun.id == workflow_run_id))
        if workflow is None or workflow.state != WorkflowState.PUBLISHING.value:
            raise LookupError()
        publish = session.scalar(select(WorkflowStep).where(WorkflowStep.workflow_run_id == workflow_run_id, WorkflowStep.step_key == "publish"))
        payload = publish.output_payload if publish and isinstance(publish.output_payload, dict) else {}
        connection_id = payload.get("publisher_connection_id")
        if not isinstance(connection_id, str):
            raise LookupError()
        return _issue_youtube_manifest(session, workflow, organization_id, uuid.UUID(connection_id))
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Publisher service identity is not authorized") from exc
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Publish handoff not found") from exc
    except (ConfigurationError, OverlayUploadConfigurationError) as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Publisher service is unavailable") from exc
    except OverlayUploadVerificationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Publish artifact is invalid") from exc


@router.post("/youtube/publication-attempts/{publication_attempt_id}/claim", response_model=YouTubePublicationAttemptManifest)
def claim_youtube_publication_attempt(publication_attempt_id: uuid.UUID, request: ClaimPublicationAttemptRequest, identity: VerifiedIdentity = Depends(require_identity), session: Session = Depends(get_session)) -> YouTubePublicationAttemptManifest:
    """Claim a durable retry before issuing its short-lived YouTube credentials."""
    try:
        _require_publisher_identity(identity)
        attempt = _publication_attempt_for_update(session, publication_attempt_id, request.organization_id)
        if attempt is None:
            raise LookupError()
        now = datetime.now(UTC)
        if attempt.state == "succeeded":
            raise _AttemptAlreadyFinalized()
        if attempt.state == "failed":
            raise _AttemptAlreadyFinalized()
        if attempt.state == "claimed" and attempt.lease_expires_at is not None and attempt.lease_expires_at > now:
            raise _AttemptLeaseActive()
        if attempt.state not in {"requested", "claimed"}:
            raise _AttemptAlreadyFinalized()
        workflow = session.get(WorkflowRun, attempt.workflow_run_id)
        if workflow is None or workflow.state not in {WorkflowState.PUBLISHING.value, WorkflowState.FAILED.value}:
            raise LookupError()
        attempt.state = "claimed"
        attempt.lease_token = secrets.token_hex(32)
        attempt.lease_expires_at = now + timedelta(minutes=2)
        manifest = _issue_youtube_manifest(session, workflow, request.organization_id, attempt.publisher_connection_id)
        session.commit()
        return YouTubePublicationAttemptManifest(**manifest.model_dump(), publication_attempt_id=attempt.id, attempt_number=attempt.attempt_number, lease_token=attempt.lease_token)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Publisher service identity is not authorized") from exc
    except _AttemptLeaseActive as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "PUBLICATION_ATTEMPT_LEASE_ACTIVE"}) from exc
    except _AttemptAlreadyFinalized as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "PUBLICATION_ATTEMPT_ALREADY_FINALIZED"}) from exc
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Publication attempt not found") from exc
    except (ConfigurationError, OverlayUploadConfigurationError) as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Publisher service is unavailable") from exc
    except OverlayUploadVerificationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Publish artifact is invalid") from exc


@router.post("/youtube/publication-attempts/{publication_attempt_id}/complete")
def complete_youtube_publication_attempt(publication_attempt_id: uuid.UUID, request: CompletePublicationAttemptRequest, identity: VerifiedIdentity = Depends(require_identity), session: Session = Depends(get_session)) -> dict[str, str]:
    try:
        _require_publisher_identity(identity)
        if not request.video_id.strip() or not request.video_url.startswith("https://www.youtube.com/watch?v="):
            raise ValueError()
        attempt = _publication_attempt_for_update(session, publication_attempt_id, request.organization_id)
        if attempt is None or attempt.publisher_connection_id != request.publisher_connection_id:
            raise LookupError()
        _require_attempt_lease(attempt, request.lease_token)
        attempt.state = "succeeded"
        attempt.external_video_id = request.video_id
        attempt.external_url = request.video_url
        attempt.failure_code = None
        attempt.lease_token = None
        attempt.lease_expires_at = None
        workflow = session.get(WorkflowRun, attempt.workflow_run_id)
        if workflow is not None and workflow.state == WorkflowState.PUBLISHING.value:
            AdvanceWorkflow(SqlAlchemyWorkflowProgressionRepository(session)).execute(
                AdvanceWorkflowCommand(
                    organization_id=request.organization_id,
                    workflow_run_id=workflow.id,
                    expected_state=WorkflowState.PUBLISHING,
                    target_state=WorkflowState.PUBLISHED,
                    output_payload={"provider": "youtube", "publisher_connection_id": str(attempt.publisher_connection_id), "external_video_id": request.video_id, "external_url": request.video_url},
                    trace_id=uuid.uuid4().hex,
                )
            )
        else:
            session.commit()
        return {"publication_attempt_id": str(attempt.id), "state": attempt.state, "external_url": request.video_url}
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Publisher service identity is not authorized") from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Publication attempt not found") from exc
    except _AttemptLeaseInvalid as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "PUBLICATION_ATTEMPT_LEASE_INVALID"}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="YouTube publish result is invalid") from exc


@router.post("/youtube/publication-attempts/{publication_attempt_id}/fail")
def fail_youtube_publication_attempt(publication_attempt_id: uuid.UUID, request: FailPublicationAttemptRequest, identity: VerifiedIdentity = Depends(require_identity), session: Session = Depends(get_session)) -> dict[str, str]:
    try:
        _require_publisher_identity(identity)
        _validate_failure_code(request.failure_code)
        attempt = _publication_attempt_for_update(session, publication_attempt_id, request.organization_id)
        if attempt is None or attempt.publisher_connection_id != request.publisher_connection_id:
            raise LookupError()
        _require_attempt_lease(attempt, request.lease_token)
        attempt.state = "failed"
        attempt.failure_code = request.failure_code
        attempt.lease_token = None
        attempt.lease_expires_at = None
        _transition_initial_attempt_failure(session, attempt, request.organization_id, request.failure_code)
        return {"publication_attempt_id": str(attempt.id), "state": attempt.state}
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Publisher service identity is not authorized") from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Publication attempt not found") from exc
    except _AttemptLeaseInvalid as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "PUBLICATION_ATTEMPT_LEASE_INVALID"}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Publisher failure result is invalid") from exc


@router.post("/youtube/publication-attempts/{publication_attempt_id}/fail-terminal")
def fail_youtube_publication_attempt_terminal(publication_attempt_id: uuid.UUID, request: FailPublicationAttemptTerminalRequest, identity: VerifiedIdentity = Depends(require_identity), session: Session = Depends(get_session)) -> dict[str, str]:
    """Record a worker-exhausted retry without reopening the failed workflow."""
    try:
        _require_publisher_identity(identity)
        _validate_failure_code(request.failure_code)
        attempt = _publication_attempt_for_update(session, publication_attempt_id, request.organization_id)
        if attempt is None:
            raise LookupError()
        if attempt.state == "succeeded":
            raise _AttemptAlreadyFinalized()
        attempt.state = "failed"
        attempt.failure_code = request.failure_code
        attempt.lease_token = None
        attempt.lease_expires_at = None
        _transition_initial_attempt_failure(session, attempt, request.organization_id, request.failure_code)
        return {"publication_attempt_id": str(attempt.id), "state": attempt.state}
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Publisher service identity is not authorized") from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Publication attempt not found") from exc
    except _AttemptAlreadyFinalized as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "PUBLICATION_ATTEMPT_ALREADY_FINALIZED"}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Publisher failure result is invalid") from exc


@router.post("/youtube/publish-manifests/{workflow_run_id}/complete")
def complete_youtube_publish(workflow_run_id: uuid.UUID, request: CompleteYouTubePublishRequest, identity: VerifiedIdentity = Depends(require_identity), session: Session = Depends(get_session)) -> dict[str, str]:
    """Persist an external YouTube result through the canonical state transition."""
    try:
        _require_publisher_identity(identity)
        if not request.video_id.strip() or not request.video_url.startswith("https://www.youtube.com/watch?v="):
            raise ValueError("YouTube result is invalid")
        publish = session.scalar(select(WorkflowStep).where(WorkflowStep.workflow_run_id == workflow_run_id, WorkflowStep.step_key == "publish"))
        payload = publish.output_payload if publish and isinstance(publish.output_payload, dict) else {}
        if payload.get("publisher_connection_id") != str(request.publisher_connection_id):
            raise LookupError()
        result = AdvanceWorkflow(SqlAlchemyWorkflowProgressionRepository(session)).execute(
            AdvanceWorkflowCommand(organization_id=request.organization_id, workflow_run_id=workflow_run_id, expected_state=WorkflowState.PUBLISHING, target_state=WorkflowState.PUBLISHED, output_payload={"provider": "youtube", "publisher_connection_id": str(request.publisher_connection_id), "external_video_id": request.video_id, "external_url": request.video_url}, trace_id=uuid.uuid4().hex)
        )
        return {"workflow_run_id": str(result.workflow_run_id), "state": result.state.value}
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Publisher service identity is not authorized") from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Publish handoff not found") from exc
    except WorkflowStateConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Publish handoff is no longer active") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="YouTube publish result is invalid") from exc


@router.post("/youtube/publish-manifests/{workflow_run_id}/fail")
def fail_youtube_publish(workflow_run_id: uuid.UUID, request: FailYouTubePublishRequest, identity: VerifiedIdentity = Depends(require_identity), session: Session = Depends(get_session)) -> dict[str, str]:
    """Record terminal publisher failure without exposing provider error details."""
    try:
        _require_publisher_identity(identity)
        if not request.failure_code.isupper() or len(request.failure_code) > 96:
            raise ValueError()
        publish = session.scalar(select(WorkflowStep).where(WorkflowStep.workflow_run_id == workflow_run_id, WorkflowStep.step_key == "publish"))
        payload = publish.output_payload if publish and isinstance(publish.output_payload, dict) else {}
        if payload.get("publisher_connection_id") != str(request.publisher_connection_id):
            raise LookupError()
        result = AdvanceWorkflow(SqlAlchemyWorkflowProgressionRepository(session)).execute(AdvanceWorkflowCommand(organization_id=request.organization_id, workflow_run_id=workflow_run_id, expected_state=WorkflowState.PUBLISHING, target_state=WorkflowState.FAILED, output_payload={"provider": "youtube", "failure_code": request.failure_code}, trace_id=uuid.uuid4().hex))
        return {"workflow_run_id": str(result.workflow_run_id), "state": result.state.value}
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Publisher service identity is not authorized") from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Publish handoff not found") from exc
    except WorkflowStateConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Publish handoff is no longer active") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Publisher failure result is invalid") from exc


class _AttemptLeaseActive(Exception):
    pass


class _AttemptAlreadyFinalized(Exception):
    pass


class _AttemptLeaseInvalid(Exception):
    pass


def _publication_attempt_for_update(session: Session, publication_attempt_id: uuid.UUID, organization_id: uuid.UUID) -> PublicationAttempt | None:
    return session.scalar(
        select(PublicationAttempt)
        .join(WorkflowRun, WorkflowRun.id == PublicationAttempt.workflow_run_id)
        .join(VideoProject, VideoProject.id == WorkflowRun.project_id)
        .where(PublicationAttempt.id == publication_attempt_id, VideoProject.organization_id == organization_id)
        .with_for_update()
    )


def _require_attempt_lease(attempt: PublicationAttempt, lease_token: str) -> None:
    now = datetime.now(UTC)
    if (
        attempt.state != "claimed"
        or not attempt.lease_token
        or not hmac.compare_digest(attempt.lease_token, lease_token)
        or attempt.lease_expires_at is None
        or attempt.lease_expires_at <= now
    ):
        raise _AttemptLeaseInvalid()


def _validate_failure_code(failure_code: str) -> None:
    if not failure_code.isupper() or len(failure_code) > 96:
        raise ValueError()


def _transition_initial_attempt_failure(session: Session, attempt: PublicationAttempt, organization_id: uuid.UUID, failure_code: str) -> None:
    workflow = session.get(WorkflowRun, attempt.workflow_run_id)
    if workflow is not None and workflow.state == WorkflowState.PUBLISHING.value:
        AdvanceWorkflow(SqlAlchemyWorkflowProgressionRepository(session)).execute(
            AdvanceWorkflowCommand(
                organization_id=organization_id,
                workflow_run_id=workflow.id,
                expected_state=WorkflowState.PUBLISHING,
                target_state=WorkflowState.FAILED,
                output_payload={"provider": "youtube", "failure_code": failure_code},
                trace_id=uuid.uuid4().hex,
            )
        )
    else:
        session.commit()


def _issue_youtube_manifest(session: Session, workflow: WorkflowRun, organization_id: uuid.UUID, publisher_connection_id: uuid.UUID) -> YouTubePublishManifest:
    approval = session.scalar(
        select(PublishApproval).where(
            PublishApproval.workflow_run_id == workflow.id,
            PublishApproval.decision == "approved",
        )
    )
    if approval is None:
        raise LookupError()
    artifact = session.scalar(
        select(MediaAsset).where(
            MediaAsset.id == approval.export_asset_id,
            MediaAsset.organization_id == organization_id,
            MediaAsset.workflow_run_id == workflow.id,
            MediaAsset.media_kind == "final_export",
        )
    )
    if artifact is None:
        raise LookupError()
    connection = session.scalar(
        select(PublisherConnection).where(
            PublisherConnection.id == publisher_connection_id,
            PublisherConnection.organization_id == organization_id,
            PublisherConnection.provider == "youtube",
            PublisherConnection.status == "active",
        )
    )
    project = session.get(VideoProject, workflow.project_id)
    if connection is None or project is None:
        raise LookupError()
    preview = PrivateObjectPreviewIssuer.from_env().issue_final_export(workflow_run_id=workflow.id, object_key=artifact.object_key)
    token = YouTubeAccessTokenRefresher(requests, PublisherTokenCipher.from_env(), YouTubePublisherSettings.from_env()).refresh(connection.encrypted_refresh_token)
    return YouTubePublishManifest(
        workflow_run_id=workflow.id,
        publisher_connection_id=connection.id,
        title=project.title[:100],
        description=project.brief[:5000],
        artifact_download_url=preview.download_url,
        artifact_expires_in_seconds=preview.expires_in_seconds,
        artifact_byte_size=artifact.byte_size,
        artifact_checksum_sha256=artifact.checksum_sha256,
        access_token=token.value,
        access_token_expires_in_seconds=token.expires_in_seconds,
    )


def _require_publisher_identity(identity: VerifiedIdentity) -> None:
    expected_subject = (getenv("VISIONFLOW_PUBLISHER_WORKER_SUBJECT") or "").strip()
    if not expected_subject or identity.subject != expected_subject or Permission.PUBLISH_EXECUTE not in identity.scopes:
        raise PermissionError("Publisher service identity is not authorized")
