from __future__ import annotations

import uuid
from datetime import UTC, datetime
from urllib.parse import urlencode

import requests
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.application.authorize_organization import AuthorizeOrganization
from app.core.config import ConfigurationError
from app.core.publisher_oauth_state import issue_state
from app.core.publisher_oauth_state import verify_state
from app.core.publisher_token_cipher import PublisherTokenCipher
from app.core.youtube_publisher import YouTubePublisherSettings
from app.core.oidc import VerifiedIdentity
from app.domain.authorization import Permission
from app.infrastructure.database import get_session
from app.infrastructure.membership_repository import SqlAlchemyOrganizationMembershipRepository
from app.infrastructure.publisher_oauth_repository import PublisherOAuthAttemptRepository
from app.infrastructure.models import PublisherConnection
from app.routers.auth import require_identity

router = APIRouter(prefix="/integrations", tags=["integrations"])

class OAuthStartResponse(BaseModel): authorization_url: str
class PublisherConnectionResponse(BaseModel): id: uuid.UUID; provider: str; provider_account_id: str; display_name: str; status: str

@router.get("/publisher-connections", response_model=list[PublisherConnectionResponse])
def list_publisher_connections(organization_id: uuid.UUID, identity: VerifiedIdentity = Depends(require_identity), session: Session = Depends(get_session)) -> list[PublisherConnectionResponse]:
    try:
        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(identity.subject, organization_id, Permission.WORKFLOW_VIEW)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Organization permission denied") from exc
    rows = session.scalars(__import__('sqlalchemy').select(PublisherConnection).where(PublisherConnection.organization_id == organization_id).order_by(PublisherConnection.created_at.desc())).all()
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
def complete_youtube_oauth(code: str, state: str, session: Session = Depends(get_session)) -> dict[str, str]:
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
        connection = session.scalar(__import__("sqlalchemy").select(PublisherConnection).where(PublisherConnection.organization_id == organization_id, PublisherConnection.provider == "youtube", PublisherConnection.provider_account_id == channel_id))
        encrypted = PublisherTokenCipher.from_env().encrypt(refresh_token)
        if connection is None:
            session.add(PublisherConnection(organization_id=organization_id, provider="youtube", provider_account_id=channel_id, display_name=title, encrypted_refresh_token=encrypted, scopes={"granted": tokens.get("scope", "https://www.googleapis.com/auth/youtube.upload")}, status="active", connected_by_subject=subject))
        else:
            connection.display_name, connection.encrypted_refresh_token, connection.status, connection.connected_by_subject = title, encrypted, "active", subject
        session.commit()
    except (ValueError, requests.RequestException) as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail="YouTube connection could not be completed") from exc
    return {"status": "connected", "provider": "youtube"}
