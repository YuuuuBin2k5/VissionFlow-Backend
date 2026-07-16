from __future__ import annotations

import uuid
from datetime import UTC, datetime
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.application.authorize_organization import AuthorizeOrganization
from app.core.config import ConfigurationError
from app.core.publisher_oauth_state import issue_state
from app.core.youtube_publisher import YouTubePublisherSettings
from app.core.oidc import VerifiedIdentity
from app.domain.authorization import Permission
from app.infrastructure.database import get_session
from app.infrastructure.membership_repository import SqlAlchemyOrganizationMembershipRepository
from app.infrastructure.publisher_oauth_repository import PublisherOAuthAttemptRepository
from app.routers.auth import require_identity

router = APIRouter(prefix="/integrations", tags=["integrations"])

class OAuthStartResponse(BaseModel): authorization_url: str

@router.post("/youtube/oauth/start", response_model=OAuthStartResponse)
def start_youtube_oauth(organization_id: uuid.UUID, identity: VerifiedIdentity = Depends(require_identity), session: Session = Depends(get_session)) -> OAuthStartResponse:
    try:
        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(identity.subject, organization_id, Permission.PUBLISH_EXECUTE)
        state, digest, expires = issue_state(organization_id, identity.subject)
        PublisherOAuthAttemptRepository(session).create(organization_id=organization_id, provider="youtube", state_digest=digest, requested_by_subject=identity.subject, expires_at=datetime.fromtimestamp(expires, UTC))
        settings = YouTubePublisherSettings.from_env()
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Organization permission denied") from exc
    except (ConfigurationError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="YouTube integration is unavailable") from exc
    query = urlencode({"client_id":settings.client_id,"redirect_uri":settings.redirect_uri,"response_type":"code","scope":"https://www.googleapis.com/auth/youtube.upload","access_type":"offline","prompt":"consent","state":state})
    return OAuthStartResponse(authorization_url=f"https://accounts.google.com/o/oauth2/v2/auth?{query}")
