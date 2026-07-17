from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import hashlib
import json
from dataclasses import asdict

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
    StaleNarrationAttempt,
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
    CommandReceipt,
    WorkflowAuditEvent,
    PromptTemplate,
    ProviderCredential,
    PublisherConnection,
)



class SqlAlchemyShortFormWorkflowRepository:
    """PostgreSQL implementation with an idempotency key as the write boundary."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def _create_or_get_initial_run_in_transaction(self, command: CreateShortFormCommand) -> tuple[WorkflowRun, bool]:
        existing = self._find_by_idempotency_key(command.idempotency_key, command.organization_id)
        if existing:
            return existing, False

        project = VideoProject(
            organization_id=command.organization_id,
            title=command.title.strip(),
            brief=command.brief.strip(),
            format_profile=command.format_profile,
            timezone=command.timezone,
        )
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
        self._session.flush()
        return workflow_run, True

    def create_or_get_initial_run(self, command: CreateShortFormCommand) -> WorkflowRunSummary:
        try:
            workflow_run, created = self._create_or_get_initial_run_in_transaction(command)
            if created:
                self._session.commit()
                self._session.refresh(workflow_run)
            return _summary(workflow_run, created=created)
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
        except IntegrityError as exc:
            self._session.rollback()
            raise IdempotencyKeyConflict(
                "idempotency key is already associated with a different operation"
            ) from exc
        except Exception:
            self._session.rollback()
            raise

    def _record_narration_result(
        self, command: RecordNarrationGeneratedCommand
    ) -> NarrationResultSummary:
        # 1. Compute fingerprint — includes narration_attempt_id so stale retry fingerprints differ
        serialized_payload = {
            "organization_id": str(command.organization_id),
            "workflow_run_id": str(command.workflow_run_id),
            "narration_attempt_id": command.narration_attempt_id,
            "script": command.script,
            "scenes": [
                {
                    "narration": scene.narration,
                    "visual_prompt": scene.visual_prompt,
                    "duration_seconds": scene.duration_seconds,
                    "transition": scene.transition,
                    "caption": scene.caption,
                }
                for scene in command.scenes
            ],
            "source_metadata": asdict(command.source_metadata),
            "legacy_job_id": command.legacy_job_id,
        }
        fingerprint = hashlib.sha256(json.dumps(serialized_payload, sort_keys=True).encode("utf-8")).hexdigest()

        # 2. Lock workflow run first to serialize concurrent requests on the same run
        workflow_run = self._session.scalar(
            select(WorkflowRun)
            .join(VideoProject, VideoProject.id == WorkflowRun.project_id)
            .where(VideoProject.organization_id == command.organization_id)
            .where(WorkflowRun.id == command.workflow_run_id)
            .with_for_update()
        )
        if workflow_run is None:
            raise LookupError(f"workflow run '{command.workflow_run_id}' was not found")

        # 3. Check persistent idempotency store (command_receipts)
        receipt = self._session.scalar(
            select(CommandReceipt)
            .where(CommandReceipt.idempotency_key == command.idempotency_key)
            .with_for_update()
        )
        if receipt:
            if (
                receipt.organization_id == command.organization_id
                and receipt.workflow_run_id == command.workflow_run_id
                and receipt.request_fingerprint == fingerprint
            ):
                self._session.rollback()
                payload = receipt.result_payload
                return NarrationResultSummary(
                    workflow_run_id=uuid.UUID(payload["workflow_run_id"]),
                    state=WorkflowState(payload["state"]),
                    changed=False,
                    version_id=uuid.UUID(payload["version_id"]),
                    version=payload["version"],
                )
            else:
                raise IdempotencyKeyConflict(
                    "idempotency key is already associated with a different operation"
                )

        current_state = WorkflowState(workflow_run.state)
        if current_state != WorkflowState.PLANNING:
            raise WorkflowStateConflict(
                f"workflow run '{workflow_run.id}' is '{current_state}', expected 'PLANNING'"
            )

        # 3b. Validate narration_attempt_id against authoritative WorkflowStep.attempt_count
        script_step = self._session.scalar(
            select(WorkflowStep)
            .where(
                WorkflowStep.workflow_run_id == workflow_run.id,
                WorkflowStep.step_key == "script",
            )
            .with_for_update()
        )
        if script_step is None or script_step.attempt_count == 0:
            from app.application.record_narration_generated import ActiveNarrationAttemptMissing
            raise ActiveNarrationAttemptMissing(
                f"workflow run '{workflow_run.id}' has no active narration attempt"
            )
        active_attempt_id = f"narration-{workflow_run.id}-attempt-{script_step.attempt_count}"
        if command.narration_attempt_id != active_attempt_id:
            raise StaleNarrationAttempt(
                f"narration_attempt_id '{command.narration_attempt_id}' is stale; "
                f"active attempt is '{active_attempt_id}'"
            )

        # 4. Perform workflow transition
        require_transition(current_state, WorkflowState.SCRIPTED)
        workflow_run.state = WorkflowState.SCRIPTED.value

        # 5. Look up or create CreativeDocument
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

        # 6. Upsert WorkflowStep
        workflow_step = self._session.scalar(
            select(WorkflowStep)
            .where(
                WorkflowStep.workflow_run_id == workflow_run.id,
                WorkflowStep.step_key == "script",
            )
            .with_for_update()
        )
        step_payload = {
            "idempotency_key": command.idempotency_key,
            "version_id": str(version.id),
            "version": new_version_number,
            "source_metadata": asdict(command.source_metadata),
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

        # 7. Write to WorkflowAuditEvent
        self._session.add(
            WorkflowAuditEvent(
                organization_id=command.organization_id,
                workflow_run_id=command.workflow_run_id,
                action="complete_narration",
                actor_subject=command.actor_subject,
                target_version_id=version.id,
                trace_id=command.trace_id,
            )
        )

        # 8. Write to CommandReceipt
        result_payload = {
            "workflow_run_id": str(workflow_run.id),
            "state": WorkflowState.SCRIPTED.value,
            "version_id": str(version.id),
            "version": new_version_number,
        }
        self._session.add(
            CommandReceipt(
                organization_id=command.organization_id,
                operation_type="complete_narration",
                idempotency_key=command.idempotency_key,
                workflow_run_id=command.workflow_run_id,
                request_fingerprint=fingerprint,
                result_payload=result_payload,
            )
        )

        # 9. Ghi OutboxEvent
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


class SqlAlchemyShortFormReadinessRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def check_gemini_active(self, organization_id: uuid.UUID) -> bool:
        return self._session.scalar(
            select(ProviderCredential.id)
            .where(
                ProviderCredential.organization_id == organization_id,
                ProviderCredential.provider == "gemini",
                ProviderCredential.status == "active"
            )
        ) is not None

    def check_stock_media_active(self, organization_id: uuid.UUID) -> list[str]:
        records = self._session.scalars(
            select(ProviderCredential.provider)
            .where(
                ProviderCredential.organization_id == organization_id,
                ProviderCredential.provider.in_(["pexels", "pixabay", "coverr"]),
                ProviderCredential.status == "active"
            )
        ).all()
        return list(records)

    def check_youtube_connection_active(self, organization_id: uuid.UUID) -> bool:
        return self._session.scalar(
            select(PublisherConnection.id)
            .where(
                PublisherConnection.organization_id == organization_id,
                PublisherConnection.provider == "youtube",
                PublisherConnection.status == "active"
            )
        ) is not None

    def check_prompts_baseline_active(self, organization_id: uuid.UUID, required_keys: list[str]) -> dict[str, bool]:
        records = self._session.execute(
            select(PromptTemplate.prompt_key, PromptTemplate.production_version)
            .where(
                PromptTemplate.organization_id == organization_id,
                PromptTemplate.prompt_key.in_(required_keys)
            )
        ).all()
        
        status_map = {key: False for key in required_keys}
        for prompt_key, production_version in records:
            if production_version is not None:
                status_map[prompt_key] = True
        return status_map

