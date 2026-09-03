from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.workflow import WorkflowState
from app.infrastructure.models import (
    CreativeDocument,
    CreativeDocumentVersion,
    CreativeScene,
    VideoProject,
    WorkflowRun,
)


def _normalize_transition(val: object) -> str:
    if not val:
        return "cut"
    if isinstance(val, dict):
        return str(val.get("type") or val.get("id") or val.get("name") or "cut")
    s = str(val).strip()
    if s.startswith("{") and ("'type'" in s or '"type"' in s or "'id'" in s or '"id"' in s):
        try:
            import json, ast
            d = ast.literal_eval(s) if "'" in s else json.loads(s)
            if isinstance(d, dict):
                return str(d.get("type") or d.get("id") or d.get("name") or s)
        except Exception:
            pass
    return s


@dataclass(frozen=True)
class CreativeDocumentSnapshot:
    document_id: uuid.UUID
    workflow_run_id: uuid.UUID
    revision: int
    active_version_id: uuid.UUID | None
    version_id: uuid.UUID
    version: int
    state: str
    script: str
    scenes: list[CreativeScene]


class CreativeDocumentConflict(ValueError):
    """Raised when an operator saves an obsolete editor revision."""


class SqlAlchemyCreativeDocumentRepository:
    """Versioned creative workspace persistence.

    Every save writes an immutable snapshot rather than mutating a scene in
    place.  This gives review and render a reproducible input while keeping
    the editor optimistic and safe for concurrent operators.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def read(self, organization_id: uuid.UUID, workflow_run_id: uuid.UUID) -> CreativeDocumentSnapshot | None:
        # Reads are required by workers after QUEUED.  Editability is enforced
        # only by save/lock, never by the read model used to render a locked
        # version.
        document = self._document_for_workflow(organization_id, workflow_run_id, lock=False, require_editable=False)
        if document is None:
            return None
        return self._snapshot(document)

    def _save_in_transaction(
        self,
        *,
        organization_id: uuid.UUID,
        workflow_run_id: uuid.UUID,
        expected_revision: int,
        script: str,
        scenes: list[dict[str, object]],
        actor_subject: str,
    ) -> tuple[CreativeDocument, CreativeDocumentVersion]:
        document = self._document_for_workflow(organization_id, workflow_run_id, lock=True, require_editable=True)
        if document is None:
            document = CreativeDocument(workflow_run_id=workflow_run_id, revision=0)
            self._session.add(document)
            self._session.flush()
        if document.revision != expected_revision:
            raise CreativeDocumentConflict("Creative document was changed by another editor. Refresh and merge your changes.")

        version = CreativeDocumentVersion(
            creative_document_id=document.id,
            version=document.revision + 1,
            state="draft",
            script=script,
            source="operator",
            created_by_subject=actor_subject,
        )
        self._session.add(version)
        self._session.flush()
        for position, scene in enumerate(scenes, start=1):
            self._session.add(CreativeScene(
                creative_document_version_id=version.id,
                position=position,
                narration=str(scene["narration"]),
                visual_prompt=str(scene["visual_prompt"]),
                duration_seconds=int(scene["duration_seconds"]),
                transition=_normalize_transition(scene.get("transition")),
                caption=str(scene["caption"]) if scene.get("caption") else None,
            ))
        document.revision = version.version
        self._session.flush()
        return document, version

    def save(
        self,
        *,
        organization_id: uuid.UUID,
        workflow_run_id: uuid.UUID,
        expected_revision: int,
        script: str,
        scenes: list[dict[str, object]],
        actor_subject: str,
    ) -> CreativeDocumentSnapshot:
        try:
            document, version = self._save_in_transaction(
                organization_id=organization_id,
                workflow_run_id=workflow_run_id,
                expected_revision=expected_revision,
                script=script,
                scenes=scenes,
                actor_subject=actor_subject,
            )
            self._session.commit()
            return self._snapshot(document, version)
        except Exception:
            self._session.rollback()
            raise

    def lock(self, *, organization_id: uuid.UUID, workflow_run_id: uuid.UUID, expected_revision: int) -> CreativeDocumentSnapshot:
        try:
            document = self._document_for_workflow(organization_id, workflow_run_id, lock=True, require_editable=True)
            if document is None or document.revision == 0:
                raise LookupError("Creative document not found")
            if document.revision != expected_revision:
                raise CreativeDocumentConflict("Creative document was changed by another editor. Refresh before locking.")
            version = self._latest_version(document.id)
            if version is None:
                raise LookupError("Creative document version not found")
            version.state = "locked"
            document.active_version_id = version.id
            self._session.commit()
            return self._snapshot(document, version)
        except Exception:
            self._session.rollback()
            raise

    def _document_for_workflow(
        self, organization_id: uuid.UUID, workflow_run_id: uuid.UUID, *, lock: bool, require_editable: bool
    ) -> CreativeDocument | None:
        run_query = select(WorkflowRun).join(VideoProject, VideoProject.id == WorkflowRun.project_id).where(
            VideoProject.organization_id == organization_id, WorkflowRun.id == workflow_run_id
        )
        if lock:
            run_query = run_query.with_for_update()
        run = self._session.scalar(run_query)
        if run is None:
            raise LookupError("Workflow run not found")
        if require_editable and WorkflowState(run.state) not in {WorkflowState.DRAFT, WorkflowState.READY}:
            raise ValueError("Creative document can only be edited before queueing")
        document_query = select(CreativeDocument).where(CreativeDocument.workflow_run_id == workflow_run_id)
        if lock:
            document_query = document_query.with_for_update()
        return self._session.scalar(document_query)

    def _latest_version(self, document_id: uuid.UUID) -> CreativeDocumentVersion | None:
        return self._session.scalar(
            select(CreativeDocumentVersion)
            .where(CreativeDocumentVersion.creative_document_id == document_id)
            .order_by(CreativeDocumentVersion.version.desc())
        )

    def _snapshot(self, document: CreativeDocument, version: CreativeDocumentVersion | None = None) -> CreativeDocumentSnapshot:
        current = version or self._latest_version(document.id)
        if current is None:
            raise LookupError("Creative document version not found")
        scenes = self._session.scalars(
            select(CreativeScene)
            .where(CreativeScene.creative_document_version_id == current.id)
            .order_by(CreativeScene.position)
        ).all()
        return CreativeDocumentSnapshot(
            document_id=document.id,
            workflow_run_id=document.workflow_run_id,
            revision=document.revision,
            active_version_id=document.active_version_id,
            version_id=current.id,
            version=current.version,
            state=current.state,
            script=current.script,
            scenes=list(scenes),
        )
