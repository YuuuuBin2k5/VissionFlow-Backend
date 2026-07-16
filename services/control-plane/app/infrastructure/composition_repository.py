from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.composition import validate_composition_for_v1
from app.domain.workflow import WorkflowState
from app.infrastructure.models import (
    CompositionClip, CompositionDocument, CompositionEffectInstance, CompositionKeyframe,
    CompositionTrack, CompositionVersion, VideoProject, WorkflowRun,
)


class CompositionConflict(ValueError):
    pass


class SqlAlchemyCompositionRepository:
    """Immutable timeline revisions; the active locked version is render input."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def read(self, organization_id: uuid.UUID, workflow_run_id: uuid.UUID) -> dict[str, Any] | None:
        document = self._document(organization_id, workflow_run_id, lock=False, editable=False)
        return self._serialize(document) if document else None

    def save(self, *, organization_id: uuid.UUID, workflow_run_id: uuid.UUID, expected_revision: int, aspect_ratio: str, canvas_config: dict[str, Any], tracks: list[dict[str, Any]], actor_subject: str) -> dict[str, Any]:
        # Keep the persistence boundary safe for non-HTTP callers as well.
        validate_composition_for_v1(aspect_ratio=aspect_ratio, tracks=tracks)
        try:
            document = self._document(organization_id, workflow_run_id, lock=True, editable=True)
            if document is None:
                document = CompositionDocument(workflow_run_id=workflow_run_id, revision=0)
                self._session.add(document); self._session.flush()
            if document.revision != expected_revision:
                raise CompositionConflict("Composition changed by another editor. Refresh and merge before saving.")
            version = CompositionVersion(composition_document_id=document.id, revision=document.revision + 1, state="draft", aspect_ratio=aspect_ratio, canvas_config=canvas_config, created_by_subject=actor_subject)
            self._session.add(version); self._session.flush()
            for track_position, track_data in enumerate(tracks, start=1):
                track = CompositionTrack(composition_version_id=version.id, position=track_position, track_type=str(track_data["track_type"]), name=str(track_data["name"]), muted=bool(track_data.get("muted", False)), locked=bool(track_data.get("locked", False)))
                self._session.add(track); self._session.flush()
                for clip_position, clip_data in enumerate(track_data.get("clips", []), start=1):
                    clip = CompositionClip(composition_track_id=track.id, position=clip_position, source_type=str(clip_data["source_type"]), source_ref=str(clip_data["source_ref"]), timeline_start_ms=int(clip_data["timeline_start_ms"]), duration_ms=int(clip_data["duration_ms"]), trim_in_ms=int(clip_data.get("trim_in_ms", 0)), transform=dict(clip_data.get("transform", {})))
                    self._session.add(clip); self._session.flush()
                    for effect_position, effect_data in enumerate(clip_data.get("effects", []), start=1):
                        self._session.add(CompositionEffectInstance(composition_clip_id=clip.id, position=effect_position, effect_key=str(effect_data["effect_key"]), config=dict(effect_data.get("config", {}))))
                    for keyframe_data in clip_data.get("keyframes", []):
                        self._session.add(CompositionKeyframe(composition_clip_id=clip.id, property_key=str(keyframe_data["property_key"]), time_ms=int(keyframe_data["time_ms"]), value=dict(keyframe_data.get("value", {})), easing=str(keyframe_data.get("easing", "linear"))))
            document.revision = version.revision
            self._session.commit()
            return self._serialize(document, version)
        except Exception:
            self._session.rollback(); raise

    def lock(self, *, organization_id: uuid.UUID, workflow_run_id: uuid.UUID, expected_revision: int) -> dict[str, Any]:
        try:
            document = self._document(organization_id, workflow_run_id, lock=True, editable=True)
            if document is None or document.revision == 0: raise LookupError("Composition not found")
            if document.revision != expected_revision: raise CompositionConflict("Composition changed by another editor. Refresh before locking.")
            version = self._latest(document.id)
            if version is None: raise LookupError("Composition version not found")
            version.state = "locked"; document.active_version_id = version.id
            self._session.commit()
            return self._serialize(document, version)
        except Exception:
            self._session.rollback(); raise

    def _document(self, organization_id: uuid.UUID, workflow_run_id: uuid.UUID, *, lock: bool, editable: bool) -> CompositionDocument | None:
        query = select(WorkflowRun).join(VideoProject, VideoProject.id == WorkflowRun.project_id).where(VideoProject.organization_id == organization_id, WorkflowRun.id == workflow_run_id)
        if lock: query = query.with_for_update()
        run = self._session.scalar(query)
        if run is None: raise LookupError("Workflow run not found")
        if editable and WorkflowState(run.state) not in {WorkflowState.DRAFT, WorkflowState.READY}: raise ValueError("Composition can only be edited before queueing")
        query = select(CompositionDocument).where(CompositionDocument.workflow_run_id == workflow_run_id)
        if lock: query = query.with_for_update()
        return self._session.scalar(query)

    def _latest(self, document_id: uuid.UUID) -> CompositionVersion | None:
        return self._session.scalar(select(CompositionVersion).where(CompositionVersion.composition_document_id == document_id).order_by(CompositionVersion.revision.desc()))

    def _serialize(self, document: CompositionDocument, version: CompositionVersion | None = None) -> dict[str, Any]:
        current = version or self._latest(document.id)
        if current is None: raise LookupError("Composition version not found")
        tracks = self._session.scalars(select(CompositionTrack).where(CompositionTrack.composition_version_id == current.id).order_by(CompositionTrack.position)).all()
        encoded_tracks: list[dict[str, Any]] = []
        for track in tracks:
            clips = self._session.scalars(select(CompositionClip).where(CompositionClip.composition_track_id == track.id).order_by(CompositionClip.position)).all()
            encoded_clips = []
            for clip in clips:
                effects = self._session.scalars(select(CompositionEffectInstance).where(CompositionEffectInstance.composition_clip_id == clip.id).order_by(CompositionEffectInstance.position)).all()
                keyframes = self._session.scalars(select(CompositionKeyframe).where(CompositionKeyframe.composition_clip_id == clip.id).order_by(CompositionKeyframe.time_ms)).all()
                encoded_clips.append({"id": str(clip.id), "source_type": clip.source_type, "source_ref": clip.source_ref, "timeline_start_ms": clip.timeline_start_ms, "duration_ms": clip.duration_ms, "trim_in_ms": clip.trim_in_ms, "transform": clip.transform, "effects": [{"effect_key": effect.effect_key, "config": effect.config} for effect in effects], "keyframes": [{"property_key": frame.property_key, "time_ms": frame.time_ms, "value": frame.value, "easing": frame.easing} for frame in keyframes]})
            encoded_tracks.append({"id": str(track.id), "track_type": track.track_type, "name": track.name, "muted": track.muted, "locked": track.locked, "clips": encoded_clips})
        return {"document_id": str(document.id), "workflow_run_id": str(document.workflow_run_id), "revision": document.revision, "active_version_id": str(document.active_version_id) if document.active_version_id else None, "version_id": str(current.id), "state": current.state, "aspect_ratio": current.aspect_ratio, "canvas_config": current.canvas_config, "tracks": encoded_tracks}
