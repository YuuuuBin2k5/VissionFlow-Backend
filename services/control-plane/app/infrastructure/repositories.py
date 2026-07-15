from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.application.create_short_form import (
    CreateShortFormCommand,
    IdempotencyKeyConflict,
    WorkflowRunSummary,
)
from app.domain.workflow import WorkflowState
from app.infrastructure.models import OutboxEvent, VideoProject, WorkflowRun


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
                raise IdempotencyKeyConflict(
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
