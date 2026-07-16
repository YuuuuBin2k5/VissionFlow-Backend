import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace


SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.routers.integrations import _AttemptLeaseInvalid, _require_attempt_lease, _validate_failure_code  # noqa: E402


class PublicationAttemptLeaseTests(unittest.TestCase):
    def test_accepts_matching_unexpired_claim_lease(self) -> None:
        attempt = SimpleNamespace(
            state="claimed",
            lease_token="a" * 64,
            lease_expires_at=datetime.now(UTC) + timedelta(seconds=10),
        )
        _require_attempt_lease(attempt, "a" * 64)

    def test_rejects_wrong_or_expired_lease(self) -> None:
        attempt = SimpleNamespace(
            state="claimed",
            lease_token="a" * 64,
            lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        with self.assertRaises(_AttemptLeaseInvalid):
            _require_attempt_lease(attempt, "b" * 64)

    def test_rejects_provider_error_details_as_failure_codes(self) -> None:
        with self.assertRaises(ValueError):
            _validate_failure_code("provider message: token expired")


if __name__ == "__main__":
    unittest.main()
