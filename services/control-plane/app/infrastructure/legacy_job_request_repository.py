from __future__ import annotations

import hashlib
import json
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.request_legacy_job import (
    LegacyJobRequestConflict,
    LegacyJobRequestResult,
    RequestLegacyJobCommand,
)
from app.domain.workflow import WorkflowState, require_transition
from app.infrastructure.models import CommandReceipt, OutboxEvent, VideoProject, WorkflowRun, WorkflowStep


class SqlAlchemyLegacyJobRequestRepository:
    """PostgreSQL transaction for the isolated VisionFlow -> legacy intake flow."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def request(self, command: RequestLegacyJobCommand) -> LegacyJobRequestResult:
        try:
            return self._request(command)
        except Exception:
            self._session.rollback()
            raise

    def _request(self, command: RequestLegacyJobCommand) -> LegacyJobRequestResult:
        idempotency_key = str(command.source_command_id)
        fingerprint = _fingerprint(command)
        receipt = self._session.scalar(
            select(CommandReceipt)
            .where(CommandReceipt.idempotency_key == idempotency_key)
            .with_for_update()
        )
        if receipt is not None:
            if (
                receipt.operation_type == "request_legacy_job"
                and receipt.organization_id == command.organization_id
                and receipt.workflow_run_id == command.workflow_run_id
                and receipt.request_fingerprint == fingerprint
            ):
                payload = receipt.result_payload
                self._session.rollback()
                return LegacyJobRequestResult(
                    workflow_run_id=uuid.UUID(payload["workflow_run_id"]),
                    source_command_id=uuid.UUID(payload["source_command_id"]),
                    event_id=uuid.UUID(payload["event_id"]),
                    state=WorkflowState(payload["state"]),
                    changed=False,
                )
            raise LegacyJobRequestConflict("source_command_id is already associated with a different request")

        workflow_run = self._session.scalar(
            select(WorkflowRun)
            .join(VideoProject, VideoProject.id == WorkflowRun.project_id)
            .where(VideoProject.organization_id == command.organization_id, WorkflowRun.id == command.workflow_run_id)
            .with_for_update()
        )
        if workflow_run is None:
            raise LookupError("workflow run was not found")
        current_state = WorkflowState(workflow_run.state)
        if current_state != WorkflowState.READY:
            raise LegacyJobRequestConflict("workflow run must be READY before a legacy job can be requested")
        require_transition(current_state, WorkflowState.QUEUED)

        queue_step = self._session.scalar(
            select(WorkflowStep)
            .where(WorkflowStep.workflow_run_id == workflow_run.id, WorkflowStep.step_key == "queue")
            .with_for_update()
        )
        if queue_step is None:
            self._session.add(
                WorkflowStep(
                    workflow_run_id=workflow_run.id,
                    step_key="queue",
                    state=WorkflowState.QUEUED.value,
                    attempt_count=1,
                    output_payload={"source_command_id": str(command.source_command_id)},
                )
            )
        else:
            queue_step.state = WorkflowState.QUEUED.value
            queue_step.attempt_count += 1
            queue_step.output_payload = {"source_command_id": str(command.source_command_id)}
        workflow_run.state = WorkflowState.QUEUED.value

        event_id = uuid.uuid4()
        project = self._session.get(VideoProject, workflow_run.project_id)
        if project is None:
            raise LookupError("project for workflow run was not found")
        event = OutboxEvent(
            id=event_id,
            aggregate_type="workflow_run",
            aggregate_id=workflow_run.id,
            event_type="visionflow.legacy_job.requested.v1",
            payload={
                "event_version": 1,
                "event_id": str(event_id),
                "source_command_id": str(command.source_command_id),
                "organization_id": str(command.organization_id),
                "workflow_run_id": str(workflow_run.id),
                # This is a point-in-time command snapshot. The legacy intake
                # must not re-query PostgreSQL or infer fields from a UUID.
                "intake": {
                    "title": project.title,
                    "brief": project.brief,
                    "format_profile": project.format_profile,
                    "timezone": project.timezone,
                    "input_payload": workflow_run.input_payload,
                    "prompt_manifest": workflow_run.prompt_manifest,
                },
            },
            trace_id=command.trace_id,
        )
        self._session.add(event)
        self._session.add(
            OutboxEvent(
                aggregate_type="workflow_run",
                aggregate_id=workflow_run.id,
                event_type="visionflow.workflow_run.state_changed.v1",
                payload={
                    "workflow_run_id": str(workflow_run.id),
                    "from_state": current_state.value,
                    "to_state": WorkflowState.QUEUED.value,
                    "step_key": "queue",
                },
                trace_id=command.trace_id,
            )
        )
        self._session.add(
            CommandReceipt(
                organization_id=command.organization_id,
                operation_type="request_legacy_job",
                idempotency_key=idempotency_key,
                workflow_run_id=workflow_run.id,
                request_fingerprint=fingerprint,
                result_payload={
                    "workflow_run_id": str(workflow_run.id),
                    "source_command_id": str(command.source_command_id),
                    "event_id": str(event_id),
                    "state": WorkflowState.QUEUED.value,
                },
            )
        )
        self._session.commit()
        return LegacyJobRequestResult(
            workflow_run_id=workflow_run.id,
            source_command_id=command.source_command_id,
            event_id=event_id,
            state=WorkflowState.QUEUED,
            changed=True,
        )


def _fingerprint(command: RequestLegacyJobCommand) -> str:
    canonical = json.dumps(
        {
            "organization_id": str(command.organization_id),
            "workflow_run_id": str(command.workflow_run_id),
            "source_command_id": str(command.source_command_id),
            "actor_subject": command.actor_subject,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
