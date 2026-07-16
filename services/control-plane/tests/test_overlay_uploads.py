import unittest
import uuid
from unittest.mock import Mock

from app.infrastructure.overlay_uploads import OverlayUploadIssuer


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
