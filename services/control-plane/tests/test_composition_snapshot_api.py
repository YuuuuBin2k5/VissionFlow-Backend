import os
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))


class CompositionSnapshotApiTests(unittest.TestCase):
    """Contract tests for the operator-owned immutable timeline snapshot API."""

    environment = {
        "DATABASE_URL": "postgresql+psycopg://placeholder:placeholder@localhost:5432/visionflow?sslmode=require"
    }

    def setUp(self) -> None:
        self.organization_id = uuid.uuid4()
        self.workflow_run_id = uuid.uuid4()

    def _client(self) -> TestClient:
        with patch.dict(os.environ, self.environment, clear=True):
            from app.core.oidc import VerifiedIdentity
            from app.main import app
            from app.routers import workflows
            from app.routers.auth import require_identity

        app.dependency_overrides[require_identity] = lambda: VerifiedIdentity("oidc|operator", None, None)
        app.dependency_overrides[workflows.get_session] = lambda: object()
        self.addCleanup(app.dependency_overrides.clear)
        return TestClient(app)

    def _snapshot(self, *, state: str = "draft", revision: int = 1) -> dict[str, object]:
        return {
            "document_id": str(uuid.uuid4()),
            "workflow_run_id": str(self.workflow_run_id),
            "revision": revision,
            "active_version_id": None if state == "draft" else str(uuid.uuid4()),
            "version_id": str(uuid.uuid4()),
            "state": state,
            "aspect_ratio": "9:16",
            "canvas_config": {"background": "#000000"},
            "tracks": [{
                "id": str(uuid.uuid4()),
                "track_type": "video",
                "name": "Main footage",
                "muted": False,
                "locked": False,
                "clips": [{
                    "id": str(uuid.uuid4()),
                    "source_type": "asset",
                    "source_ref": "visionflow/run-1/assets/scene-01.mp4",
                    "timeline_start_ms": 0,
                    "duration_ms": 5000,
                    "trim_in_ms": 0,
                    "transform": {},
                    "effects": [{"effect_key": "cinematic_push", "config": {}}],
                    "keyframes": [{"property_key": "scale", "time_ms": 0, "value": {"value": 1}, "easing": "linear"}],
                }],
            }],
        }

    def _payload(self, *, expected_revision: int = 0) -> dict[str, object]:
        return {
            "organization_id": str(self.organization_id),
            "expected_revision": expected_revision,
            "aspect_ratio": "9:16",
            "canvas_config": {"background": "#000000"},
            "tracks": [{
                "track_type": "video",
                "name": "Main footage",
                "clips": [{
                    "source_type": "asset",
                    "source_ref": "visionflow/run-1/assets/scene-01.mp4",
                    "timeline_start_ms": 0,
                    "duration_ms": 5000,
                    "effects": [{"effect_key": "cinematic_push", "config": {}}],
                    "keyframes": [{"property_key": "scale", "time_ms": 0, "value": {"value": 1}}],
                }],
            }],
        }

    def test_requires_bearer_authentication(self) -> None:
        with patch.dict(os.environ, self.environment, clear=True):
            from app.main import app
            response = TestClient(app).get(
                f"/api/v1/workflows/{self.workflow_run_id}/composition",
                params={"organization_id": str(self.organization_id)},
            )
        self.assertEqual(401, response.status_code)

    def test_save_persists_validated_snapshot_with_organization_scope(self) -> None:
        with patch("app.routers.workflows.AuthorizeOrganization") as authorize, patch(
            "app.routers.workflows.SqlAlchemyCompositionRepository"
        ) as repository:
            repository.return_value.save.return_value = self._snapshot()
            response = self._client().put(
                f"/api/v1/workflows/{self.workflow_run_id}/composition",
                headers={"Authorization": "Bearer service-token"}, json=self._payload(),
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual(1, response.json()["revision"])
        saved = repository.return_value.save.call_args.kwargs
        self.assertEqual(self.organization_id, saved["organization_id"])
        self.assertEqual(self.workflow_run_id, saved["workflow_run_id"])
        self.assertEqual(0, saved["expected_revision"])
        self.assertEqual("cinematic_push", saved["tracks"][0]["clips"][0]["effects"][0]["effect_key"])
        authorize.return_value.require.assert_called_once()

    def test_save_rejects_unknown_effect_before_repository_write(self) -> None:
        payload = self._payload()
        payload["tracks"][0]["clips"][0]["effects"] = [{"effect_key": "fade", "config": {}}]
        with patch("app.routers.workflows.AuthorizeOrganization"), patch(
            "app.routers.workflows.SqlAlchemyCompositionRepository"
        ) as repository:
            response = self._client().put(
                f"/api/v1/workflows/{self.workflow_run_id}/composition",
                headers={"Authorization": "Bearer service-token"}, json=payload,
            )

        self.assertEqual(422, response.status_code)
        self.assertIn("unsupported effect", response.json()["detail"])
        repository.return_value.save.assert_not_called()

    def test_lock_maps_optimistic_concurrency_conflict_to_409(self) -> None:
        from app.infrastructure.composition_repository import CompositionConflict

        with patch("app.routers.workflows.AuthorizeOrganization"), patch(
            "app.routers.workflows.SqlAlchemyCompositionRepository"
        ) as repository:
            repository.return_value.lock.side_effect = CompositionConflict("Composition changed by another editor.")
            response = self._client().post(
                f"/api/v1/workflows/{self.workflow_run_id}/composition/lock",
                headers={"Authorization": "Bearer service-token"},
                json={"organization_id": str(self.organization_id), "expected_revision": 1},
            )

        self.assertEqual(409, response.status_code)
        self.assertIn("changed by another editor", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
