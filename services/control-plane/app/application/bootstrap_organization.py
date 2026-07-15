from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Protocol

from app.domain.authorization import OrganizationRole


_SLUG_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,78}[a-z0-9])?$")


@dataclass(frozen=True)
class BootstrapAdministratorCommand:
    organization_slug: str
    organization_name: str
    identity_subject: str
    email: str | None = None
    display_name: str | None = None
    role: OrganizationRole = OrganizationRole.ADMINISTRATOR
    promote_existing_membership: bool = False


@dataclass(frozen=True)
class BootstrapAdministratorResult:
    organization_id: uuid.UUID
    user_id: uuid.UUID
    membership_created: bool
    membership_promoted: bool


class BootstrapAdministratorRepository(Protocol):
    def bootstrap_administrator(
        self, command: BootstrapAdministratorCommand
    ) -> BootstrapAdministratorResult:
        """Create the initial organization/user/admin membership in one transaction."""


class BootstrapAdministrator:
    def __init__(self, repository: BootstrapAdministratorRepository) -> None:
        self._repository = repository

    def execute(self, command: BootstrapAdministratorCommand) -> BootstrapAdministratorResult:
        _validate(command)
        return self._repository.bootstrap_administrator(command)


def _validate(command: BootstrapAdministratorCommand) -> None:
    if len(command.organization_slug) < 2 or not _SLUG_PATTERN.fullmatch(command.organization_slug):
        raise ValueError("organization_slug must be lowercase kebab-case and 2-80 characters")
    if not command.organization_name.strip() or len(command.organization_name.strip()) > 160:
        raise ValueError("organization_name must be 1-160 characters")
    if not command.identity_subject.strip() or len(command.identity_subject.strip()) > 512:
        raise ValueError("identity_subject must be 1-512 characters")
    if command.email is not None and len(command.email) > 320:
        raise ValueError("email must be 320 characters or fewer")
    if command.display_name is not None and len(command.display_name) > 160:
        raise ValueError("display_name must be 160 characters or fewer")
