"""VF-03.02a Commit 2 — Narration handoff coordinator and shadow reconciler."""
from __future__ import annotations

import datetime
import hashlib
import json
import logging
import os
import uuid
from typing import Any

from worker.config import ConfigurationError
from worker.domain.narration_sink import NarrationSinkPort, get_deterministic_workflow_run_id
from worker.infrastructure.repositories.video_job_repository import VideoJobRepository
from worker.services.visionflow_control_plane_client import VisionFlowControlPlaneClient, VisionFlowWorkerSettings

logger = logging.getLogger("visionflow.handoff")
reconciliation_logger = logging.getLogger("visionflow.shadow_reconciliation")


class MySqlNarrationSink(NarrationSinkPort):
    """Legacy MySQL database adapter for narration script sinking."""

    def __init__(self, repo: VideoJobRepository | None = None) -> None:
        self._repo = repo or VideoJobRepository()

    def save_narration_result(
        self,
        job_id: int,
        hook: str,
        full_script: str,
        scenes_layout_json: Any,
        seo_tags: dict[str, Any],
        *,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            self._repo.save_script_result(job_id, hook, full_script, scenes_layout_json, seo_tags)
            return {"success": True, "source": "legacy"}
        except Exception as exc:
            logger.error(f"Legacy MySQL save failed for Job #{job_id}: {exc}")
            return {"success": False, "source": "legacy", "error": str(exc)}


class ControlPlaneNarrationSink(NarrationSinkPort):
    """PostgreSQL Control Plane adapter for narration script sinking."""

    def __init__(self, client: VisionFlowControlPlaneClient | None = None) -> None:
        self._client = client or VisionFlowControlPlaneClient(VisionFlowWorkerSettings.from_env())

    def save_narration_result(
        self,
        job_id: int,
        hook: str,
        full_script: str,
        scenes_layout_json: Any,
        seo_tags: dict[str, Any],
        *,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            # 1. Resolve workflow_run_id
            workflow_run_id_val = seo_tags.get("workflow_run_id")
            if not workflow_run_id_val:
                workflow_run_id = get_deterministic_workflow_run_id(job_id)
            else:
                try:
                    workflow_run_id = uuid.UUID(str(workflow_run_id_val))
                except ValueError:
                    workflow_run_id = get_deterministic_workflow_run_id(job_id)

            # 2. Resolve organization_id
            organization_id_val = seo_tags.get("organization_id") or os.environ.get("VISIONFLOW_ORGANIZATION_ID")
            if not organization_id_val:
                raise ValueError("VISIONFLOW_ORGANIZATION_ID is required for Control Plane sink")
            organization_id = uuid.UUID(str(organization_id_val))

            # 3. Create stable, deterministic idempotency key based on script content hash
            script_hash = hashlib.sha256(full_script.encode("utf-8")).hexdigest()[:16]
            idempotency_key = f"narration-{workflow_run_id}-{script_hash}"

            # 4. Map scenes to Control Plane request format
            raw_scenes = []
            if isinstance(scenes_layout_json, dict):
                raw_scenes = scenes_layout_json.get("scenes_layout", [])
            elif isinstance(scenes_layout_json, list):
                raw_scenes = scenes_layout_json

            scenes_list = []
            for scene in raw_scenes:
                narration = str(scene.get("narration") or scene.get("subtitle") or "").strip()
                visual_prompt = str(scene.get("visual_search_keywords") or scene.get("visual_prompt") or "").strip()
                duration = int(scene.get("duration") or scene.get("duration_seconds") or 5)
                scenes_list.append({
                    "narration": narration,
                    "visual_prompt": visual_prompt,
                    "duration_seconds": duration,
                    "transition": scene.get("transition"),
                    "caption": scene.get("caption"),
                })

            # 5. Extract LLM metadata if available
            source_metadata = {
                "provider": seo_tags.get("source_metadata", {}).get("provider") or "openai",
                "model": seo_tags.get("source_metadata", {}).get("model") or "gpt-4",
            }

            # 6. Call Control Plane complete_narration
            res = self._client.complete_narration(
                workflow_run_id=str(workflow_run_id),
                organization_id=str(organization_id),
                idempotency_key=idempotency_key,
                script=full_script,
                scenes=scenes_list,
                source_metadata=source_metadata,
                legacy_job_id=str(job_id),
                trace_id=trace_id,
            )
            return {
                "success": True,
                "source": "control_plane",
                "version_id": res.get("version_id"),
                "version": res.get("version"),
                "state": res.get("state"),
                "idempotency_key": idempotency_key,
                "workflow_run_id": workflow_run_id,
            }
        except Exception as exc:
            # Safe diagnostics logging (does not log prompts, scripts or credentials)
            logger.warning(f"Control Plane complete_narration failed for Job #{job_id}: {exc}")
            return {"success": False, "source": "control_plane", "error": str(exc)}


class ShadowReconciler:
    """Read-only shadow reconciler checking legacy and control plane output parity."""

    def reconcile(
        self,
        job_id: int,
        workflow_run_id: str | uuid.UUID,
        idempotency_key: str,
        full_script: str,
        scenes_layout_json: Any,
        cp_result: dict[str, Any],
        *,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        # Normalized hashes (safe, no full scripts or prompts are stored)
        normalized_script_hash = hashlib.sha256(full_script.strip().lower().encode("utf-8")).hexdigest()

        raw_scenes = []
        if isinstance(scenes_layout_json, dict):
            raw_scenes = scenes_layout_json.get("scenes_layout", [])
        elif isinstance(scenes_layout_json, list):
            raw_scenes = scenes_layout_json

        scene_durations = [str(s.get("duration") or s.get("duration_seconds") or 5) for s in raw_scenes]
        scene_str = f"count:{len(raw_scenes)}|durations:[{','.join(scene_durations)}]"
        normalized_scenes_hash = hashlib.sha256(scene_str.encode("utf-8")).hexdigest()

        if not cp_result.get("success", False):
            result_status = "control-plane-failed"
            cp_version_id = None
        else:
            cp_version_id = cp_result.get("version_id")
            if cp_result.get("state") == "SCRIPTED":
                result_status = "matched"
            else:
                result_status = "mismatched"

        report = {
            "workflow_run_id": str(workflow_run_id),
            "legacy_job_id": int(job_id),
            "idempotency_key": idempotency_key,
            "control_plane_version_id": str(cp_version_id) if cp_version_id else None,
            "normalized_script_hash": normalized_script_hash,
            "normalized_scenes_hash": normalized_scenes_hash,
            "result": result_status,
            "trace_id": trace_id,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
        }

        # Log to structured comparison logger
        reconciliation_logger.info(json.dumps(report))
        return report


class NarrationHandoffCoordinator:
    """Orchestrates handoff modes (legacy, shadow, control_plane) for narration."""

    def __init__(
        self,
        mysql_sink: NarrationSinkPort | None = None,
        cp_sink: NarrationSinkPort | None = None,
        reconciler: ShadowReconciler | None = None,
    ) -> None:
        self._mysql_sink = mysql_sink or MySqlNarrationSink()
        self._cp_sink = cp_sink or ControlPlaneNarrationSink()
        self._reconciler = reconciler or ShadowReconciler()

    def handle_narration(
        self,
        job_id: int,
        hook: str,
        full_script: str,
        scenes_layout_json: Any,
        seo_tags: dict[str, Any],
        *,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        # Validate configuration before executing
        from worker.config import validate_config
        validate_config()

        mode = os.environ.get("VISIONFLOW_NARRATION_HANDOFF_MODE", "legacy").lower()

        if mode == "legacy":
            # 1. Legacy mode: only MySQL
            return self._mysql_sink.save_narration_result(
                job_id, hook, full_script, scenes_layout_json, seo_tags, trace_id=trace_id
            )

        if mode == "shadow":
            # 2. Shadow mode: MySQL is primary, Control Plane is shadow
            legacy_res = self._mysql_sink.save_narration_result(
                job_id, hook, full_script, scenes_layout_json, seo_tags, trace_id=trace_id
            )
            cp_res = self._cp_sink.save_narration_result(
                job_id, hook, full_script, scenes_layout_json, seo_tags, trace_id=trace_id
            )

            # Extract or compute run ID and idempotency key for reconciler
            workflow_run_id = cp_res.get("workflow_run_id") or get_deterministic_workflow_run_id(job_id)
            idempotency_key = cp_res.get("idempotency_key") or f"narration-{workflow_run_id}-shadow"

            self._reconciler.reconcile(
                job_id,
                workflow_run_id,
                idempotency_key,
                full_script,
                scenes_layout_json,
                cp_res,
                trace_id=trace_id,
            )
            return legacy_res

        if mode == "control_plane":
            # 3. Control Plane mode: only Control Plane, skip MySQL
            cp_res = self._cp_sink.save_narration_result(
                job_id, hook, full_script, scenes_layout_json, seo_tags, trace_id=trace_id
            )
            if not cp_res.get("success", False):
                # Fail closed on control plane save failure
                raise RuntimeError(f"Control Plane narration save failed: {cp_res.get('error')}")
            return cp_res

        raise ConfigurationError(f"Unsupported handoff mode: {mode}")
