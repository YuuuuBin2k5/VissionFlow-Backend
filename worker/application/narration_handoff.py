"""VF-03.02a.2 — Narration handoff coordinator, shadow reconciler, and adapters.

Per-job execution context is sourced exclusively from the authenticated
Control Plane API via get_execution_context_by_job_id(). Coordinators MUST
NOT derive context from environment variables for per-job identity.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import logging
import os
import uuid
from typing import Any

import requests
from worker.config import ConfigurationError
from worker.domain.narration_sink import NarrationSinkPort, WorkerExecutionContext
from worker.infrastructure.repositories.video_job_repository import VideoJobRepository
from worker.services.visionflow_control_plane_client import (
    VisionFlowControlPlaneClient,
    VisionFlowControlPlaneError,
    VisionFlowWorkerSettings,
)

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
        context: WorkerExecutionContext | None = None,
    ) -> dict[str, Any]:
        try:
            self._repo.save_script_result(job_id, hook, full_script, scenes_layout_json, seo_tags)
            return {"success": True, "source": "legacy"}
        except Exception as exc:
            logger.error(f"Legacy MySQL save failed for Job #{job_id}: {exc}", exc_info=True)
            return {"success": False, "source": "legacy", "error": "MYSQL_DATABASE_ERROR"}


class ControlPlaneNarrationSink(NarrationSinkPort):
    """PostgreSQL Control Plane adapter for narration script sinking.

    VF-03.02a.2: Context is fetched from the Control Plane API if not supplied
    by the caller. The caller (NarrationHandoffCoordinator) should always
    supply the context obtained via get_execution_context_by_job_id() so that
    per-job identity is authoritative before any write occurs.
    """

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
        context: WorkerExecutionContext | None = None,
    ) -> dict[str, Any]:
        # Resolve context from API if not pre-fetched by coordinator
        if not context:
            try:
                api_payload = self._client.get_execution_context_by_job_id(job_id)
                context = WorkerExecutionContext.from_api_response(
                    api_payload,
                    legacy_job_id=job_id,
                )
            except Exception as exc:
                logger.error(
                    f"Failed to fetch execution context from API for Job #{job_id}: {exc}",
                    exc_info=True,
                )
                return {
                    "success": False,
                    "source": "control_plane",
                    "error_code": "EXECUTION_CONTEXT_FETCH_FAILED",
                }

        # Tenancy boundary check
        if str(context.organization_id) != str(self._client._settings.organization_id):
            raise ValueError("Context organization_id mismatch with client configuration")

        trace_id = context.trace_id

        try:
            # 1. Semantic Idempotency Key based on run ID and attempt ID
            idempotency_key = f"narration-{context.workflow_run_id}-{context.narration_attempt_id}"

            # 2. Map scenes to Control Plane request format
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
                    "transition": str(scene.get("transition") or "cut").strip() or "cut",
                    "caption": str(scene.get("caption") or "").strip() or None,
                })

            # 3. Extract LLM metadata if available
            source_metadata = {
                "provider": seo_tags.get("source_metadata", {}).get("provider") or "openai",
                "model": seo_tags.get("source_metadata", {}).get("model") or "gpt-4",
            }

            # 4. Call Control Plane complete_narration
            res = self._client.complete_narration(
                workflow_run_id=str(context.workflow_run_id),
                organization_id=str(context.organization_id),
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
                "workflow_run_id": context.workflow_run_id,
            }
        except Exception as exc:
            # Exception safety: log traceback in server log, return safe error codes
            error_code = "CONTROL_PLANE_INTERNAL_ERROR"
            if isinstance(exc, VisionFlowControlPlaneError):
                error_code = "CONTROL_PLANE_API_ERROR"
            elif isinstance(exc, requests.Timeout):
                error_code = "CONTROL_PLANE_TIMEOUT"
            elif isinstance(exc, requests.ConnectionError):
                error_code = "CONTROL_PLANE_NETWORK_ERROR"

            logger.error(
                f"Control Plane complete_narration failed for Job #{job_id} [Trace ID: {trace_id}]: {exc}",
                exc_info=True
            )
            return {
                "success": False,
                "source": "control_plane",
                "error_code": error_code,
                "trace_id": trace_id,
            }


class ShadowReconciler:
    """Read-only shadow reconciler checking legacy and control plane output parity."""

    def reconcile(
        self,
        job_id: int,
        context: WorkerExecutionContext,
        idempotency_key: str,
        full_script: str,
        scenes_layout_json: Any,
        cp_result: dict[str, Any],
        client: VisionFlowControlPlaneClient,
    ) -> dict[str, Any]:
        # Normalized hashes (safe, no full scripts or prompts are stored)
        normalized_script_hash = hashlib.sha256(full_script.strip().lower().encode("utf-8")).hexdigest()

        report = {
            "workflow_run_id": str(context.workflow_run_id),
            "legacy_job_id": int(job_id),
            "idempotency_key": idempotency_key,
            "control_plane_version_id": None,
            "normalized_script_hash": normalized_script_hash,
            "result": "control-plane-failed",
            "mismatch_codes": [],
            "error_code": None,
            "trace_id": context.trace_id,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
            "observability_record_only": True,  # Observability record only, not authoritative state
        }

        if not cp_result.get("success", False):
            report["error_code"] = cp_result.get("error_code") or "CONTROL_PLANE_SUBMIT_FAILED"
            reconciliation_logger.info(json.dumps(report))
            return report

        report["control_plane_version_id"] = str(cp_result.get("version_id"))

        # Fetch actual Creative Document version from Control Plane API
        try:
            doc = client.get_creative_document(workflow_run_id=str(context.workflow_run_id), trace_id=context.trace_id)
        except Exception as exc:
            logger.error(
                f"Failed to fetch creative document for reconciliation of Job #{job_id} [Trace: {context.trace_id}]: {exc}",
                exc_info=True
            )
            report["error_code"] = "FETCH_CREATIVE_DOCUMENT_FAILED"
            reconciliation_logger.info(json.dumps(report))
            return report

        mismatch_codes = []

        # 1. Compare Script (normalized)
        legacy_script_normalized = full_script.strip().lower()
        cp_script_normalized = (doc.get("script") or "").strip().lower()
        if legacy_script_normalized != cp_script_normalized:
            mismatch_codes.append("SCRIPT_HASH_MISMATCH")

        # Normalize legacy scenes
        raw_scenes = []
        if isinstance(scenes_layout_json, dict):
            raw_scenes = scenes_layout_json.get("scenes_layout", [])
        elif isinstance(scenes_layout_json, list):
            raw_scenes = scenes_layout_json

        cp_scenes = sorted(doc.get("scenes", []), key=lambda s: s.get("position", 0))

        # 2. Compare Scene Count
        if len(raw_scenes) != len(cp_scenes):
            mismatch_codes.append("SCENE_COUNT_MISMATCH")
        else:
            # 3. Compare Scene fields and order (0-indexed position)
            for idx, legacy_scene in enumerate(raw_scenes):
                cp_scene = cp_scenes[idx]

                # Position check (0-indexed)
                if cp_scene.get("position") != idx:
                    mismatch_codes.append("SCENE_ORDER_MISMATCH")

                # Narration content
                leg_narration = str(legacy_scene.get("narration") or legacy_scene.get("subtitle") or "").strip()
                cp_narration = str(cp_scene.get("narration") or "").strip()
                if leg_narration != cp_narration:
                    mismatch_codes.append(f"SCENE_{idx}_NARRATION_MISMATCH")

                # Visual prompt content
                leg_prompt = str(legacy_scene.get("visual_search_keywords") or legacy_scene.get("visual_prompt") or "").strip()
                cp_prompt = str(cp_scene.get("visual_prompt") or "").strip()
                if leg_prompt != cp_prompt:
                    mismatch_codes.append(f"SCENE_{idx}_VISUAL_PROMPT_MISMATCH")

                # Duration
                leg_duration = int(legacy_scene.get("duration") or legacy_scene.get("duration_seconds") or 5)
                cp_duration = int(cp_scene.get("duration_seconds") or 5)
                if leg_duration != cp_duration:
                    mismatch_codes.append(f"SCENE_{idx}_DURATION_MISMATCH")

                # Transition
                leg_trans = str(legacy_scene.get("transition") or "cut").strip() or "cut"
                cp_trans = str(cp_scene.get("transition") or "cut").strip() or "cut"
                if leg_trans != cp_trans:
                    mismatch_codes.append(f"SCENE_{idx}_TRANSITION_MISMATCH")

                # Caption presence/content
                leg_cap = str(legacy_scene.get("caption") or "").strip() or None
                cp_cap = str(cp_scene.get("caption") or "").strip() or None
                if (leg_cap is None) != (cp_cap is None):
                    mismatch_codes.append(f"SCENE_{idx}_CAPTION_PRESENCE_MISMATCH")
                elif leg_cap is not None and leg_cap != cp_cap:
                    mismatch_codes.append(f"SCENE_{idx}_CAPTION_CONTENT_MISMATCH")

        if mismatch_codes:
            report["result"] = "mismatched"
            report["mismatch_codes"] = mismatch_codes
        else:
            report["result"] = "matched"

        reconciliation_logger.info(json.dumps(report))
        return report


class NarrationHandoffCoordinator:
    """Orchestrates handoff modes (legacy, shadow, control_plane) for narration.

    VF-03.02a.2: In shadow/control_plane modes, the coordinator fetches the
    authoritative per-job execution context from the Control Plane API before
    any write. It never derives context from environment variables per-job.
    """

    def __init__(
        self,
        mysql_sink: NarrationSinkPort | None = None,
        cp_sink: NarrationSinkPort | None = None,
        reconciler: ShadowReconciler | None = None,
        client: VisionFlowControlPlaneClient | None = None,
    ) -> None:
        self._mysql_sink = mysql_sink or MySqlNarrationSink()
        self._reconciler = reconciler or ShadowReconciler()
        if cp_sink:
            self._cp_sink = cp_sink
            self._client = client
        else:
            try:
                self._client = client or VisionFlowControlPlaneClient(VisionFlowWorkerSettings.from_env())
            except Exception:
                self._client = client
            self._cp_sink = ControlPlaneNarrationSink(self._client)

    def handle_narration(
        self,
        job_id: int,
        hook: str,
        full_script: str,
        scenes_layout_json: Any,
        seo_tags: dict[str, Any],
        *,
        context: WorkerExecutionContext | None = None,
    ) -> dict[str, Any]:
        # Validate configuration before execution
        from worker.config import validate_config
        validate_config()

        mode = os.environ.get("VISIONFLOW_NARRATION_HANDOFF_MODE", "legacy").lower()

        # Resolve authoritative per-job context from the Control Plane API
        # if in shadow/control_plane mode and no context was pre-fetched.
        if mode in {"shadow", "control_plane"}:
            if not context:
                if self._client is None:
                    raise ConfigurationError(
                        f"Control Plane client is not configured for handoff mode {mode}"
                    )
                try:
                    api_payload = self._client.get_execution_context_by_job_id(job_id)
                    context = WorkerExecutionContext.from_api_response(
                        api_payload,
                        legacy_job_id=job_id,
                    )
                except (VisionFlowControlPlaneError, ValueError) as exc:
                    # Fail closed immediately before any write
                    raise ConfigurationError(
                        f"Trusted context fetch from API failed for Job #{job_id} (mode: {mode}): {exc}"
                    ) from exc
                except Exception as exc:
                    raise ConfigurationError(
                        f"Unexpected error fetching execution context for Job #{job_id}: {exc}"
                    ) from exc

        if mode == "legacy":
            return self._mysql_sink.save_narration_result(
                job_id, hook, full_script, scenes_layout_json, seo_tags, context=context
            )

        if mode == "shadow":
            # Primary MySQL write
            legacy_res = self._mysql_sink.save_narration_result(
                job_id, hook, full_script, scenes_layout_json, seo_tags, context=context
            )

            # Shadow Control Plane write
            cp_res = self._cp_sink.save_narration_result(
                job_id, hook, full_script, scenes_layout_json, seo_tags, context=context
            )

            # Reconcile outputs
            idempotency_key = cp_res.get("idempotency_key") or f"narration-{context.workflow_run_id}-{context.narration_attempt_id}"
            self._reconciler.reconcile(
                job_id,
                context,
                idempotency_key,
                full_script,
                scenes_layout_json,
                cp_res,
                self._client,
            )
            return legacy_res

        if mode == "control_plane":
            cp_res = self._cp_sink.save_narration_result(
                job_id, hook, full_script, scenes_layout_json, seo_tags, context=context
            )
            if not cp_res.get("success", False):
                raise RuntimeError(f"Control Plane narration save failed with error code: {cp_res.get('error_code')}")
            return cp_res

        raise ConfigurationError(f"Unsupported handoff mode: {mode}")
