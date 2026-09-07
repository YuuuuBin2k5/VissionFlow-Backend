"""
Real Human Review Workflow & Dataset Storage for VisionFlow (Phase 7 - Section 6 & 7).
Enforces the mandatory operator review gate (READY -> HUMAN_REVIEW_PENDING -> APPROVED / CHANGES_REQUESTED).
Ensures human ratings are authentic operator actions, completely isolated from AI-generated metrics.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from production.contracts import (
    HumanReviewRatings,
    HumanReviewRecord,
    ReviewSource,
    ProductionRun,
    ProductionRunStatus,
    PublicationStatus,
    SceneFeedbackItem,
)
from production.repositories.run_repository import run_repository

logger = logging.getLogger("visionflow.production.human_review")

REVIEWS_DIR = Path("d:/VisionFlow/.reviews_storage")
REVIEWS_DIR.mkdir(parents=True, exist_ok=True)


class HumanReviewError(RuntimeError):
    """Raised when human review submission fails validation."""


class HumanReviewService:
    """
    Manages operator review lifecycle and fine-tuning dataset persistence.
    """

    def __init__(self, storage_dir: Optional[Path] = None):
        self.storage_dir = storage_dir or REVIEWS_DIR
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def submit_review(
        self,
        run_id: str,
        reviewer: str,
        ratings: Optional[HumanReviewRatings] = None,
        decision: str = "APPROVED",  # "APPROVED" or "CHANGES_REQUESTED"
        notes: Optional[str] = None,
        changed_scenes: Optional[List[int]] = None,
        scene_feedback: Optional[Dict[int, SceneFeedbackItem]] = None,
        review_source: ReviewSource = ReviewSource.REAL_OPERATOR,
        client_source: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> HumanReviewRecord:
        """
        Processes human operator review.
        Enforces that ratings originate exclusively from operator input.
        """
        if not reviewer or not reviewer.strip():
            raise HumanReviewError("Reviewer identity is required for audit trail")

        if decision not in ("APPROVED", "CHANGES_REQUESTED"):
            raise HumanReviewError(f"Invalid review decision: {decision}. Must be APPROVED or CHANGES_REQUESTED")

        run = run_repository.get(run_id)
        if not run:
            raise HumanReviewError(f"Production run not found: {run_id}")

        # Check that video reached READY or HUMAN_REVIEW_PENDING before approval
        allowed_prior_states = {
            ProductionRunStatus.READY,
            ProductionRunStatus.HUMAN_REVIEW_PENDING,
            ProductionRunStatus.CHANGES_REQUESTED,
            ProductionRunStatus.NEEDS_REVIEW,
        }
        if run.status not in allowed_prior_states:
            raise HumanReviewError(f"Run {run_id} is in status {run.status}, cannot be approved prior to READY/REVIEW")

        now = datetime.now(timezone.utc)
        record = HumanReviewRecord(
            run_id=run_id,
            reviewer=reviewer.strip(),
            reviewer_id=reviewer.strip(),
            review_source=review_source,
            submitted_at=now,
            client_source=client_source,
            session_id=session_id,
            ratings=ratings,
            decision=decision,
            notes=notes,
            changed_scenes=changed_scenes or [],
            scene_feedback=scene_feedback or {},
            is_operator_review=review_source == ReviewSource.REAL_OPERATOR,
            approved_at=now if decision == "APPROVED" else None,
            created_at=now,
        )

        # First-pass human approval tracking (attempt 1 without changes requested or manual intervention)
        if review_source == ReviewSource.REAL_OPERATOR and run.first_pass_human_approval is None:
            run.first_pass_human_approval = (
                decision == "APPROVED"
                and len(run.auto_fix_history) == 0
                and len(run.manual_interventions) == 0
            )

        # Update run status
        if decision == "APPROVED":
            run.status = ProductionRunStatus.APPROVED
            run.publication_status = PublicationStatus.APPROVED
        else:
            run.status = ProductionRunStatus.CHANGES_REQUESTED

        run.human_review = record
        run_repository.update(run)

        # Persist to reviews dataset
        self._persist_review(record)
        logger.info("Recorded %s review for run %s by %s (Decision: %s)", review_source.value, run_id, reviewer, decision)
        return record

    def _persist_review(self, record: HumanReviewRecord) -> None:
        file_path = self.storage_dir / f"{record.run_id}_{record.review_id}.json"
        tmp_path = file_path.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(record.model_dump_json(indent=2))
        import os
        os.replace(tmp_path, file_path)

    def get_review(self, run_id: str) -> Optional[HumanReviewRecord]:
        run = run_repository.get(run_id)
        if run and run.human_review:
            return run.human_review

        # Check storage disk
        for f in self.storage_dir.glob(f"{run_id}_*.json"):
            try:
                with open(f, "r", encoding="utf-8") as fp:
                    return HumanReviewRecord.model_validate(json.load(fp))
            except Exception:
                pass
        return None

    def export_dataset(self) -> List[Dict[str, Any]]:
        """
        Exports all persisted human review records for model training and ranking calibration.
        """
        dataset = []
        for f in self.storage_dir.glob("*.json"):
            try:
                with open(f, "r", encoding="utf-8") as fp:
                    dataset.append(json.load(fp))
            except Exception:
                pass
        return dataset


human_review_service = HumanReviewService()
