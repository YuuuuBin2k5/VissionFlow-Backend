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

    def require(
        self,
        identity_subject: str,
        organization_id: uuid.UUID,
        permission: Permission,
        verified_email: str | None = None,
    ) -> OrganizationRole:
        role = self._repository.find_role(identity_subject, organization_id)
        # OIDC providers can rotate or migrate ``sub`` values.  A verified
        # email is a narrowly-scoped identity-link fallback, not a tenant
        # default: it succeeds only when every matching membership agrees on
        # the same role.
        if role is None and verified_email:
            by_email = getattr(self._repository, "find_role_for_verified_email", None)
            if callable(by_email):
                role = by_email(verified_email, organization_id)
        if role is None:
            raise PermissionError("identity is not a member of this organization")
        require_permission(role, permission)
        return role
