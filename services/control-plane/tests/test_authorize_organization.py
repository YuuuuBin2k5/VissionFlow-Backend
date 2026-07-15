import sys
import unittest
import uuid
from pathlib import Path


SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.application.authorize_organization import AuthorizeOrganization  # noqa: E402
from app.domain.authorization import OrganizationRole, Permission  # noqa: E402


class FakeMembershipRepository:
    def __init__(self, role: OrganizationRole | None) -> None:
        self.role = role

    def find_role(self, identity_subject: str, organization_id: uuid.UUID) -> OrganizationRole | None:
        return self.role


class AuthorizeOrganizationTests(unittest.TestCase):
    def test_administrator_can_manage_prompts(self) -> None:
        authorization = AuthorizeOrganization(FakeMembershipRepository(OrganizationRole.ADMINISTRATOR))

        role = authorization.require("oidc|admin", uuid.uuid4(), Permission.PROMPT_MANAGE)

        self.assertEqual(OrganizationRole.ADMINISTRATOR, role)

    def test_unknown_identity_is_denied(self) -> None:
        authorization = AuthorizeOrganization(FakeMembershipRepository(None))

        with self.assertRaisesRegex(PermissionError, "not a member"):
            authorization.require("oidc|unknown", uuid.uuid4(), Permission.WORKFLOW_CREATE)

    def test_viewer_cannot_create_workflow(self) -> None:
        authorization = AuthorizeOrganization(FakeMembershipRepository(OrganizationRole.VIEWER))

        with self.assertRaisesRegex(PermissionError, "workflow:create"):
            authorization.require("oidc|viewer", uuid.uuid4(), Permission.WORKFLOW_CREATE)
