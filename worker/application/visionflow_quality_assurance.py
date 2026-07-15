"""QA_PENDING -> RENDERED use case; approval remains a human boundary."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Protocol

from worker.domain.visionflow_qa_contract import MediaInspection, QaReport, RenderArtifactForQa, validate_short_form_artifact


class WorkflowGateway(Protocol):
    def advance_workflow(self, workflow_run_id: str, expected_state: str, target_state: str, output_payload: dict, *, trace_id: str | None = None) -> dict: ...


class MediaInspector(Protocol):
    def inspect(self, artifact: RenderArtifactForQa) -> MediaInspection: ...


@dataclass(frozen=True)
class QualityAssuranceResult:
    workflow_run_id: str
    report: QaReport


class VisionFlowQualityAssurance:
    """Validates a stored export without reading legacy persistence.

    This intentionally stops at ``RENDERED``. Moving to ``APPROVAL_PENDING``
    and approving/publishing are separate, human-governed operations.
    """

    def __init__(self, gateway: WorkflowGateway, inspector: MediaInspector) -> None:
        self._gateway = gateway
        self._inspector = inspector

    def execute(self, workflow_run_id: str, artifact: RenderArtifactForQa, *, trace_id: str | None = None) -> QualityAssuranceResult:
        inspection = self._inspector.inspect(artifact)
        report = validate_short_form_artifact(artifact, inspection)
        self._gateway.advance_workflow(
            workflow_run_id,
            "QA_PENDING",
            "RENDERED",
            {"artifact": asdict(artifact), "inspection": asdict(inspection), "qa": asdict(report)},
            trace_id=trace_id,
        )
        return QualityAssuranceResult(workflow_run_id, report)
