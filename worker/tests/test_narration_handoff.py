"""VF-03.02a Commit 2 — Unit & Integration tests for narration handoff and shadow reconciliation."""
from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from worker.application.narration_handoff import (
    ControlPlaneNarrationSink,
    MySqlNarrationSink,
    NarrationHandoffCoordinator,
    ShadowReconciler,
)
from worker.config import ConfigurationError
from worker.domain.narration_sink import get_deterministic_workflow_run_id


class FakeClient:
    """Mock client for Control Plane narration endpoint requests."""
    def __init__(self, complete_narration_mock: MagicMock) -> None:
        self.complete_narration = complete_narration_mock


class NarrationHandoffTests(unittest.TestCase):

    def setUp(self) -> None:
        self.job_id = 999
        self.hook = "Get ready for a crazy adventure!"
        self.full_script = "This is a full script for testing. It has more than forty characters to pass validation checks."
        self.scenes_layout = [
            {"scene_id": "scene-1", "narration": "Narration 1", "visual_prompt": "Prompt 1", "duration": 5},
            {"scene_id": "scene-2", "narration": "Narration 2", "visual_prompt": "Prompt 2", "duration": 6},
        ]
        self.seo_tags = {"source_metadata": {"provider": "openai", "model": "gpt-4"}}

    def test_legacy_mode_only_calls_mysql(self) -> None:
        mysql_sink = MagicMock()
        cp_sink = MagicMock()
        reconciler = MagicMock()
        coordinator = NarrationHandoffCoordinator(mysql_sink, cp_sink, reconciler)

        env = {"VISIONFLOW_NARRATION_HANDOFF_MODE": "legacy", "APP_ENV": "development"}
        with patch.dict(os.environ, env, clear=True):
            coordinator.handle_narration(self.job_id, self.hook, self.full_script, self.scenes_layout, self.seo_tags)

        mysql_sink.save_narration_result.assert_called_once()
        cp_sink.save_narration_result.assert_not_called()
        reconciler.reconcile.assert_not_called()

    def test_shadow_mode_calls_both_and_reconciles(self) -> None:
        mysql_sink = MagicMock()
        mysql_sink.save_narration_result.return_value = {"success": True, "source": "legacy"}

        cp_sink = MagicMock()
        cp_sink.save_narration_result.return_value = {
            "success": True,
            "source": "control_plane",
            "version_id": "v-123",
            "version": 1,
            "state": "SCRIPTED",
            "idempotency_key": "narration-key-123",
            "workflow_run_id": "run-uuid-123",
        }

        reconciler = MagicMock()
        coordinator = NarrationHandoffCoordinator(mysql_sink, cp_sink, reconciler)

        env = {
            "VISIONFLOW_NARRATION_HANDOFF_MODE": "shadow",
            "APP_ENV": "staging",
            "VISIONFLOW_ORGANIZATION_ID": "00000000-0000-0000-0000-000000000001",
            "VISIONFLOW_CONTROL_PLANE_URL": "http://localhost:8000/api/v1",
        }
        with patch.dict(os.environ, env, clear=True):
            coordinator.handle_narration(self.job_id, self.hook, self.full_script, self.scenes_layout, self.seo_tags)

        mysql_sink.save_narration_result.assert_called_once()
        cp_sink.save_narration_result.assert_called_once()
        reconciler.reconcile.assert_called_once_with(
            self.job_id,
            "run-uuid-123",
            "narration-key-123",
            self.full_script,
            self.scenes_layout,
            cp_sink.save_narration_result.return_value,
            trace_id=None,
        )

    def test_control_plane_mode_only_calls_control_plane(self) -> None:
        mysql_sink = MagicMock()
        cp_sink = MagicMock()
        cp_sink.save_narration_result.return_value = {"success": True, "source": "control_plane"}
        reconciler = MagicMock()
        coordinator = NarrationHandoffCoordinator(mysql_sink, cp_sink, reconciler)

        env = {
            "VISIONFLOW_NARRATION_HANDOFF_MODE": "control_plane",
            "APP_ENV": "staging",
            "VISIONFLOW_ORGANIZATION_ID": "00000000-0000-0000-0000-000000000001",
            "VISIONFLOW_CONTROL_PLANE_URL": "http://localhost:8000/api/v1",
        }
        with patch.dict(os.environ, env, clear=True):
            coordinator.handle_narration(self.job_id, self.hook, self.full_script, self.scenes_layout, self.seo_tags)

        mysql_sink.save_narration_result.assert_not_called()
        cp_sink.save_narration_result.assert_called_once()
        reconciler.assert_not_called()

    def test_control_plane_save_failure_fails_closed_in_control_plane_mode(self) -> None:
        mysql_sink = MagicMock()
        cp_sink = MagicMock()
        cp_sink.save_narration_result.return_value = {"success": False, "error": "API timeout"}
        reconciler = MagicMock()
        coordinator = NarrationHandoffCoordinator(mysql_sink, cp_sink, reconciler)

        env = {
            "VISIONFLOW_NARRATION_HANDOFF_MODE": "control_plane",
            "APP_ENV": "staging",
            "VISIONFLOW_ORGANIZATION_ID": "00000000-0000-0000-0000-000000000001",
            "VISIONFLOW_CONTROL_PLANE_URL": "http://localhost:8000/api/v1",
        }
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(RuntimeError, "Control Plane narration save failed: API timeout"):
                coordinator.handle_narration(self.job_id, self.hook, self.full_script, self.scenes_layout, self.seo_tags)

    def test_reconciler_match_and_mismatch(self) -> None:
        reconciler = ShadowReconciler()
        workflow_run_id = get_deterministic_workflow_run_id(self.job_id)
        idempotency_key = "test-idempotency-key"

        # 1. Match scenario
        cp_result_match = {
            "success": True,
            "version_id": "version-uuid-001",
            "version": 1,
            "state": "SCRIPTED",
        }
        report_match = reconciler.reconcile(
            self.job_id, workflow_run_id, idempotency_key, self.full_script, self.scenes_layout, cp_result_match
        )
        self.assertEqual(report_match["result"], "matched")
        self.assertEqual(report_match["control_plane_version_id"], "version-uuid-001")

        # 2. Mismatch scenario (returned state is not SCRIPTED, e.g. STORYBOARDED)
        cp_result_mismatch = {
            "success": True,
            "version_id": "version-uuid-001",
            "version": 1,
            "state": "QUEUED",
        }
        report_mismatch = reconciler.reconcile(
            self.job_id, workflow_run_id, idempotency_key, self.full_script, self.scenes_layout, cp_result_mismatch
        )
        self.assertEqual(report_mismatch["result"], "mismatched")

        # 3. Control Plane call failed scenario
        cp_result_failed = {
            "success": False,
            "error": "HTTP 500 Internal Error",
        }
        report_failed = reconciler.reconcile(
            self.job_id, workflow_run_id, idempotency_key, self.full_script, self.scenes_layout, cp_result_failed
        )
        self.assertEqual(report_failed["result"], "control-plane-failed")
        self.assertIsNone(report_failed["control_plane_version_id"])

    def test_deterministic_idempotency_key_based_on_script_contents(self) -> None:
        mock_client_fn = MagicMock()
        mock_client_fn.return_value = {"version_id": "v-1", "version": 1, "state": "SCRIPTED"}
        fake_client = FakeClient(mock_client_fn)
        sink = ControlPlaneNarrationSink(fake_client)

        env = {
            "VISIONFLOW_ORGANIZATION_ID": "00000000-0000-0000-0000-000000000001",
            "VISIONFLOW_CONTROL_PLANE_URL": "http://localhost:8000/api/v1",
        }
        with patch.dict(os.environ, env, clear=True):
            res = sink.save_narration_result(self.job_id, self.hook, self.full_script, self.scenes_layout, self.seo_tags)

        self.assertTrue(res["success"])
        idem_key_1 = res["idempotency_key"]

        # Retry with the exact same script content must yield the identical idempotency key
        with patch.dict(os.environ, env, clear=True):
            res2 = sink.save_narration_result(self.job_id, self.hook, self.full_script, self.scenes_layout, self.seo_tags)
        self.assertEqual(idem_key_1, res2["idempotency_key"])

        # Changing script content must yield a different idempotency key
        different_script = "A completely different script narration contents for verification purposes."
        with patch.dict(os.environ, env, clear=True):
            res3 = sink.save_narration_result(self.job_id, self.hook, different_script, self.scenes_layout, self.seo_tags)
        self.assertNotEqual(idem_key_1, res3["idempotency_key"])

    def test_safe_diagnostics_without_exposing_script_contents_on_failure(self) -> None:
        mock_client_fn = MagicMock(side_effect=Exception("Database connection timed out or auth token is expired"))
        fake_client = FakeClient(mock_client_fn)
        sink = ControlPlaneNarrationSink(fake_client)

        env = {
            "VISIONFLOW_ORGANIZATION_ID": "00000000-0000-0000-0000-000000000001",
            "VISIONFLOW_CONTROL_PLANE_URL": "http://localhost:8000/api/v1",
        }
        with patch.dict(os.environ, env, clear=True):
            res = sink.save_narration_result(self.job_id, self.hook, self.full_script, self.scenes_layout, self.seo_tags)

        self.assertFalse(res["success"])
        # Verify script contents are not leaked in the return dict error message
        self.assertNotIn(self.full_script, res["error"])
        self.assertEqual(res["error"], "Database connection timed out or auth token is expired")


if __name__ == "__main__":
    unittest.main()
