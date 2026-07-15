from __future__ import annotations

from enum import StrEnum


class OrganizationRole(StrEnum):
    ADMINISTRATOR = "administrator"
    SERVICE = "service"
    PRODUCER = "producer"
    REVIEWER = "reviewer"
    VIEWER = "viewer"


class Permission(StrEnum):
    WORKFLOW_CREATE = "workflow:create"
    WORKFLOW_VIEW = "workflow:view"
    WORKFLOW_ADVANCE = "workflow:advance"
    WORKFLOW_NARRATION_COMPLETE = "workflow:narration:complete"
    PROMPT_MANAGE = "prompt:manage"
    PUBLISH_APPROVE = "publish:approve"
    PUBLISH_EXECUTE = "publish:execute"


ROLE_PERMISSIONS: dict[OrganizationRole, frozenset[Permission]] = {
    OrganizationRole.ADMINISTRATOR: frozenset(Permission),
    OrganizationRole.SERVICE: frozenset(
        {
            Permission.WORKFLOW_CREATE,
            Permission.WORKFLOW_VIEW,
            Permission.WORKFLOW_ADVANCE,
            Permission.WORKFLOW_NARRATION_COMPLETE,
        }
    ),
    OrganizationRole.PRODUCER: frozenset({Permission.WORKFLOW_CREATE, Permission.WORKFLOW_VIEW}),
    OrganizationRole.REVIEWER: frozenset({Permission.WORKFLOW_VIEW, Permission.PUBLISH_APPROVE}),
    OrganizationRole.VIEWER: frozenset({Permission.WORKFLOW_VIEW}),
}


def has_permission(role: OrganizationRole, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS[role]


def require_permission(role: OrganizationRole, permission: Permission) -> None:
    if not has_permission(role, permission):
        raise PermissionError(f"role '{role}' does not grant '{permission}'")
