"""VF-03.02a Commit 1 — Unit tests for handoff configuration and validation rules."""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from worker.config import ConfigurationError, validate_config


class NarrationHandoffConfigTests(unittest.TestCase):

    def test_legacy_mode_always_allowed(self) -> None:
        env = {
            "VISIONFLOW_NARRATION_HANDOFF_MODE": "legacy",
            "APP_ENV": "production",
        }
        with patch.dict(os.environ, env, clear=True):
            # Should not raise ConfigurationError
            validate_config()

    def test_invalid_handoff_mode_rejected(self) -> None:
        env = {
            "VISIONFLOW_NARRATION_HANDOFF_MODE": "invalid_mode",
            "APP_ENV": "development",
        }
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(ConfigurationError, "Invalid VISIONFLOW_NARRATION_HANDOFF_MODE"):
                validate_config()

    def test_shadow_and_control_plane_mode_blocked_in_production(self) -> None:
        for mode in ("shadow", "control_plane"):
            env = {
                "VISIONFLOW_NARRATION_HANDOFF_MODE": mode,
                "APP_ENV": "production",
            }
            with patch.dict(os.environ, env, clear=True):
                with self.assertRaisesRegex(ConfigurationError, "not allowed in production environment"):
                    validate_config()

    def test_shadow_mode_requires_org_id_and_url(self) -> None:
        # 1. Missing org ID
        env = {
            "VISIONFLOW_NARRATION_HANDOFF_MODE": "shadow",
            "APP_ENV": "staging",
            "VISIONFLOW_CONTROL_PLANE_URL": "http://localhost:8000/api/v1",
        }
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(ConfigurationError, "VISIONFLOW_ORGANIZATION_ID is required"):
                validate_config()

        # 2. Invalid org ID UUID format
        env = env.copy()
        env["VISIONFLOW_ORGANIZATION_ID"] = "not-a-uuid"
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(ConfigurationError, "must be a valid UUID"):
                validate_config()

        # 3. Missing Control Plane URL
        env = env.copy()
        env["VISIONFLOW_ORGANIZATION_ID"] = "00000000-0000-0000-0000-000000000001"
        env["VISIONFLOW_CONTROL_PLANE_URL"] = ""
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(ConfigurationError, "VISIONFLOW_CONTROL_PLANE_URL is required"):
                validate_config()

        # 4. Valid setup
        env = env.copy()
        env["VISIONFLOW_CONTROL_PLANE_URL"] = "http://localhost:8000/api/v1"
        with patch.dict(os.environ, env, clear=True):
            # Should pass without errors
            validate_config()

    def test_worker_execution_context_validation(self) -> None:
        from worker.domain.narration_sink import WorkerExecutionContext
        # 1. Missing env vars
        env = {}
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(ValueError, "Missing required fields"):
                WorkerExecutionContext.from_env()

        # 2. Invalid UUID
        env = {
            "VISIONFLOW_WORKFLOW_RUN_ID": "not-a-uuid",
            "VISIONFLOW_ORGANIZATION_ID": "00000000-0000-0000-0000-000000000001",
            "VISIONFLOW_NARRATION_ATTEMPT_ID": "attempt-1",
            "VISIONFLOW_TRACE_ID": "a" * 32,
        }
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(ValueError, "Invalid UUID"):
                WorkerExecutionContext.from_env()

        # 3. Empty attempt ID
        env = {
            "VISIONFLOW_WORKFLOW_RUN_ID": "00000000-0000-0000-0000-000000000002",
            "VISIONFLOW_ORGANIZATION_ID": "00000000-0000-0000-0000-000000000001",
            "VISIONFLOW_NARRATION_ATTEMPT_ID": "   ",
            "VISIONFLOW_TRACE_ID": "a" * 32,
        }
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(ValueError, "Empty narration_attempt_id"):
                WorkerExecutionContext.from_env()

        # 4. Valid setup
        env = {
            "VISIONFLOW_WORKFLOW_RUN_ID": "00000000-0000-0000-0000-000000000002",
            "VISIONFLOW_ORGANIZATION_ID": "00000000-0000-0000-0000-000000000001",
            "VISIONFLOW_NARRATION_ATTEMPT_ID": "attempt-1",
            "VISIONFLOW_TRACE_ID": "a" * 32,
        }
        with patch.dict(os.environ, env, clear=True):
            ctx = WorkerExecutionContext.from_env()
            self.assertEqual(ctx.narration_attempt_id, "attempt-1")


if __name__ == "__main__":
    unittest.main()
