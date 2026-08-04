import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.application.authorize_organization import AuthorizeOrganization
from app.application.get_short_form_readiness import GetShortFormReadiness, ReadinessResponse
from app.core.config import Settings
from app.core.oidc import VerifiedIdentity
from app.domain.authorization import Permission
from app.infrastructure.database import get_engine, get_session
from app.infrastructure.membership_repository import SqlAlchemyOrganizationMembershipRepository
from app.infrastructure.repositories import SqlAlchemyShortFormReadinessRepository
from app.routers.auth import require_identity

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict[str, str]:
    settings = Settings.from_env()
    return {"status": "ok", "service": "visionflow-control-plane", "environment": settings.app_env}


@router.get("/ready")
def ready() -> dict[str, str]:
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="PostgreSQL is unavailable") from exc
    return {"status": "ready", "database": "postgresql"}


@router.get("/organizations/{organization_id}/readiness", response_model=ReadinessResponse)
def get_readiness(
    organization_id: uuid.UUID,
    identity: VerifiedIdentity = Depends(require_identity),
    session: Session = Depends(get_session),
):
    try:
        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(
            identity.subject, organization_id, Permission.WORKFLOW_VIEW
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization permission denied",
        ) from exc

    repository = SqlAlchemyShortFormReadinessRepository(session)
    use_case = GetShortFormReadiness(repository)
    return use_case.execute(organization_id)

