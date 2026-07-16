from __future__ import annotations

import hashlib
import json
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.application.register_legacy_job_mapping import (
    LegacyJobMappingConflict,
    LegacyJobMappingResult,
    RegisterLegacyJobMappingCommand,
)
from app.infrastructure.models import (
    CommandReceipt,
    OutboxEvent,
    VideoProject,
    WorkflowAuditEvent,
    WorkflowRun,
)


class SqlAlchemyLegacyMappingRepository:
    """Atomically registers a legacy MySQL job ID onto an existing WorkflowRun.

    Invariants enforced here (application layer validated upstream):
    - WorkflowRun must exist and belong to organization_id.
    - legacy_job_id globally unique: DB unique constraint + conflict handling.
    - Idempotency: same idempotency_key with identical mapping → cached success.
    - Duplicate idempotency_key with different mapping → IdempotencyKeyConflict.
    - Duplicate legacy_job_id mapped to a different workflow_run → LegacyJobMappingConflict.
    - Worker identity enforcement is done at the transport (router) layer; repository
      trusts actor_subject as already validated.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def register(
        self, command: RegisterLegacyJobMappingCommand
    ) -> LegacyJobMappingResult:
        try:
            return self._register(command)
        except IntegrityError as exc:
            self._session.rollback()
            # Unique constraint on legacy_job_id fired for a different run.
            raise LegacyJobMappingConflict(
                f"legacy_job_id '{command.legacy_job_id}' is already mapped to a different workflow run"
            ) from exc
        except Exception:
            self._session.rollback()
            raise

    def _register(
        self, command: RegisterLegacyJobMappingCommand
    ) -> LegacyJobMappingResult:
        # 1. Compute fingerprint for idempotency receipt
        fingerprint_payload = {
            "organization_id": str(command.organization_id),
            "workflow_run_id": str(command.workflow_run_id),
            "legacy_source": command.legacy_source,
            "legacy_job_id": command.legacy_job_id,
        }
        fingerprint = hashlib.sha256(
            json.dumps(fingerprint_payload, sort_keys=True).encode("utf-8")
        ).hexdigest()

        # 2. Check idempotency receipt first (avoids lock contention on happy replay)
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
                return LegacyJobMappingResult(
                    workflow_run_id=uuid.UUID(payload["workflow_run_id"]),
                    legacy_job_id=payload["legacy_job_id"],
                    registered=False,
                )
            else:
                from app.application.create_short_form import IdempotencyKeyConflict
                raise IdempotencyKeyConflict(
                    "idempotency key is already associated with a different mapping operation"
                )

        # 3. Lock the WorkflowRun to verify ownership and check existing mapping
        workflow_run = self._session.scalar(
            select(WorkflowRun)
            .join(VideoProject, VideoProject.id == WorkflowRun.project_id)
            .where(VideoProject.organization_id == command.organization_id)
            .where(WorkflowRun.id == command.workflow_run_id)
            .with_for_update()
        )
        if workflow_run is None:
            raise LookupError(
                f"workflow run '{command.workflow_run_id}' was not found for organization '{command.organization_id}'"
            )

        # 4. Detect if legacy_job_id already mapped to this exact run (safe idempotent)
        if workflow_run.legacy_job_id is not None:
            if workflow_run.legacy_job_id == command.legacy_job_id:
                # Already mapped to the same job — treat as idempotent, but
                # idempotency_key didn't match above so this is a key mismatch
                # for the same semantic operation. Fail closed.
                from app.application.create_short_form import IdempotencyKeyConflict
                raise IdempotencyKeyConflict(
                    "workflow run already has a legacy_job_id mapping; use the original idempotency_key to replay"
                )
            else:
                raise LegacyJobMappingConflict(
                    f"workflow run '{command.workflow_run_id}' already has legacy_job_id "
                    f"'{workflow_run.legacy_job_id}'; cannot overwrite with '{command.legacy_job_id}'"
                )

        # 5. Write the mapping
        workflow_run.legacy_job_id = command.legacy_job_id

        # 6. Outbox event
        self._session.add(
            OutboxEvent(
                aggregate_type="workflow_run",
                aggregate_id=workflow_run.id,
                event_type="visionflow.workflow_run.legacy_job_mapped.v1",
                payload={
                    "workflow_run_id": str(workflow_run.id),
                    "legacy_source": command.legacy_source,
                    "legacy_job_id": command.legacy_job_id,
                    "actor_subject": command.actor_subject,
                },
                trace_id=command.trace_id,
            )
        )

        # 7. Audit event
        self._session.add(
            WorkflowAuditEvent(
                organization_id=command.organization_id,
                workflow_run_id=command.workflow_run_id,
                action="register_legacy_job_mapping",
                actor_subject=command.actor_subject,
                target_version_id=None,
                trace_id=command.trace_id,
            )
        )

        # 8. Idempotency receipt
        result_payload = {
            "workflow_run_id": str(command.workflow_run_id),
            "legacy_job_id": command.legacy_job_id,
        }
        self._session.add(
            CommandReceipt(
                organization_id=command.organization_id,
                operation_type="register_legacy_job_mapping",
                idempotency_key=command.idempotency_key,
                workflow_run_id=command.workflow_run_id,
                request_fingerprint=fingerprint,
                result_payload=result_payload,
            )
        )

        self._session.commit()
        return LegacyJobMappingResult(
            workflow_run_id=command.workflow_run_id,
            legacy_job_id=command.legacy_job_id,
            registered=True,
        )
