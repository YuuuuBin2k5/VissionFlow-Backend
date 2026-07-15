from __future__ import annotations

import unittest

from worker.application.visionflow_quality_assurance import VisionFlowQualityAssurance
from worker.domain.visionflow_qa_contract import (
    MediaInspection,
    QualityContractViolation,
    RenderArtifactForQa,
)


class Gateway:
    def __init__(self):
        self.calls = []

    def advance_workflow(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return {"changed": True}


class Inspector:
    def __init__(self, inspection):
        self.inspection = inspection

    def inspect(self, artifact):
        return self.inspection


def artifact():
    return RenderArtifactForQa("visionflow/run-1/exports/final.mp4", "video/mp4", 20_000, "a" * 64)


class VisionFlowQualityAssuranceTests(unittest.TestCase):
    def test_passed_export_moves_only_to_rendered_with_audit_payload(self):
        gateway = Gateway()
        qa = VisionFlowQualityAssurance(gateway, Inspector(MediaInspection(45.0, 1080, 1920, "h264", True)))

        result = qa.execute("run-1", artifact(), trace_id="a" * 32)

        self.assertTrue(result.report.passed)
        self.assertEqual(1, len(gateway.calls))
        args, kwargs = gateway.calls[0]
        self.assertEqual(("run-1", "QA_PENDING", "RENDERED"), args[:3])
        self.assertNotIn("APPROVAL_PENDING", args)
        self.assertEqual("visionflow/run-1/exports/final.mp4", args[3]["artifact"]["object_key"])
        self.assertEqual("a" * 32, kwargs["trace_id"])

    def test_failed_qa_does_not_advance_or_bypass_manual_review(self):
        gateway = Gateway()
        qa = VisionFlowQualityAssurance(gateway, Inspector(MediaInspection(8.0, 1920, 1080, "vp9", False)))

        with self.assertRaises(QualityContractViolation):
            qa.execute("run-1", artifact())

        self.assertEqual([], gateway.calls)


if __name__ == "__main__":
    unittest.main()
