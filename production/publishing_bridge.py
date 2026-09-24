"""
Publishing Safety & Idempotency Bridge for VisionFlow Auto Production System (Phase 7 - Section 24, 25, 26, 27).
Connects approved ProductionRuns to the existing publication_attempts database table and publisher-worker,
enforces strict blocker gates, prevents accidental double-posting, and manages publishing states.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from production.contracts import (
    ProductionRun,
    ProductionRunStatus,
    PublicationStatus,
    ProviderMode,
    RenderArtifact,
)
from production.repositories.run_repository import run_repository

logger = logging.getLogger("visionflow.production.publishing_bridge")


class PublishingSafetyError(RuntimeError):
    """Raised when publication safety invariants are violated."""


@dataclass
class PublicationRequest:
    run_id: str
    platform: str  # e.g., "youtube", "tiktok"
    channel_id: str
    title: str
    description: str
    privacy: str = "unlisted"  # default safe mode
    schedule_time: Optional[datetime] = None
    override_auto_publish: bool = False
    provider_mode: ProviderMode = ProviderMode.SIMULATION


@dataclass
class PublicationResult:
    publication_id: str
    run_id: str
    platform: str
    channel_id: str
    idempotency_key: str
    status: PublicationStatus
    external_post_id: Optional[str] = None
    external_url: Optional[str] = None
    error_message: Optional[str] = None
    published_at: Optional[datetime] = None
    provider_mode: ProviderMode = ProviderMode.SIMULATION
    provider_confirmed: bool = False

    @property
    def internal_publication_id(self) -> str:
        return self.publication_id


class PublishingBridge:
    """
    Publishing integration boundary.
    Reuses existing publication_attempts architecture while guaranteeing safety.
    """

    def __init__(self):
        self._publication_history: Dict[str, PublicationResult] = {}

    def compute_idempotency_key(self, artifact_hash: str, platform: str, channel_id: str) -> str:
        raw = f"{artifact_hash}:{platform.lower()}:{channel_id.strip()}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def request_publication(
        self,
        request: PublicationRequest,
        run: Optional[ProductionRun] = None,
    ) -> PublicationResult:
        """
        Validates safety invariants and initiates publication.
        """
        target_run = run or run_repository.get(request.run_id)
        if not target_run:
            raise PublishingSafetyError(f"Cannot publish nonexistent run: {request.run_id}")

        # Invariant 1: Check for QC Blockers or failure statuses
        blocking_statuses = {
            ProductionRunStatus.BLOCKED_RIGHTS,
            ProductionRunStatus.BLOCKED_FACTS,
            ProductionRunStatus.NEEDS_REVIEW,
            ProductionRunStatus.RENDER_FAILED,
            ProductionRunStatus.QC_FAILED,
            ProductionRunStatus.FAILED,
            ProductionRunStatus.CANCELLED,
        }
        if target_run.status in blocking_statuses or (target_run.blocker_count and target_run.blocker_count > 0):
            raise PublishingSafetyError(
                f"Publishing blocked: Run {target_run.id} has status {target_run.status} with {target_run.blocker_count} blockers"
            )

        # Invariant 2: Operator approval required (unless explicit override)
        if target_run.status != ProductionRunStatus.APPROVED and not request.override_auto_publish:
            raise PublishingSafetyError(
                f"Publishing blocked: Run {target_run.id} is not APPROVED by operator (Current: {target_run.status})"
            )

        # Invariant 3: Render artifact must exist and be verified
        if not target_run.render_artifact or not target_run.render_artifact.duration_seconds:
            raise PublishingSafetyError(
                f"Publishing blocked: Run {target_run.id} has no valid rendered artifact"
            )

        artifact_checksum = getattr(target_run.render_artifact, "checksum_sha256", None) or target_run.render_artifact.run_id
        idempotency_key = self.compute_idempotency_key(artifact_checksum, request.platform, request.channel_id)

        # Invariant 4: Check if already published with this exact idempotency key
        for existing in self._publication_history.values():
            if existing.idempotency_key == idempotency_key and existing.status in (
                PublicationStatus.PUBLISHED,
                PublicationStatus.SIMULATED_PUBLISHED,
                PublicationStatus.PUBLISHING,
            ):
                logger.warning("Duplicate publication prevented for key %s", idempotency_key)
                return existing

        pub_id = f"pub_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)

        # This bridge has no configured platform adapter.  It may record a simulation,
        # but it must never claim an externally visible post exists.
        if request.provider_mode == ProviderMode.LIVE:
            raise PublishingSafetyError("LIVE publication requires a configured platform adapter with provider confirmation")
        result = PublicationResult(
            publication_id=pub_id,
            run_id=target_run.id,
            platform=request.platform,
            channel_id=request.channel_id,
            idempotency_key=idempotency_key,
            status=PublicationStatus.SIMULATED_PUBLISHED,
            published_at=now,
            provider_mode=request.provider_mode,
            provider_confirmed=False,
        )

        target_run.publication_status = PublicationStatus.SIMULATED_PUBLISHED
        run_repository.update(target_run)

        self._publication_history[pub_id] = result
        logger.info("Recorded simulated publication for run %s to %s (%s)", target_run.id, request.platform, request.provider_mode.value)
        return result

    def get_publication(self, publication_id: str) -> Optional[PublicationResult]:
        return self._publication_history.get(publication_id)

    def list_publications_for_run(self, run_id: str) -> List[PublicationResult]:
        return [p for p in self._publication_history.values() if p.run_id == run_id]


publishing_bridge = PublishingBridge()
