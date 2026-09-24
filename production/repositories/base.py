"""
Repository Interface for VisionFlow Auto Production System
Defines the storage contract so SQLite / Postgres / MySQL can be plugged in without changing the Orchestrator.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Protocol
from production.contracts import (
    EditorPlan,
    ProductionRun,
    ProductionRunStatus,
    ProductionStageRun,
    QualityReport,
    StageStatus,
)


class ProductionRunRepositoryInterface(Protocol):
    def create(self, run: ProductionRun) -> ProductionRun:
        ...

    def get(self, run_id: str) -> Optional[ProductionRun]:
        ...

    def list_all(self, limit: int = 50) -> List[ProductionRun]:
        ...

    def update_status(
        self,
        run_id: str,
        status: ProductionRunStatus,
        current_stage: Optional[str] = None,
        progress_pct: Optional[int] = None,
        error_message: Optional[str] = None,
    ) -> Optional[ProductionRun]:
        ...

    def add_stage(self, run_id: str, stage: ProductionStageRun) -> Optional[ProductionRun]:
        ...

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
        ...

    def set_editor_plan(self, run_id: str, editor_plan: EditorPlan) -> Optional[ProductionRun]:
        ...

    def set_quality_report(self, run_id: str, quality_report: QualityReport) -> Optional[ProductionRun]:
        ...

    def update(self, run: ProductionRun) -> ProductionRun:
        ...
