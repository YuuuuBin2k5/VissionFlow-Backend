from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.application.create_short_form import (
    CreateShortFormCommand,
    IdempotencyKeyConflict as ShortFormIdempotencyKeyConflict,
    WorkflowRunSummary,
)
from app.application.record_narration_generated import (
    RecordNarrationGeneratedCommand,
    NarrationResultSummary,
    WorkflowStateConflict,
    IdempotencyKeyConflict,
)
from app.domain.workflow import WorkflowState, require_transition
from app.infrastructure.models import (
    OutboxEvent,
    VideoProject,
    WorkflowRun,
    CreativeDocument,
    CreativeDocumentVersion,
    CreativeScene,
    WorkflowStep,
)


class SqlAlchemyShortFormWorkflowRepository:
    """PostgreSQL implementation with an idempotency key as the write boundary."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create_or_get_initial_run(self, command: CreateShortFormCommand) -> WorkflowRunSummary:
        existing = self._find_by_idempotency_key(command.idempotency_key, command.organization_id)
        if existing:
            return _summary(existing, created=False)

        project = VideoProject(
            organization_id=command.organization_id,
            title=command.title.strip(),
            brief=command.brief.strip(),
            format_profile=command.format_profile,
            timezone=command.timezone,
        )
        try:
            self._session.add(project)
            self._session.flush()
            workflow_run = WorkflowRun(
                project_id=project.id,
                state=WorkflowState.DRAFT.value,
                idempotency_key=command.idempotency_key,
                prompt_manifest=command.prompt_manifest,
                input_payload=command.input_payload,
            )
            self._session.add(workflow_run)
            self._session.flush()
            self._session.add(
                OutboxEvent(
                    aggregate_type="workflow_run",
                    aggregate_id=workflow_run.id,
                    event_type="visionflow.workflow_run.opened.v1",
                    payload={
                        "project_id": str(project.id),
                        "workflow_run_id": str(workflow_run.id),
                        "state": WorkflowState.DRAFT.value,
                    },
                    trace_id=command.trace_id,
                )
            )
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            existing = self._find_by_idempotency_key(command.idempotency_key, command.organization_id)
            if existing:
                return _summary(existing, created=False)
            if self._find_any_by_idempotency_key(command.idempotency_key):
                raise ShortFormIdempotencyKeyConflict(
                    "idempotency key is already associated with a different organization"
                ) from exc
            raise

        self._session.refresh(workflow_run)
        return _summary(workflow_run, created=True)

    def _find_by_idempotency_key(
        self, idempotency_key: str, organization_id: uuid.UUID
    ) -> WorkflowRun | None:
        return self._session.scalar(
            select(WorkflowRun)
            .join(VideoProject, VideoProject.id == WorkflowRun.project_id)
            .where(
                WorkflowRun.idempotency_key == idempotency_key,
                VideoProject.organization_id == organization_id,
            )
        )

    def _find_any_by_idempotency_key(self, idempotency_key: str) -> WorkflowRun | None:
        return self._session.scalar(
            select(WorkflowRun).where(WorkflowRun.idempotency_key == idempotency_key)
        )


def _summary(workflow_run: WorkflowRun, *, created: bool) -> WorkflowRunSummary:
    return WorkflowRunSummary(
        project_id=uuid.UUID(str(workflow_run.project_id)),
        workflow_run_id=uuid.UUID(str(workflow_run.id)),
        state=WorkflowState(workflow_run.state),
        created=created,
    )


class SqlAlchemyNarrationResultRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def record_narration_result(
        self, command: RecordNarrationGeneratedCommand
    ) -> NarrationResultSummary:
        try:
            return self._record_narration_result(command)
        except Exception:
            self._session.rollback()
            raise

    def _record_narration_result(
        self, command: RecordNarrationGeneratedCommand
    ) -> NarrationResultSummary:
        workflow_run = self._session.scalar(
            select(WorkflowRun)
            .join(VideoProject, VideoProject.id == WorkflowRun.project_id)
            .where(VideoProject.organization_id == command.organization_id)
            .where(WorkflowRun.id == command.workflow_run_id)
            .with_for_update()
        )
        if workflow_run is None:
            raise LookupError(f"workflow run '{command.workflow_run_id}' was not found")

        workflow_step = self._session.scalar(
            select(WorkflowStep)
            .where(
                WorkflowStep.workflow_run_id == workflow_run.id,
                WorkflowStep.step_key == "script",
            )
            .with_for_update()
        )

        if workflow_step and workflow_step.output_payload and workflow_step.output_payload.get("idempotency_key") == command.idempotency_key:
            self._session.rollback()
            return NarrationResultSummary(
                workflow_run_id=workflow_run.id,
                state=WorkflowState(workflow_run.state),
                changed=False,
                version_id=uuid.UUID(workflow_step.output_payload["version_id"]),
                version=workflow_step.output_payload["version"],
            )

        # Global uniqueness check for the step idempotency key
        # Check if the key exists inside any step's output_payload JSONB
        duplicate_step = self._session.scalar(
            select(WorkflowStep).where(
                WorkflowStep.output_payload["idempotency_key"].as_string() == command.idempotency_key
            )
        )
        if duplicate_step and duplicate_step.workflow_run_id != command.workflow_run_id:
            raise IdempotencyKeyConflict("idempotency key is already associated with a different workflow run")

        current_state = WorkflowState(workflow_run.state)
        if current_state != WorkflowState.PLANNING:
            raise WorkflowStateConflict(
                f"workflow run '{workflow_run.id}' is '{current_state}', expected 'PLANNING'"
            )

        require_transition(current_state, WorkflowState.SCRIPTED)
        workflow_run.state = WorkflowState.SCRIPTED.value

        creative_document = self._session.scalar(
            select(CreativeDocument)
            .where(CreativeDocument.workflow_run_id == workflow_run.id)
            .with_for_update()
        )
        if creative_document is None:
            creative_document = CreativeDocument(
                workflow_run_id=workflow_run.id,
                revision=0,
            )
            self._session.add(creative_document)
            self._session.flush()

        new_version_number = creative_document.revision + 1
        version = CreativeDocumentVersion(
            creative_document_id=creative_document.id,
            version=new_version_number,
            state="locked",
            script=command.script,
            source="worker",
            created_by_subject=command.actor_subject,
        )
        self._session.add(version)
        self._session.flush()

        for position, scene in enumerate(command.scenes, start=1):
            self._session.add(
                CreativeScene(
                    creative_document_version_id=version.id,
                    position=position,
                    narration=scene.narration,
                    visual_prompt=scene.visual_prompt,
                    duration_seconds=scene.duration_seconds,
                    transition=scene.transition,
                    caption=scene.caption,
                )
            )

        creative_document.revision = new_version_number
        creative_document.active_version_id = version.id

        step_payload = {
            "idempotency_key": command.idempotency_key,
            "version_id": str(version.id),
            "version": new_version_number,
            "source_metadata": command.source_metadata,
            "legacy_job_id": command.legacy_job_id,
        }
        if workflow_step is None:
            workflow_step = WorkflowStep(
                workflow_run_id=workflow_run.id,
                step_key="script",
                state=WorkflowState.SCRIPTED.value,
                attempt_count=1,
                output_payload=step_payload,
            )
            self._session.add(workflow_step)
        else:
            workflow_step.state = WorkflowState.SCRIPTED.value
            workflow_step.attempt_count += 1
            workflow_step.output_payload = step_payload

        self._session.add(
            OutboxEvent(
                aggregate_type="workflow_run",
                aggregate_id=workflow_run.id,
                event_type="visionflow.workflow_run.state_changed.v1",
                payload={
                    "workflow_run_id": str(workflow_run.id),
                    "from_state": current_state.value,
                    "to_state": WorkflowState.SCRIPTED.value,
                    "step_key": "script",
                    "creative_version_id": str(version.id),
                    "creative_version": new_version_number,
                },
                trace_id=command.trace_id,
            )
        )

        self._session.commit()
        return NarrationResultSummary(
            workflow_run_id=workflow_run.id,
            state=WorkflowState.SCRIPTED,
            changed=True,
            version_id=version.id,
            version=new_version_number,
        )
