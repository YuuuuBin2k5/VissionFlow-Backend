from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.save_creative_draft import SaveCreativeDraftCommand
from app.domain.workflow import WorkflowState
from app.infrastructure.models import VideoProject, WorkflowRun


class SqlAlchemyCreativeDraftRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def save_creative_draft(self, command: SaveCreativeDraftCommand) -> None:
        try:
            run = self._session.scalar(
                select(WorkflowRun)
                .join(VideoProject, VideoProject.id == WorkflowRun.project_id)
                .where(VideoProject.organization_id == command.organization_id, WorkflowRun.id == command.workflow_run_id)
                .with_for_update()
            )
            if run is None:
                raise LookupError("workflow run not found")
            if WorkflowState(run.state) not in {WorkflowState.DRAFT, WorkflowState.READY}:
                raise ValueError("creative draft can only be edited before queueing")
            payload = dict(run.input_payload or {})
            payload["creative_draft"] = command.creative_draft
            run.input_payload = payload
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
