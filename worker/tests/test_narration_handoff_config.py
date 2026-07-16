"""VF-03.02a.2 — Unit tests for handoff configuration and context validation rules."""
from __future__ import annotations

import os
import unittest
import uuid
from unittest.mock import patch

from worker.config import ConfigurationError, validate_config
from worker.domain.narration_sink import WorkerExecutionContext


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

    def test_worker_execution_context_validation_from_env(self) -> None:
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

    def test_worker_execution_context_validation_from_api_response(self) -> None:
        # 1. Missing fields
        payload = {}
        with self.assertRaisesRegex(ValueError, "Missing workflow_run_id"):
            WorkerExecutionContext.from_api_response(payload)

        payload = {"workflow_run_id": "00000000-0000-0000-0000-000000000002"}
        with self.assertRaisesRegex(ValueError, "Missing organization_id"):
            WorkerExecutionContext.from_api_response(payload)

        payload = {
            "workflow_run_id": "00000000-0000-0000-0000-000000000002",
            "organization_id": "00000000-0000-0000-0000-000000000001",
        }
        with self.assertRaisesRegex(ValueError, "Missing or empty narration_attempt_id"):
            WorkerExecutionContext.from_api_response(payload)

        # 2. Invalid UUIDs
        payload = {
            "workflow_run_id": "not-a-uuid",
            "organization_id": "00000000-0000-0000-0000-000000000001",
            "narration_attempt_id": "attempt-1",
        }
        with self.assertRaisesRegex(ValueError, "Invalid workflow_run_id UUID"):
            WorkerExecutionContext.from_api_response(payload)

        payload = {
            "workflow_run_id": "00000000-0000-0000-0000-000000000002",
            "organization_id": "not-a-uuid",
            "narration_attempt_id": "attempt-1",
        }
        with self.assertRaisesRegex(ValueError, "Invalid organization_id UUID"):
            WorkerExecutionContext.from_api_response(payload)

        # 3. Valid setup
        payload = {
            "workflow_run_id": "00000000-0000-0000-0000-000000000002",
            "organization_id": "00000000-0000-0000-0000-000000000001",
            "narration_attempt_id": "attempt-1",
            "trace_id": "api-trace-id",
            "issued_at": "2026-07-16T12:00:00Z",
            "event_version": 2,
        }
        ctx = WorkerExecutionContext.from_api_response(payload, legacy_job_id=999, trace_id="override-trace")
        self.assertEqual(ctx.workflow_run_id, uuid.UUID("00000000-0000-0000-0000-000000000002"))
        self.assertEqual(ctx.organization_id, uuid.UUID("00000000-0000-0000-0000-000000000001"))
        self.assertEqual(ctx.narration_attempt_id, "attempt-1")
        self.assertEqual(ctx.trace_id, "override-trace")
        self.assertEqual(ctx.legacy_job_id, "999")
        self.assertEqual(ctx.issued_at, "2026-07-16T12:00:00Z")
        self.assertEqual(ctx.event_version, 2)


if __name__ == "__main__":
    unittest.main()
