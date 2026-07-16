from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.advance_workflow import (
    AdvanceWorkflowCommand,
    WorkflowStateConflict,
    WorkflowTransitionResult,
)
from app.domain.workflow import WorkflowState, require_transition
from app.infrastructure.models import OutboxEvent, VideoProject, WorkflowRun, WorkflowStep


class SqlAlchemyWorkflowProgressionRepository:
    """Serialized PostgreSQL transitions with idempotent worker-result submission."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def advance(self, command: AdvanceWorkflowCommand) -> WorkflowTransitionResult:
        try:
            return self._advance(command)
        except Exception:
            self._session.rollback()
            raise

    def _advance(self, command: AdvanceWorkflowCommand) -> WorkflowTransitionResult:
        workflow_run = self._session.scalar(
            select(WorkflowRun)
            .join(VideoProject, VideoProject.id == WorkflowRun.project_id)
            .where(VideoProject.organization_id == command.organization_id)
            .where(WorkflowRun.id == command.workflow_run_id)
            .with_for_update()
        )
        if workflow_run is None:
            raise LookupError(f"workflow run '{command.workflow_run_id}' was not found")

        current_state = WorkflowState(workflow_run.state)
        if current_state == command.target_state:
            self._session.rollback()
            return WorkflowTransitionResult(
                workflow_run_id=uuid.UUID(str(workflow_run.id)),
                state=current_state,
                changed=False,
            )
        if current_state != command.expected_state:
            raise WorkflowStateConflict(
                f"workflow run '{workflow_run.id}' is '{current_state}', expected '{command.expected_state}'"
            )
        require_transition(current_state, command.target_state)

        step_key = _step_key_for(command.target_state)
        workflow_step = self._session.scalar(
            select(WorkflowStep)
            .where(
                WorkflowStep.workflow_run_id == workflow_run.id,
                WorkflowStep.step_key == step_key,
            )
            .with_for_update()
        )
        if workflow_step is None:
            workflow_step = WorkflowStep(
                workflow_run_id=workflow_run.id,
                step_key=step_key,
                state=command.target_state.value,
                attempt_count=1,
                output_payload=command.output_payload,
            )
            self._session.add(workflow_step)
        else:
            workflow_step.state = command.target_state.value
            workflow_step.attempt_count += 1
            workflow_step.output_payload = command.output_payload

        workflow_run.state = command.target_state.value
        event_payload: dict[str, object] = {
            "workflow_run_id": str(workflow_run.id),
            "organization_id": str(command.organization_id),
            "from_state": current_state.value,
            "to_state": command.target_state.value,
            "step_key": step_key,
        }
        if command.target_state == WorkflowState.QUEUED:
            project = self._session.get(VideoProject, workflow_run.project_id)
            if project is None:
                raise LookupError(f"project for workflow run '{workflow_run.id}' was not found")
            event_payload["intake"] = {
                "title": project.title,
                "brief": project.brief,
                "format_profile": project.format_profile,
                "timezone": project.timezone,
                "input_payload": workflow_run.input_payload,
                "prompt_manifest": workflow_run.prompt_manifest,
            }
            render_plan = command.output_payload.get("render_plan")
            if isinstance(render_plan, dict):
                event_payload["render_plan"] = render_plan
        if command.target_state == WorkflowState.PUBLISHING:
            event_payload["publisher_connection_id"] = command.output_payload.get("publisher_connection_id")
        self._session.add(
            OutboxEvent(
                aggregate_type="workflow_run",
                aggregate_id=workflow_run.id,
                event_type="visionflow.workflow_run.state_changed.v1",
                payload=event_payload,
                trace_id=command.trace_id,
            )
        )
        self._session.commit()
        return WorkflowTransitionResult(
            workflow_run_id=uuid.UUID(str(workflow_run.id)),
            state=command.target_state,
            changed=True,
        )


def _step_key_for(target_state: WorkflowState) -> str:
    try:
        return _STEP_KEY_BY_TARGET_STATE[target_state]
    except KeyError as exc:
        raise ValueError(f"No V1 step key is defined for target state '{target_state}'") from exc


_STEP_KEY_BY_TARGET_STATE: dict[WorkflowState, str] = {
    WorkflowState.READY: "brief",
    WorkflowState.QUEUED: "queue",
    WorkflowState.PLANNING: "script",
    WorkflowState.SCRIPTED: "script",
    WorkflowState.STORYBOARDED: "storyboard",
    WorkflowState.ASSETS_READY: "assets",
    WorkflowState.RENDERING: "render",
    WorkflowState.QA_PENDING: "quality_assurance",
    WorkflowState.RENDERED: "quality_assurance",
    WorkflowState.APPROVAL_PENDING: "approval",
    WorkflowState.APPROVED: "approval",
    WorkflowState.PUBLISHING: "publish",
    WorkflowState.PUBLISHED: "publish",
    WorkflowState.RETRY_SCHEDULED: "retry",
    WorkflowState.CANCELED: "cancellation",
    WorkflowState.FAILED: "failure",
}
