import sys
import unittest
import uuid
from pathlib import Path


SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.application.local_auth import (  # noqa: E402
    AuthenticateLocalUser,
    AuthenticateLocalUserCommand,
    InvalidCredentials,
    LocalEmailAlreadyRegistered,
    RegisterLocalUser,
    RegisterLocalUserCommand,
)
from app.domain.local_auth import LocalAuthUser  # noqa: E402


class FakeHasher:
    def hash(self, password: str) -> str:
        return f"hash::{password}"

    def verify(self, password_hash: str, password: str) -> bool:
        return password_hash == self.hash(password)


class FakeRepository:
    def __init__(self) -> None:
        self.users: dict[str, LocalAuthUser] = {}
        self.audits: list[tuple[uuid.UUID | None, str, str]] = []

    def find_by_email(self, email: str) -> LocalAuthUser | None:
        return self.users.get(email)

    def create_user(self, *, email: str, password_hash: str, display_name: str | None) -> LocalAuthUser:
        user = LocalAuthUser(uuid.uuid4(), uuid.uuid4(), email, password_hash, True)
        self.users[email] = user
        return user

    def record_audit(self, *, auth_user_id, event_type, outcome, metadata=None) -> None:
        self.audits.append((auth_user_id, event_type, outcome))


class LocalAuthTests(unittest.TestCase):
    def test_registers_with_canonical_email_and_hashes_password(self) -> None:
        repository = FakeRepository()
        user = RegisterLocalUser(repository, FakeHasher()).execute(
            RegisterLocalUserCommand(email="  Operator@VisionFlow.dev ", password="correct horse battery")
        )
        self.assertEqual("operator@visionflow.dev", user.email)
        self.assertEqual("hash::correct horse battery", user.password_hash)
        self.assertEqual((user.id, "registration", "succeeded"), repository.audits[-1])

    def test_duplicate_registration_is_rejected_without_hashing_a_second_password(self) -> None:
        repository = FakeRepository()
        use_case = RegisterLocalUser(repository, FakeHasher())
        command = RegisterLocalUserCommand(email="operator@visionflow.dev", password="correct horse battery")
        use_case.execute(command)
        with self.assertRaises(LocalEmailAlreadyRegistered):
            use_case.execute(command)
        self.assertEqual((None, "registration", "rejected"), repository.audits[-1])

    def test_authentication_returns_generic_failure_for_unknown_or_wrong_credentials(self) -> None:
        repository = FakeRepository()
        RegisterLocalUser(repository, FakeHasher()).execute(
            RegisterLocalUserCommand(email="operator@visionflow.dev", password="correct horse battery")
        )
        auth = AuthenticateLocalUser(repository, FakeHasher())
        with self.assertRaises(InvalidCredentials):
            auth.execute(AuthenticateLocalUserCommand(email="operator@visionflow.dev", password="wrong password!"))
        with self.assertRaises(InvalidCredentials):
            auth.execute(AuthenticateLocalUserCommand(email="unknown@visionflow.dev", password="wrong password!"))
        self.assertEqual("failed", repository.audits[-1][2])

    def test_rejects_short_password(self) -> None:
        with self.assertRaisesRegex(ValueError, "12-1024"):
            RegisterLocalUser(FakeRepository(), FakeHasher()).execute(
                RegisterLocalUserCommand(email="operator@visionflow.dev", password="short")
            )
