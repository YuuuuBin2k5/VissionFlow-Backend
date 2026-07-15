from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Protocol


_PROMPT_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{1,99}$")


class PromptKeyConflict(RuntimeError):
    """Raised when an organization already owns a template with this key."""


@dataclass(frozen=True)
class CreatePromptTemplateCommand:
    organization_id: uuid.UUID
    prompt_key: str
    name: str
    description: str
    content: str
    actor_subject: str
    config: dict[str, object] = field(default_factory=dict)
    change_note: str | None = None
    promote_immediately: bool = False


@dataclass(frozen=True)
class AddPromptVersionCommand:
    organization_id: uuid.UUID
    prompt_template_id: uuid.UUID
    content: str
    actor_subject: str
    config: dict[str, object] = field(default_factory=dict)
    change_note: str | None = None


@dataclass(frozen=True)
class PromotePromptVersionCommand:
    organization_id: uuid.UUID
    prompt_template_id: uuid.UUID
    version: int
    actor_subject: str


@dataclass(frozen=True)
class PromptTemplateSummary:
    id: uuid.UUID
    prompt_key: str
    name: str
    description: str
    production_version: int | None


@dataclass(frozen=True)
class PromptVersionSummary:
    id: uuid.UUID
    version: int
    content: str
    config: dict[str, object]
    change_note: str | None


class PromptRegistryRepository(Protocol):
    def create_template(self, command: CreatePromptTemplateCommand) -> PromptTemplateSummary:
        """Create template/version one and record its audit entry atomically."""

    def add_version(self, command: AddPromptVersionCommand) -> PromptVersionSummary:
        """Append a version for an owned template and record its audit entry."""

    def promote_version(self, command: PromotePromptVersionCommand) -> PromptTemplateSummary:
        """Select an existing version for production and record its audit entry."""

    def list_templates(self, organization_id: uuid.UUID) -> list[PromptTemplateSummary]:
        """Return only the calling organization's prompt templates."""

    def list_versions(self, organization_id: uuid.UUID, prompt_template_id: uuid.UUID) -> list[PromptVersionSummary]:
        """Return versions only after enforcing template ownership."""


class PromptRegistry:
    def __init__(self, repository: PromptRegistryRepository) -> None:
        self._repository = repository

    def create_template(self, command: CreatePromptTemplateCommand) -> PromptTemplateSummary:
        _validate_template(command)
        return self._repository.create_template(command)

    def add_version(self, command: AddPromptVersionCommand) -> PromptVersionSummary:
        _validate_version(command.content, command.actor_subject, command.change_note)
        return self._repository.add_version(command)

    def promote_version(self, command: PromotePromptVersionCommand) -> PromptTemplateSummary:
        if command.version < 1:
            raise ValueError("version must be positive")
        if not command.actor_subject.strip():
            raise ValueError("actor_subject must not be blank")
        return self._repository.promote_version(command)

    def list_templates(self, organization_id: uuid.UUID) -> list[PromptTemplateSummary]:
        return self._repository.list_templates(organization_id)

    def list_versions(self, organization_id: uuid.UUID, prompt_template_id: uuid.UUID) -> list[PromptVersionSummary]:
        return self._repository.list_versions(organization_id, prompt_template_id)


def _validate_template(command: CreatePromptTemplateCommand) -> None:
    if not _PROMPT_KEY_PATTERN.fullmatch(command.prompt_key):
        raise ValueError("prompt_key must be lowercase and use only letters, digits, dot, underscore or hyphen")
    if not command.name.strip() or len(command.name.strip()) > 160:
        raise ValueError("name must be 1-160 characters")
    if not command.description.strip() or len(command.description.strip()) > 10_000:
        raise ValueError("description must be 1-10000 characters")
    _validate_version(command.content, command.actor_subject, command.change_note)


def _validate_version(content: str, actor_subject: str, change_note: str | None) -> None:
    if not content.strip() or len(content) > 100_000:
        raise ValueError("content must be 1-100000 characters")
    if not actor_subject.strip() or len(actor_subject) > 512:
        raise ValueError("actor_subject must be 1-512 characters")
    if change_note is not None and len(change_note) > 500:
        raise ValueError("change_note must be 500 characters or fewer")
