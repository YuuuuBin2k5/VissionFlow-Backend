from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.authorization import OrganizationRole
from app.infrastructure.models import OrganizationMembership, User


class SqlAlchemyOrganizationMembershipRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def find_role(self, identity_subject: str, organization_id: uuid.UUID) -> OrganizationRole | None:
        role = self._session.scalar(
            select(OrganizationMembership.role)
            .join(User, User.id == OrganizationMembership.user_id)
            .where(
                User.identity_subject == identity_subject,
                OrganizationMembership.organization_id == organization_id,
            )
        )
        if role is not None:
            return OrganizationRole(role)
        return None
