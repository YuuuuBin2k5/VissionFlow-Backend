from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


SERVICE_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = SERVICE_ROOT.parents[2]
sys.path[:0] = [str(SERVICE_ROOT), str(BACKEND_ROOT)]


class WorkflowDeleteContractTests(unittest.TestCase):
    def test_single_delete_route_is_registered_once(self) -> None:
        from app.routers.workflows import router

        routes = [
            route
            for route in router.routes
            if getattr(route, "path", "") == "/workflows/{workflow_run_id}"
            and "DELETE" in (getattr(route, "methods", set()) or set())
        ]

        self.assertEqual(1, len(routes))

    def test_active_workflow_is_not_deletable(self) -> None:
        from app.routers.workflows import _get_deletable_workflow

        session = MagicMock()
        session.scalar.return_value = SimpleNamespace(state="RENDERING")

        with self.assertRaisesRegex(ValueError, "Cancel the workflow first"):
            _get_deletable_workflow(
                session,
                organization_id=uuid.uuid4(),
                workflow_run_id=uuid.uuid4(),
            )

    def test_storage_failure_preserves_workflow_records(self) -> None:
        from app.routers.workflows import WorkflowStorageCleanupError, _delete_workflow_records

        asset = SimpleNamespace(object_key="visionflow/run/export.mp4")
        scalars = MagicMock()
        scalars.all.return_value = [asset]
        session = MagicMock()
        session.scalars.return_value = scalars
        run = SimpleNamespace(id=uuid.uuid4())

        with patch("app.routers.workflows.PrivateObjectPreviewIssuer.from_env", side_effect=RuntimeError("R2 unavailable")):
            with self.assertRaises(WorkflowStorageCleanupError):
                _delete_workflow_records(session, run)

        session.execute.assert_not_called()
        session.delete.assert_not_called()


class VideoVaultDeleteContractTests(unittest.TestCase):
    def test_r2_delete_failure_is_not_swallowed(self) -> None:
        from app.routers.video_vault import _delete_r2_object

        issuer = MagicMock()
        issuer.delete_object.side_effect = RuntimeError("access denied")
        with patch("app.routers.video_vault.PrivateObjectPreviewIssuer.from_env", return_value=issuer):
            with self.assertRaisesRegex(RuntimeError, "access denied"):
                _delete_r2_object("visionflow/run/export.mp4")


class UploadedSourceDeleteTests(unittest.TestCase):
    def test_uploaded_source_can_be_deleted_by_server_issued_id(self) -> None:
        from fastapi import UploadFile
        from production import production_controller

        with tempfile.TemporaryDirectory() as directory:
            upload_root = Path(directory)
            with patch.object(production_controller, "UPLOADS_DIR", upload_root):
                upload = UploadFile(filename="source.mp4", file=__import__("io").BytesIO(b"video"))
                result = asyncio.run(production_controller._handle_upload_source(upload))
                stored = Path(result["file_ref"])
                self.assertTrue(stored.exists())

                deleted = production_controller._handle_delete_uploaded_source(result["source_id"])

                self.assertTrue(deleted["deleted"])
                self.assertFalse(stored.exists())

    def test_uploaded_source_rejects_path_traversal_identifier(self) -> None:
        from fastapi import HTTPException
        from production.production_controller import _handle_delete_uploaded_source

        with self.assertRaises(HTTPException) as raised:
            _handle_delete_uploaded_source("../../secrets")

        self.assertEqual(422, raised.exception.status_code)


if __name__ == "__main__":
    unittest.main()
