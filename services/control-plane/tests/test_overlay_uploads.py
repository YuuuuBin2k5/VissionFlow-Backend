import unittest
import uuid
from unittest.mock import Mock

from app.infrastructure.overlay_uploads import (
    OverlayAssetVerifier,
    OverlayUploadIssuer,
    OverlayUploadVerificationError,
    PrivateObjectPreviewIssuer,
    composition_overlay_object_keys,
)


class OverlayUploadIssuerTests(unittest.TestCase):
    def test_issues_workflow_scoped_presigned_put_for_png(self):
        client = Mock()
        client.generate_presigned_url.return_value = "https://storage.example/upload"
        ticket = OverlayUploadIssuer(client, "visionflow-assets").issue(
            workflow_run_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            filename="brand.png", content_type="image/png", byte_size=2048,
        )
        self.assertTrue(ticket.object_key.startswith("visionflow/00000000-0000-0000-0000-000000000001/uploads/"))
        self.assertEqual({"Content-Type": "image/png"}, ticket.required_headers)
        self.assertEqual("put_object", client.generate_presigned_url.call_args.args[0])

    def test_rejects_unsupported_or_oversize_inputs(self):
        issuer = OverlayUploadIssuer(Mock(), "visionflow-assets")
        with self.assertRaisesRegex(ValueError, "PNG"):
            issuer.issue(workflow_run_id=uuid.uuid4(), filename="brand.gif", content_type="image/gif", byte_size=10)
        with self.assertRaisesRegex(ValueError, "15 MiB"):
            issuer.issue(workflow_run_id=uuid.uuid4(), filename="brand.png", content_type="image/png", byte_size=16 * 1024 * 1024)

    def test_verifies_head_object_before_locking_overlay_revision(self):
        client = Mock()
        client.head_object.return_value = {"ContentType": "image/png", "ContentLength": 2048}
        run_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        key = f"visionflow/{run_id}/uploads/logo.png"
        OverlayAssetVerifier(client, "visionflow-assets").verify(workflow_run_id=run_id, object_keys=(key,))
        client.head_object.assert_called_once_with(Bucket="visionflow-assets", Key=key)

    def test_rejects_cross_workflow_or_invalid_head_object(self):
        verifier = OverlayAssetVerifier(Mock(), "visionflow-assets")
        with self.assertRaisesRegex(OverlayUploadVerificationError, "does not belong"):
            verifier.verify(workflow_run_id=uuid.uuid4(), object_keys=("visionflow/other/uploads/logo.png",))

    def test_extracts_only_active_overlay_asset_keys(self):
        composition = {"tracks": [{"track_type": "overlay", "muted": False, "clips": [{"source_type": "asset", "source_ref": "visionflow/run/uploads/a.png"}]}, {"track_type": "video", "clips": [{"source_type": "asset", "source_ref": "ignored"}]}]}
        self.assertEqual(("visionflow/run/uploads/a.png",), composition_overlay_object_keys(composition))

    def test_issues_get_only_for_the_workflow_final_export(self):
        client = Mock()
        client.generate_presigned_url.return_value = "https://storage.example/preview"
        run_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        ticket = PrivateObjectPreviewIssuer(client, "visionflow-assets").issue_final_export(
            workflow_run_id=run_id,
            object_key=f"visionflow/{run_id}/exports/final.mp4",
        )
        self.assertEqual("https://storage.example/preview", ticket.download_url)
        self.assertEqual("get_object", client.generate_presigned_url.call_args.args[0])
        with self.assertRaisesRegex(OverlayUploadVerificationError, "does not belong"):
            PrivateObjectPreviewIssuer(Mock(), "visionflow-assets").issue_final_export(
                workflow_run_id=run_id,
                object_key="visionflow/other/exports/final.mp4",
            )
