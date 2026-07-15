from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.bootstrap_organization import (
    BootstrapAdministratorCommand,
    BootstrapAdministratorResult,
)
from app.infrastructure.models import Organization, OrganizationMembership, User


class SqlAlchemyBootstrapAdministratorRepository:
    """Direct-connection setup repository; never used by the web request path."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def bootstrap_administrator(
        self, command: BootstrapAdministratorCommand
    ) -> BootstrapAdministratorResult:
        try:
            organization = self._session.scalar(
                select(Organization).where(Organization.slug == command.organization_slug)
            )
            if organization is None:
                organization = Organization(
                    slug=command.organization_slug,
                    name=command.organization_name.strip(),
                )
                self._session.add(organization)
                self._session.flush()

            user = self._session.scalar(
                select(User).where(User.identity_subject == command.identity_subject.strip())
            )
            if user is None:
                user = User(
                    identity_subject=command.identity_subject.strip(),
                    email=command.email,
                    display_name=command.display_name,
                )
                self._session.add(user)
                self._session.flush()

            membership = self._session.scalar(
                select(OrganizationMembership).where(
                    OrganizationMembership.organization_id == organization.id,
                    OrganizationMembership.user_id == user.id,
                )
            )
            membership_created = membership is None
            membership_promoted = False
            if membership is None:
                membership = OrganizationMembership(
                    organization_id=organization.id,
                    user_id=user.id,
                    role=command.role.value,
                )
                self._session.add(membership)
            elif membership.role != command.role.value:
                if not command.promote_existing_membership:
                    raise PermissionError(
                        "existing membership has a different role; rerun with explicit role change"
                    )
                membership.role = command.role.value
                membership_promoted = True

            self._session.commit()
            return BootstrapAdministratorResult(
                organization_id=organization.id,
                user_id=user.id,
                membership_created=membership_created,
                membership_promoted=membership_promoted,
            )
        except Exception:
            self._session.rollback()
            raise
