from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.application.authorize_organization import AuthorizeOrganization
from app.application.prompt_registry import (
    AddPromptVersionCommand,
    CreatePromptTemplateCommand,
    PromotePromptVersionCommand,
    PromptKeyConflict,
    PromptRegistry,
    PromptTemplateSummary,
    PromptVersionSummary,
)
from app.core.oidc import VerifiedIdentity
from app.domain.authorization import Permission
from app.infrastructure.database import get_session
from app.infrastructure.membership_repository import SqlAlchemyOrganizationMembershipRepository
from app.infrastructure.prompt_registry_repository import SqlAlchemyPromptRegistryRepository
from app.routers.auth import require_identity

router = APIRouter(tags=["prompts"])


class CreatePromptTemplateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt_key: str = Field(min_length=2, max_length=100)
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=10_000)
    content: str = Field(min_length=1, max_length=100_000)
    config: dict[str, object] = Field(default_factory=dict)
    change_note: str | None = Field(default=None, max_length=500)
    promote_immediately: bool = False


class AddPromptVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=100_000)
    config: dict[str, object] = Field(default_factory=dict)
    change_note: str | None = Field(default=None, max_length=500)


class PromotePromptVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)


class PromptTemplateResponse(BaseModel):
    id: uuid.UUID
    prompt_key: str
    name: str
    description: str
    production_version: int | None


class PromptVersionResponse(BaseModel):
    id: uuid.UUID
    version: int
    content: str
    config: dict[str, object]
    change_note: str | None


@router.get("/organizations/{organization_id}/prompts", response_model=list[PromptTemplateResponse])
def list_prompt_templates(
    organization_id: uuid.UUID,
    identity: VerifiedIdentity = Depends(require_identity),
    session: Session = Depends(get_session),
) -> list[PromptTemplateResponse]:
    registry = _authorized_registry(session, identity, organization_id)
    return [_template_response(item) for item in registry.list_templates(organization_id)]


@router.post(
    "/organizations/{organization_id}/prompts",
    response_model=PromptTemplateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_prompt_template(
    organization_id: uuid.UUID,
    request: CreatePromptTemplateRequest,
    identity: VerifiedIdentity = Depends(require_identity),
    session: Session = Depends(get_session),
) -> PromptTemplateResponse:
    registry = _authorized_registry(session, identity, organization_id)
    try:
        item = registry.create_template(
            CreatePromptTemplateCommand(
                organization_id=organization_id,
                prompt_key=request.prompt_key,
                name=request.name,
                description=request.description,
                content=request.content,
                actor_subject=identity.subject,
                config=request.config,
                change_note=request.change_note,
                promote_immediately=request.promote_immediately,
            )
        )
    except PromptKeyConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Prompt key already exists") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _template_response(item)


@router.get(
    "/organizations/{organization_id}/prompts/{prompt_template_id}/versions",
    response_model=list[PromptVersionResponse],
)
def list_prompt_versions(
    organization_id: uuid.UUID,
    prompt_template_id: uuid.UUID,
    identity: VerifiedIdentity = Depends(require_identity),
    session: Session = Depends(get_session),
) -> list[PromptVersionResponse]:
    registry = _authorized_registry(session, identity, organization_id)
    try:
        return [_version_response(item) for item in registry.list_versions(organization_id, prompt_template_id)]
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompt template not found") from exc


@router.post(
    "/organizations/{organization_id}/prompts/{prompt_template_id}/versions",
    response_model=PromptVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_prompt_version(
    organization_id: uuid.UUID,
    prompt_template_id: uuid.UUID,
    request: AddPromptVersionRequest,
    identity: VerifiedIdentity = Depends(require_identity),
    session: Session = Depends(get_session),
) -> PromptVersionResponse:
    registry = _authorized_registry(session, identity, organization_id)
    try:
        item = registry.add_version(
            AddPromptVersionCommand(
                organization_id=organization_id,
                prompt_template_id=prompt_template_id,
                content=request.content,
                actor_subject=identity.subject,
                config=request.config,
                change_note=request.change_note,
            )
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompt template not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _version_response(item)


@router.post(
    "/organizations/{organization_id}/prompts/{prompt_template_id}/promote",
    response_model=PromptTemplateResponse,
)
def promote_prompt_version(
    organization_id: uuid.UUID,
    prompt_template_id: uuid.UUID,
    request: PromotePromptVersionRequest,
    identity: VerifiedIdentity = Depends(require_identity),
    session: Session = Depends(get_session),
) -> PromptTemplateResponse:
    registry = _authorized_registry(session, identity, organization_id)
    try:
        item = registry.promote_version(
            PromotePromptVersionCommand(
                organization_id=organization_id,
                prompt_template_id=prompt_template_id,
                version=request.version,
                actor_subject=identity.subject,
            )
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompt template or version not found") from exc
    return _template_response(item)


def _authorized_registry(
    session: Session, identity: VerifiedIdentity, organization_id: uuid.UUID
) -> PromptRegistry:
    try:
        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(
            identity.subject, organization_id, Permission.PROMPT_MANAGE
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization permission denied") from exc
    return PromptRegistry(SqlAlchemyPromptRegistryRepository(session))


def _template_response(item: PromptTemplateSummary) -> PromptTemplateResponse:
    return PromptTemplateResponse(
        id=item.id,
        prompt_key=item.prompt_key,
        name=item.name,
        description=item.description,
        production_version=item.production_version,
    )


def _version_response(item: PromptVersionSummary) -> PromptVersionResponse:
    return PromptVersionResponse(
        id=item.id,
        version=item.version,
        content=item.content,
        config=item.config,
        change_note=item.change_note,
    )
