from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.core.config import ConfigurationError  # noqa: E402
from app.core.service_client_registry import ServiceClientRegistry  # noqa: E402


class ServiceClientRegistryTests(unittest.TestCase):
    def test_loads_distinct_least_privilege_clients(self) -> None:
        with patch.dict(os.environ, _environment(), clear=True):
            registry = ServiceClientRegistry.from_env()

        worker = registry.get("visionflow-intelligence-worker")
        intake = registry.get("visionflow-legacy-intake")
        self.assertIsNotNone(worker)
        self.assertIsNotNone(intake)
        self.assertEqual(frozenset({"workflow:narration:complete"}), worker.allowed_scopes)
        self.assertEqual(frozenset({"workflow:legacy-mapping:register"}), intake.allowed_scopes)

    def test_rejects_partial_optional_client_configuration(self) -> None:
        values = _environment()
        values.pop("VISIONFLOW_LEGACY_MAPPING_SUBJECT")
        with patch.dict(os.environ, values, clear=True):
            with self.assertRaisesRegex(ConfigurationError, "must be configured together"):
                ServiceClientRegistry.from_env()


def _environment() -> dict[str, str]:
    return {
        "VISIONFLOW_WORKER_CLIENT_ID": "visionflow-intelligence-worker",
        "VISIONFLOW_WORKER_CLIENT_SECRET": "worker-secret",
        "VISIONFLOW_WORKER_SUBJECT": "service|visionflow-intelligence-worker",
        "VISIONFLOW_LEGACY_MAPPING_CLIENT_ID": "visionflow-legacy-intake",
        "VISIONFLOW_LEGACY_MAPPING_CLIENT_SECRET": "intake-secret",
        "VISIONFLOW_LEGACY_MAPPING_SUBJECT": "service|visionflow-legacy-intake",
    }
