"""Admin-only lifecycle API for encrypted third-party provider credentials."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.application.authorize_organization import AuthorizeOrganization
from app.core.credential_cipher import ProviderCredentialCipher, secret_fingerprint
from app.core.oidc import VerifiedIdentity
from app.domain.authorization import Permission
from app.infrastructure.database import get_session
from app.infrastructure.membership_repository import SqlAlchemyOrganizationMembershipRepository
from app.infrastructure.models import ProviderCredential, ProviderCredentialAuditEvent
from app.routers.auth import require_identity

router = APIRouter(tags=["provider-credentials"])

SUPPORTED_PROVIDERS = frozenset({
    "gemini", "groq", "openrouter",
    "fal", "together", "deepinfra", "huggingface", "segmind",
    "replicate", "kling", "runway", "luma", "minimax",
    "pexels", "pixabay", "coverr"
})
MUTABLE_STATUSES = frozenset({"active", "disabled"})


class ProviderCredentialResponse(BaseModel):
    id: uuid.UUID
    provider: str
    label: str
    priority: int
    status: str
    capabilities: dict[str, object]
    fingerprint_suffix: str
    last_used_at: datetime | None
    last_failure_code: str | None
    created_at: datetime
    updated_at: datetime


class CreateProviderCredentialRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=2, max_length=64)
    label: str = Field(min_length=1, max_length=120)
    secret: str = Field(min_length=8, max_length=20_000)
    capabilities: dict[str, object] = Field(default_factory=dict)


class UpdateProviderCredentialRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(default=None, min_length=1, max_length=120)
    status: str | None = Field(default=None, min_length=1, max_length=24)


class ReorderProviderCredentialsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=2, max_length=64)
    credential_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)


class ResolvedProviderCredentialResponse(BaseModel):
    id: uuid.UUID
    provider: str
    priority: int
    secret: str


def _authorize(session: Session, identity: VerifiedIdentity, organization_id: uuid.UUID) -> None:
    try:
        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(
            identity.subject, organization_id, Permission.CREDENTIAL_MANAGE
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization credential permission denied") from exc


def _provider(value: str) -> str:
    provider = value.strip().lower()
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported credential provider")
    return provider


def _response(record: ProviderCredential) -> ProviderCredentialResponse:
    return ProviderCredentialResponse(
        id=record.id, provider=record.provider, label=record.label, priority=record.priority,
        status=record.status, capabilities=record.capabilities,
        fingerprint_suffix=record.secret_fingerprint[-8:], last_used_at=record.last_used_at,
        last_failure_code=record.last_failure_code, created_at=record.created_at, updated_at=record.updated_at,
    )


def _audit(session: Session, *, organization_id: uuid.UUID, credential_id: uuid.UUID | None, actor: str, event_type: str, metadata: dict[str, object]) -> None:
    session.add(ProviderCredentialAuditEvent(
        organization_id=organization_id, credential_id=credential_id, actor_subject=actor,
        event_type=event_type, outcome="success", metadata_json=metadata,
    ))


@router.get("/organizations/{organization_id}/provider-credentials", response_model=list[ProviderCredentialResponse])
def list_provider_credentials(organization_id: uuid.UUID, identity: VerifiedIdentity = Depends(require_identity), session: Session = Depends(get_session)) -> list[ProviderCredentialResponse]:
    _authorize(session, identity, organization_id)
    records = session.scalars(
        select(ProviderCredential)
        .where(ProviderCredential.organization_id == organization_id)
        .order_by(ProviderCredential.provider, ProviderCredential.priority, ProviderCredential.created_at)
    ).all()
    return [_response(record) for record in records]


@router.post("/organizations/{organization_id}/provider-credentials", response_model=ProviderCredentialResponse, status_code=status.HTTP_201_CREATED)
def create_provider_credential(organization_id: uuid.UUID, request: CreateProviderCredentialRequest, identity: VerifiedIdentity = Depends(require_identity), session: Session = Depends(get_session)) -> ProviderCredentialResponse:
    _authorize(session, identity, organization_id)
    provider = _provider(request.provider)
    fingerprint = secret_fingerprint(request.secret.strip())
    duplicate = session.scalar(select(ProviderCredential.id).where(
        ProviderCredential.organization_id == organization_id,
        ProviderCredential.provider == provider,
        ProviderCredential.secret_fingerprint == fingerprint,
    ))
    if duplicate is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A matching provider credential already exists")
    next_priority = session.scalar(select(ProviderCredential.priority).where(
        ProviderCredential.organization_id == organization_id, ProviderCredential.provider == provider,
    ).order_by(ProviderCredential.priority.desc()).limit(1))
    record = ProviderCredential(
        organization_id=organization_id, provider=provider, label=request.label.strip(),
        secret_ciphertext=ProviderCredentialCipher.from_env().encrypt(request.secret.strip()),
        secret_fingerprint=fingerprint, priority=(next_priority or 0) + 1, status="active",
        capabilities=request.capabilities, created_by_subject=identity.subject,
    )
    try:
        session.add(record)
        session.flush()
        _audit(session, organization_id=organization_id, credential_id=record.id, actor=identity.subject, event_type="provider_credential.created", metadata={"provider": provider, "label": record.label, "priority": record.priority})
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Provider credential label already exists") from exc
    session.refresh(record)
    return _response(record)


@router.patch("/organizations/{organization_id}/provider-credentials/{credential_id}", response_model=ProviderCredentialResponse)
def update_provider_credential(organization_id: uuid.UUID, credential_id: uuid.UUID, request: UpdateProviderCredentialRequest, identity: VerifiedIdentity = Depends(require_identity), session: Session = Depends(get_session)) -> ProviderCredentialResponse:
    _authorize(session, identity, organization_id)
    record = session.scalar(select(ProviderCredential).where(ProviderCredential.id == credential_id, ProviderCredential.organization_id == organization_id).with_for_update())
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider credential not found")
    if request.status is not None:
        normalized = request.status.strip().lower()
        if normalized not in MUTABLE_STATUSES:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Credential status must be active or disabled")
        record.status = normalized
    if request.label is not None:
        record.label = request.label.strip()
    try:
        _audit(session, organization_id=organization_id, credential_id=record.id, actor=identity.subject, event_type="provider_credential.updated", metadata={"status": record.status, "label": record.label})
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Provider credential label already exists") from exc
    session.refresh(record)
    return _response(record)


@router.post("/organizations/{organization_id}/provider-credentials/reorder", response_model=list[ProviderCredentialResponse])
def reorder_provider_credentials(organization_id: uuid.UUID, request: ReorderProviderCredentialsRequest, identity: VerifiedIdentity = Depends(require_identity), session: Session = Depends(get_session)) -> list[ProviderCredentialResponse]:
    _authorize(session, identity, organization_id)
    provider = _provider(request.provider)
    if len(set(request.credential_ids)) != len(request.credential_ids):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Credential ordering contains duplicates")
    records = session.scalars(select(ProviderCredential).where(
        ProviderCredential.organization_id == organization_id, ProviderCredential.provider == provider,
    ).with_for_update()).all()
    by_id = {record.id: record for record in records}
    if set(by_id) != set(request.credential_ids):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Credential ordering is stale or incomplete")
    for priority, credential_id in enumerate(request.credential_ids, start=1):
        by_id[credential_id].priority = priority
    _audit(session, organization_id=organization_id, credential_id=None, actor=identity.subject, event_type="provider_credential.reordered", metadata={"provider": provider, "count": len(records)})
    session.commit()
    return [_response(by_id[credential_id]) for credential_id in request.credential_ids]


@router.delete("/organizations/{organization_id}/provider-credentials/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_provider_credential(organization_id: uuid.UUID, credential_id: uuid.UUID, identity: VerifiedIdentity = Depends(require_identity), session: Session = Depends(get_session)) -> None:
    _authorize(session, identity, organization_id)
    record = session.scalar(select(ProviderCredential).where(ProviderCredential.id == credential_id, ProviderCredential.organization_id == organization_id).with_for_update())
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider credential not found")
    _audit(session, organization_id=organization_id, credential_id=record.id, actor=identity.subject, event_type="provider_credential.deleted", metadata={"provider": record.provider, "label": record.label})
    session.delete(record)
    session.commit()


@router.get("/organizations/{organization_id}/provider-credentials/{provider}/resolve", response_model=list[ResolvedProviderCredentialResponse])
def resolve_provider_credentials(organization_id: uuid.UUID, provider: str, identity: VerifiedIdentity = Depends(require_identity), session: Session = Depends(get_session)) -> list[ResolvedProviderCredentialResponse]:
    """Trusted worker-only secret delivery; never available to browser identities."""
    normalized_provider = _provider(provider)
    expected_subject = os.getenv("VISIONFLOW_WORKER_SUBJECT", "").strip()
    if not expected_subject:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Worker identity is not configured")
    if identity.subject != expected_subject or "credential:resolve" not in identity.scopes:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Provider credential resolution is restricted to the render worker")
    try:
        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(
            identity.subject, organization_id, Permission.CREDENTIAL_RESOLVE
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization credential permission denied") from exc
    records = session.scalars(select(ProviderCredential).where(
        ProviderCredential.organization_id == organization_id,
        ProviderCredential.provider == normalized_provider,
        ProviderCredential.status == "active",
    ).order_by(ProviderCredential.priority, ProviderCredential.created_at)).all()
    if not records:
        return []
    cipher = ProviderCredentialCipher.from_env()
    result = []
    for record in records:
        record.last_used_at = datetime.now(UTC)
        _audit(session, organization_id=organization_id, credential_id=record.id, actor=identity.subject, event_type="provider_credential.resolved", metadata={"provider": normalized_provider, "priority": record.priority})
        result.append(ResolvedProviderCredentialResponse(id=record.id, provider=record.provider, priority=record.priority, secret=cipher.decrypt(record.secret_ciphertext)))
    session.commit()
    return result
