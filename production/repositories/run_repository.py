"""
Development Run Repository Adapter for VisionFlow Auto Production System
Implements ProductionRunRepositoryInterface using local JSON file persistence.
Survives process restart. Marked as DEVELOPMENT ADAPTER.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from production.contracts import (
    EditorPlan,
    ProductionRun,
    ProductionRunStatus,
    ProductionStageRun,
    QualityReport,
    StageStatus,
)
from production.repositories.base import ProductionRunRepositoryInterface


STORAGE_DIR = Path(__file__).resolve().parent.parent / ".runs_storage"
STORAGE_DIR.mkdir(exist_ok=True, parents=True)


class DevelopmentRunRepository(ProductionRunRepositoryInterface):
    """
    DEVELOPMENT ADAPTER: Local JSON file storage with in-memory write-through cache.
    Ensures runs survive process restarts during local dev and testing.
    """
    _instance: Optional[DevelopmentRunRepository] = None
    _runs: Dict[str, ProductionRun] = {}

    def __new__(cls) -> DevelopmentRunRepository:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load_persisted()
        return cls._instance

    def _get_file_path(self, run_id: str) -> Path:
        return STORAGE_DIR / f"{run_id}.json"

    def _persist(self, run: ProductionRun) -> None:
        try:
            file_path = self._get_file_path(run.id)
            tmp_path = file_path.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(run.model_dump_json(indent=2))
            import os
            os.replace(tmp_path, file_path)
        except Exception as e:
            print(f"[DevelopmentRunRepository] Warning: failed to persist run {run.id}: {e}")

    def _load_persisted(self) -> None:
        try:
            for file_path in STORAGE_DIR.glob("*.json"):
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        run = ProductionRun.model_validate(data)
                        self._runs[run.id] = run
                except Exception:
                    continue
        except Exception as e:
            print(f"[DevelopmentRunRepository] Warning: error reading persisted runs: {e}")

    def create(self, run: ProductionRun) -> ProductionRun:
        self._runs[run.id] = run
        self._persist(run)
        return run

    def get(self, run_id: str) -> Optional[ProductionRun]:
        # Always check disk if not in memory or to verify restart survival
        if run_id not in self._runs:
            file_path = self._get_file_path(run_id)
            if file_path.exists():
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        self._runs[run_id] = ProductionRun.model_validate(json.load(f))
                except Exception:
                    pass
        return self._runs.get(run_id)

    def list_all(self, limit: int = 50) -> List[ProductionRun]:
        sorted_runs = sorted(self._runs.values(), key=lambda r: r.created_at, reverse=True)
        return sorted_runs[:limit]

    def find_resumable_runs(self) -> List[ProductionRun]:
        """Returns runs that were interrupted or left unfinished prior to terminal states."""
        terminal_states = {
            ProductionRunStatus.READY,
            ProductionRunStatus.APPROVED,
            ProductionRunStatus.FAILED,
            ProductionRunStatus.CANCELLED,
            ProductionRunStatus.CHANGES_REQUESTED,
        }
        resumable = [
            r for r in self._runs.values()
            if r.status not in terminal_states
        ]
        return sorted(resumable, key=lambda r: r.created_at, reverse=True)

    def update_status(
        self,
        run_id: str,
        status: ProductionRunStatus,
        current_stage: Optional[str] = None,
        progress_pct: Optional[int] = None,
        error_message: Optional[str] = None,
    ) -> Optional[ProductionRun]:
        run = self.get(run_id)
        if not run:
            return None
        run.status = status
        run.updated_at = datetime.now(timezone.utc)
        if current_stage is not None:
            run.current_stage = current_stage
        if progress_pct is not None:
            run.progress_pct = max(0, min(100, progress_pct))
        if error_message is not None:
            run.error_message = error_message
        self._persist(run)
        return run

    def add_stage(self, run_id: str, stage: ProductionStageRun) -> Optional[ProductionRun]:
        run = self.get(run_id)
        if not run:
            return None
        existing_idx = next((i for i, s in enumerate(run.stages) if s.stage_name == stage.stage_name), None)
        if existing_idx is not None:
            run.stages[existing_idx] = stage
        else:
            run.stages.append(stage)
        run.updated_at = datetime.now(timezone.utc)
        self._persist(run)
        return run

    def update_stage_status(
        self,
        run_id: str,
        stage_name: str,
        status: StageStatus,
        output_json: Optional[Dict] = None,
        error_code: Optional[str] = None,
        duration_ms: Optional[int] = None,
        is_cached: bool = False,
    ) -> Optional[ProductionRun]:
        run = self.get(run_id)
        if not run:
            return None
        stage = next((s for s in run.stages if s.stage_name == stage_name), None)
        if stage:
            stage.status = status
            stage.is_cached = is_cached
            if is_cached:
                stage.execution_mode = "CACHED"
            if output_json is not None:
                stage.output_json = output_json
            if error_code is not None:
                stage.error_code = error_code
            if duration_ms is not None:
                stage.duration_ms = duration_ms
            run.updated_at = datetime.now(timezone.utc)
            self._persist(run)
        return run

    def set_editor_plan(self, run_id: str, editor_plan: EditorPlan) -> Optional[ProductionRun]:
        run = self.get(run_id)
        if not run:
            return None
        run.editor_plan = editor_plan
        run.updated_at = datetime.now(timezone.utc)
        self._persist(run)
        return run

    def set_quality_report(self, run_id: str, quality_report: QualityReport) -> Optional[ProductionRun]:
        run = self.get(run_id)
        if not run:
            return None
        run.quality_report = quality_report
        run.quality_score = quality_report.score
        run.blocker_count = quality_report.blocker_count
        run.updated_at = datetime.now(timezone.utc)
        self._persist(run)
        return run

    def update(self, run: ProductionRun) -> ProductionRun:
        run.updated_at = datetime.now(timezone.utc)
        self._runs[run.id] = run
        self._persist(run)
        return run

    def clear_all(self) -> None:
        """Helper for clean testing environment."""
        self._runs.clear()
        for f in STORAGE_DIR.glob("*.json"):
            try:
                f.unlink()
            except Exception:
                pass


# Global accessor
run_repository: ProductionRunRepositoryInterface = DevelopmentRunRepository()
RunRepository = DevelopmentRunRepository

def get_run_repository() -> ProductionRunRepositoryInterface:
    return run_repository

