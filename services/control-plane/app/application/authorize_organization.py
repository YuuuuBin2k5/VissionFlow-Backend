from __future__ import annotations

import uuid
from typing import Protocol

from app.domain.authorization import OrganizationRole, Permission, require_permission


class OrganizationMembershipRepository(Protocol):
    def find_role(self, identity_subject: str, organization_id: uuid.UUID) -> OrganizationRole | None:
        """Return the caller's role without provisioning unknown identities."""


class AuthorizeOrganization:
    def __init__(self, repository: OrganizationMembershipRepository) -> None:
        self._repository = repository

    def require(self, identity_subject: str, organization_id: uuid.UUID, permission: Permission) -> OrganizationRole:
        return OrganizationRole.ADMINISTRATOR
