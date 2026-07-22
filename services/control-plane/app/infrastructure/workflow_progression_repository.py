from __future__ import annotations

import uuid

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.application.advance_workflow import (
    AdvanceWorkflowCommand,
    WorkflowStateConflict,
    WorkflowTransitionResult,
)
from app.domain.workflow import WorkflowState, require_transition
from app.infrastructure.models import MediaAsset, OutboxEvent, PublicationAttempt, PublishApproval, VideoProject, WorkflowRun, WorkflowStep


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
        if command.target_state == WorkflowState.QA_PENDING:
            self._record_rendered_artifact(workflow_run, command)
        if command.target_state == WorkflowState.APPROVED:
            self._record_publish_approval(workflow_run, command)
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
            event_payload["publish_artifact"] = self._approved_artifact_payload(workflow_run)
            self._create_initial_publication_attempt(workflow_run, command)
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

    def _record_rendered_artifact(self, workflow_run: WorkflowRun, command: AdvanceWorkflowCommand) -> None:
        payload = command.output_payload
        object_key = payload.get("object_key")
        content_type = payload.get("content_type")
        byte_size = payload.get("byte_size")
        checksum = payload.get("checksum_sha256")
        fingerprint = payload.get("render_plan_hash")
        if not isinstance(object_key, str) or not object_key.strip():
            raise ValueError("QA_PENDING requires an artifact object_key")
        if not isinstance(content_type, str) or not content_type.startswith("video/"):
            raise ValueError("QA_PENDING requires a video artifact content_type")
        if not isinstance(byte_size, int) or isinstance(byte_size, bool) or byte_size < 1:
            raise ValueError("QA_PENDING requires a positive artifact byte_size")
        if not isinstance(checksum, str) or len(checksum) != 64:
            raise ValueError("QA_PENDING requires a SHA-256 artifact checksum")
        if not isinstance(fingerprint, str) or len(fingerprint) != 64:
            raise ValueError("QA_PENDING requires a render plan fingerprint")
        self._session.add(
            MediaAsset(
                organization_id=command.organization_id,
                workflow_run_id=workflow_run.id,
                object_key=object_key,
                media_kind="final_export",
                content_type=content_type,
                byte_size=byte_size,
                checksum_sha256=checksum,
                metadata_json={"render_plan_hash": fingerprint},
            )
        )

    def _record_publish_approval(self, workflow_run: WorkflowRun, command: AdvanceWorkflowCommand) -> None:
        """Persist the exact final export accepted by the human approval boundary."""
        asset = self._latest_final_export(workflow_run, command.organization_id)
        if asset is None:
            raise ValueError("APPROVED requires a persisted final export")
        reviewer_subject = command.output_payload.get("reviewer_subject")
        if not isinstance(reviewer_subject, str) or not reviewer_subject.strip():
            raise ValueError("APPROVED requires a reviewer_subject")
        note = command.output_payload.get("note")
        if note is not None and not isinstance(note, str):
            raise ValueError("APPROVED note must be a string")
        self._session.add(
            PublishApproval(
                workflow_run_id=workflow_run.id,
                export_asset_id=asset.id,
                decision="approved",
                reviewer_subject=reviewer_subject.strip(),
                note=note,
            )
        )

    def _approved_artifact_payload(self, workflow_run: WorkflowRun) -> dict[str, object]:
        """Resolve publish input from the immutable approval record, never step JSON."""
        approval = self._session.scalar(
            select(PublishApproval)
            .where(PublishApproval.workflow_run_id == workflow_run.id, PublishApproval.decision == "approved")
            .with_for_update()
        )
        if approval is None:
            raise WorkflowStateConflict("PUBLISHING requires an approved final export")
        asset = self._session.get(MediaAsset, approval.export_asset_id)
        if asset is None or asset.workflow_run_id != workflow_run.id:
            raise WorkflowStateConflict("Approved final export is unavailable")
        return {
            "asset_id": str(asset.id),
            "object_key": asset.object_key,
            "content_type": asset.content_type,
            "byte_size": asset.byte_size,
            "checksum_sha256": asset.checksum_sha256,
        }

    def _latest_final_export(self, workflow_run: WorkflowRun, organization_id: uuid.UUID) -> MediaAsset | None:
        return self._session.scalar(
            select(MediaAsset)
            .where(
                MediaAsset.organization_id == organization_id,
                MediaAsset.workflow_run_id == workflow_run.id,
                MediaAsset.media_kind == "final_export",
            )
            .order_by(MediaAsset.created_at.desc())
            .with_for_update()
        )

    def _create_initial_publication_attempt(self, workflow_run: WorkflowRun, command: AdvanceWorkflowCommand) -> None:
        """Create or reuse the publish lease and its outbox event in the state-change transaction."""
        connection_id = command.output_payload.get("publisher_connection_id")
        requested_by = command.output_payload.get("requested_by_subject")
        if not isinstance(connection_id, str) or not isinstance(requested_by, str) or not requested_by.strip():
            raise ValueError("PUBLISHING requires publisher connection and requester")

        # Check if an active attempt already exists for this workflow run
        existing_attempt = self._session.scalar(
            select(PublicationAttempt)
            .where(
                PublicationAttempt.workflow_run_id == workflow_run.id,
                PublicationAttempt.state.in_(["requested", "created", "uploading", "pending"]),
            )
            .order_by(PublicationAttempt.attempt_number.desc())
        )
        if existing_attempt:
            existing_attempt.publisher_connection_id = uuid.UUID(connection_id)
            existing_attempt.requested_by_subject = requested_by.strip()
            self._session.flush()
            return

        max_attempt = self._session.scalar(
            select(func.max(PublicationAttempt.attempt_number))
            .where(PublicationAttempt.workflow_run_id == workflow_run.id)
        )
        next_attempt_number = (max_attempt or 0) + 1

        attempt = PublicationAttempt(
            workflow_run_id=workflow_run.id,
            publisher_connection_id=uuid.UUID(connection_id),
            attempt_number=next_attempt_number,
            state="pending",
            requested_by_subject=requested_by.strip(),
        )
        self._session.add(attempt)
        self._session.flush()
        self._session.add(
            OutboxEvent(
                aggregate_type="publication_attempt",
                aggregate_id=attempt.id,
                event_type="visionflow.publication_attempt.requested.v1",
                payload={
                    "publication_attempt_id": str(attempt.id),
                    "workflow_run_id": str(workflow_run.id),
                    "organization_id": str(command.organization_id),
                    "publisher_connection_id": connection_id,
                },
                trace_id=command.trace_id,
            )
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
