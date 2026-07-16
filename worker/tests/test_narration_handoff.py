"""VF-03.02a.1 — Unit & Integration tests for narration handoff and shadow reconciliation."""
from __future__ import annotations

import os
import unittest
import uuid
from unittest.mock import MagicMock, patch

from worker.application.narration_handoff import (
    ControlPlaneNarrationSink,
    MySqlNarrationSink,
    NarrationHandoffCoordinator,
    ShadowReconciler,
)
from worker.config import ConfigurationError
from worker.domain.narration_sink import WorkerExecutionContext


class FakeClient:
    """Mock client for Control Plane narration endpoint requests."""
    def __init__(self, complete_narration_mock: MagicMock, get_creative_document_mock: MagicMock | None = None) -> None:
        self.complete_narration = complete_narration_mock
        if get_creative_document_mock:
            self.get_creative_document = get_creative_document_mock
        self._settings = MagicMock()
        self._settings.organization_id = uuid.UUID("00000000-0000-0000-0000-000000000001")


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
        self.context = WorkerExecutionContext(
            workflow_run_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
            organization_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            narration_attempt_id="attempt-1",
            trace_id="a" * 32,
        )

    def test_legacy_mode_only_calls_mysql(self) -> None:
        mysql_sink = MagicMock()
        cp_sink = MagicMock()
        reconciler = MagicMock()
        coordinator = NarrationHandoffCoordinator(mysql_sink, cp_sink, reconciler)

        env = {"VISIONFLOW_NARRATION_HANDOFF_MODE": "legacy", "APP_ENV": "development"}
        with patch.dict(os.environ, env, clear=True):
            coordinator.handle_narration(
                self.job_id, self.hook, self.full_script, self.scenes_layout, self.seo_tags, context=self.context
            )

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
        }

        reconciler = MagicMock()
        client = MagicMock()
        coordinator = NarrationHandoffCoordinator(mysql_sink, cp_sink, reconciler, client=client)

        env = {
            "VISIONFLOW_NARRATION_HANDOFF_MODE": "shadow",
            "APP_ENV": "staging",
            "VISIONFLOW_ORGANIZATION_ID": "00000000-0000-0000-0000-000000000001",
            "VISIONFLOW_CONTROL_PLANE_URL": "http://localhost:8000/api/v1",
        }
        with patch.dict(os.environ, env, clear=True):
            coordinator.handle_narration(
                self.job_id, self.hook, self.full_script, self.scenes_layout, self.seo_tags, context=self.context
            )

        mysql_sink.save_narration_result.assert_called_once()
        cp_sink.save_narration_result.assert_called_once()
        reconciler.reconcile.assert_called_once_with(
            self.job_id,
            self.context,
            "narration-key-123",
            self.full_script,
            self.scenes_layout,
            cp_sink.save_narration_result.return_value,
            coordinator._client,
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
            coordinator.handle_narration(
                self.job_id, self.hook, self.full_script, self.scenes_layout, self.seo_tags, context=self.context
            )

        mysql_sink.save_narration_result.assert_not_called()
        cp_sink.save_narration_result.assert_called_once()
        reconciler.assert_not_called()

    def test_control_plane_save_failure_fails_closed_in_control_plane_mode(self) -> None:
        mysql_sink = MagicMock()
        cp_sink = MagicMock()
        cp_sink.save_narration_result.return_value = {"success": False, "error_code": "CONTROL_PLANE_TIMEOUT"}
        reconciler = MagicMock()
        coordinator = NarrationHandoffCoordinator(mysql_sink, cp_sink, reconciler)

        env = {
            "VISIONFLOW_NARRATION_HANDOFF_MODE": "control_plane",
            "APP_ENV": "staging",
            "VISIONFLOW_ORGANIZATION_ID": "00000000-0000-0000-0000-000000000001",
            "VISIONFLOW_CONTROL_PLANE_URL": "http://localhost:8000/api/v1",
        }
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(RuntimeError, "Control Plane narration save failed with error code: CONTROL_PLANE_TIMEOUT"):
                coordinator.handle_narration(
                    self.job_id, self.hook, self.full_script, self.scenes_layout, self.seo_tags, context=self.context
                )

    def test_reconciler_match_and_mismatch(self) -> None:
        reconciler = ShadowReconciler()
        idempotency_key = "test-idempotency-key"

        # Mock client to fetch creative document
        client = MagicMock()
        client.get_creative_document.return_value = {
            "script": self.full_script,
            "scenes": [
                {
                    "position": 0,
                    "narration": "Narration 1",
                    "visual_prompt": "Prompt 1",
                    "duration_seconds": 5,
                    "transition": "cut",
                    "caption": None,
                },
                {
                    "position": 1,
                    "narration": "Narration 2",
                    "visual_prompt": "Prompt 2",
                    "duration_seconds": 6,
                    "transition": "cut",
                    "caption": None,
                },
            ]
        }

        # 1. Match scenario
        cp_result_match = {
            "success": True,
            "version_id": "version-uuid-001",
            "version": 1,
        }
        report_match = reconciler.reconcile(
            self.job_id, self.context, idempotency_key, self.full_script, self.scenes_layout, cp_result_match, client
        )
        self.assertEqual(report_match["result"], "matched")
        self.assertEqual(report_match["control_plane_version_id"], "version-uuid-001")
        self.assertEqual(len(report_match["mismatch_codes"]), 0)

        # 2. Mismatch scenario (changed script)
        different_script = "A completely different script narration contents for verification purposes."
        report_mismatch = reconciler.reconcile(
            self.job_id, self.context, idempotency_key, different_script, self.scenes_layout, cp_result_match, client
        )
        self.assertEqual(report_mismatch["result"], "mismatched")
        self.assertIn("SCRIPT_HASH_MISMATCH", report_mismatch["mismatch_codes"])

        # 3. Control Plane call failed scenario
        cp_result_failed = {
            "success": False,
            "error_code": "CONTROL_PLANE_TIMEOUT",
        }
        report_failed = reconciler.reconcile(
            self.job_id, self.context, idempotency_key, self.full_script, self.scenes_layout, cp_result_failed, client
        )
        self.assertEqual(report_failed["result"], "control-plane-failed")
        self.assertEqual(report_failed["error_code"], "CONTROL_PLANE_TIMEOUT")
        self.assertIsNone(report_failed["control_plane_version_id"])

    def test_idempotency_key_bound_to_attempt(self) -> None:
        mock_client_fn = MagicMock()
        mock_client_fn.return_value = {"version_id": "v-1", "version": 1, "state": "SCRIPTED"}
        fake_client = FakeClient(mock_client_fn)
        sink = ControlPlaneNarrationSink(fake_client)

        # Same attempt, same script => same key
        res = sink.save_narration_result(
            self.job_id, self.hook, self.full_script, self.scenes_layout, self.seo_tags, context=self.context
        )
        self.assertTrue(res["success"])
        key_1 = res["idempotency_key"]

        # Retry with the same attempt but changed script content => MUST yield the same key
        changed_script = "Changed script content but running under the same execution context attempt ID."
        res2 = sink.save_narration_result(
            self.job_id, self.hook, changed_script, self.scenes_layout, self.seo_tags, context=self.context
        )
        self.assertEqual(key_1, res2["idempotency_key"])

        # Different attempt => MUST yield a different key
        context_diff = WorkerExecutionContext(
            workflow_run_id=self.context.workflow_run_id,
            organization_id=self.context.organization_id,
            narration_attempt_id="attempt-2",
            trace_id=self.context.trace_id,
        )
        res3 = sink.save_narration_result(
            self.job_id, self.hook, self.full_script, self.scenes_layout, self.seo_tags, context=context_diff
        )
        self.assertNotEqual(key_1, res3["idempotency_key"])

    def test_safe_diagnostics_without_exposing_script_contents_on_failure(self) -> None:
        mock_client_fn = MagicMock(side_effect=Exception("Database connection timed out or auth token is expired"))
        fake_client = FakeClient(mock_client_fn)
        sink = ControlPlaneNarrationSink(fake_client)

        res = sink.save_narration_result(
            self.job_id, self.hook, self.full_script, self.scenes_layout, self.seo_tags, context=self.context
        )

        self.assertFalse(res["success"])
        # Verify script contents are not leaked in the return dict error
        self.assertNotIn(self.full_script, str(res))
        self.assertEqual(res["error_code"], "CONTROL_PLANE_INTERNAL_ERROR")


if __name__ == "__main__":
    unittest.main()
