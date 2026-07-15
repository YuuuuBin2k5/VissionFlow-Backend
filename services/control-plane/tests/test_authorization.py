import sys
import unittest
from pathlib import Path


SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.domain.authorization import (  # noqa: E402
    OrganizationRole,
    Permission,
    has_permission,
    require_permission,
)


class AuthorizationPolicyTests(unittest.TestCase):
    def test_administrator_can_manage_prompts_and_publish(self) -> None:
        self.assertTrue(has_permission(OrganizationRole.ADMINISTRATOR, Permission.PROMPT_MANAGE))
        self.assertTrue(has_permission(OrganizationRole.ADMINISTRATOR, Permission.PUBLISH_EXECUTE))

    def test_producer_cannot_manage_prompts_or_publish(self) -> None:
        self.assertTrue(has_permission(OrganizationRole.PRODUCER, Permission.WORKFLOW_CREATE))
        self.assertFalse(has_permission(OrganizationRole.PRODUCER, Permission.PROMPT_MANAGE))
        self.assertFalse(has_permission(OrganizationRole.PRODUCER, Permission.PUBLISH_EXECUTE))

    def test_reviewer_can_approve_but_not_execute_publish(self) -> None:
        self.assertTrue(has_permission(OrganizationRole.REVIEWER, Permission.PUBLISH_APPROVE))
        with self.assertRaisesRegex(PermissionError, "publish:execute"):
            require_permission(OrganizationRole.REVIEWER, Permission.PUBLISH_EXECUTE)
