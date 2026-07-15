import sys
import unittest
import uuid
from pathlib import Path


SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.application.bootstrap_organization import (  # noqa: E402
    BootstrapAdministrator,
    BootstrapAdministratorCommand,
    BootstrapAdministratorResult,
)
from app.domain.authorization import OrganizationRole  # noqa: E402


class FakeBootstrapRepository:
    def __init__(self) -> None:
        self.commands: list[BootstrapAdministratorCommand] = []

    def bootstrap_administrator(
        self, command: BootstrapAdministratorCommand
    ) -> BootstrapAdministratorResult:
        self.commands.append(command)
        return BootstrapAdministratorResult(uuid.uuid4(), uuid.uuid4(), True, False)


class BootstrapAdministratorTests(unittest.TestCase):
    def test_creates_a_valid_initial_administrator(self) -> None:
        repository = FakeBootstrapRepository()
        command = BootstrapAdministratorCommand(
            organization_slug="visionflow-studio",
            organization_name="VisionFlow Studio",
            identity_subject="oidc|admin-001",
        )

        result = BootstrapAdministrator(repository).execute(command)

        self.assertTrue(result.membership_created)
        self.assertEqual([command], repository.commands)

    def test_rejects_non_canonical_organization_slug(self) -> None:
        repository = FakeBootstrapRepository()
        command = BootstrapAdministratorCommand(
            organization_slug="VisionFlow Studio",
            organization_name="VisionFlow Studio",
            identity_subject="oidc|admin-001",
        )

        with self.assertRaisesRegex(ValueError, "kebab-case"):
            BootstrapAdministrator(repository).execute(command)
        self.assertEqual([], repository.commands)

    def test_can_bootstrap_a_least_privilege_service_membership(self) -> None:
        repository = FakeBootstrapRepository()
        command = BootstrapAdministratorCommand(
            organization_slug="visionflow-studio",
            organization_name="VisionFlow Studio",
            identity_subject="oidc|intelligence-worker",
            role=OrganizationRole.SERVICE,
        )

        BootstrapAdministrator(repository).execute(command)

        self.assertEqual(OrganizationRole.SERVICE, repository.commands[0].role)
