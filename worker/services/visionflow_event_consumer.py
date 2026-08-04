"""Redis Streams consumer for VisionFlow workflow queue events.

The first worker action is deliberately idempotent: QUEUED -> PLANNING.  The
Control Plane rejects stale transitions, so a redelivery cannot start work
twice after the workflow has already been claimed.
"""

from __future__ import annotations

import json
import os
import socket
from dataclasses import dataclass

from redis import Redis

from worker.application.visionflow_short_form_intelligence import (
    LegacyLlmShortFormGenerator,
    VisionFlowShortFormIntelligence,
)
from worker.services.visionflow_control_plane_client import VisionFlowControlPlaneClient


@dataclass(frozen=True)
class VisionFlowEventConsumerSettings:
    redis_url: str
    stream: str
    group: str
    consumer: str

    @classmethod
    def from_env(cls) -> "VisionFlowEventConsumerSettings":
        redis_url = os.getenv("REDIS_URL", "").strip()
        if not redis_url:
            raise ValueError("REDIS_URL must be configured")
        if not redis_url.startswith(("rediss://", "redis://localhost", "redis://127.0.0.1")):
            raise ValueError("REDIS_URL must use TLS outside local development")
        return cls(
            redis_url=redis_url,
            stream=os.getenv("VISIONFLOW_EVENTS_STREAM", "visionflow.workflow-events.v1").strip(),
            group=os.getenv("VISIONFLOW_WORKER_GROUP", "visionflow-intelligence-v1").strip(),
            consumer=os.getenv("VISIONFLOW_WORKER_CONSUMER", socket.gethostname()).strip(),
        )


class VisionFlowEventConsumer:
    def __init__(self, redis: Redis, settings: VisionFlowEventConsumerSettings, control_plane: VisionFlowControlPlaneClient, intelligence: VisionFlowShortFormIntelligence | None = None, render_dispatcher: object | None = None) -> None:
        self._redis = redis
        self._settings = settings
        self._control_plane = control_plane
        self._intelligence = intelligence or VisionFlowShortFormIntelligence(control_plane, LegacyLlmShortFormGenerator())
        self._render_dispatcher = render_dispatcher

    def ensure_group(self) -> None:
        try:
            self._redis.xgroup_create(self._settings.stream, self._settings.group, id="0", mkstream=True)
        except Exception as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def consume_once(self, *, block_ms: int = 5000, count: int = 10) -> int:
        messages = self._redis.xreadgroup(
            self._settings.group,
            self._settings.consumer,
            {self._settings.stream: ">"},
            count=count,
            block=block_ms,
        )
        handled = 0
        for _stream, entries in messages:
            for message_id, fields in entries:
                self._handle(fields)
                self._redis.xack(self._settings.stream, self._settings.group, message_id)
                handled += 1
        return handled

    def _handle(self, fields: dict[str, str]) -> None:
        if fields.get("event_type") != "visionflow.workflow_run.state_changed.v1":
            return
        payload = json.loads(fields.get("payload", "{}"))
        workflow_run_id = str(payload["workflow_run_id"])

        # ─── Phát hiện AI Dubbing job sớm ───────────────────────────────────
        intake_raw = payload.get("intake") or {}
        input_payload_raw = intake_raw.get("input_payload") or {}
        prompt_manifest_raw = intake_raw.get("prompt_manifest") or {}
        render_mode_raw = (
            input_payload_raw.get("render_mode")
            or prompt_manifest_raw.get("render_mode")
        )
        title_raw = str(intake_raw.get("title") or intake_raw.get("brief") or "")
        is_dubbing_job = (render_mode_raw == "TRANSLATE_DUB" or title_raw.startswith("[DUB]"))

        if is_dubbing_job:
            import logging
            _dub_log = logging.getLogger(__name__)
            _dub_log.info(
                "Dubbing job detected for workflow %s (%s) — dispatching DubbingStrategy directly.",
                workflow_run_id, title_raw[:60],
            )
            try:
                import asyncio
                from worker.application.render_strategies.dubbing_strategy import DubbingStrategy
                from worker.domain.render_contract import RenderContract, RenderMode, RenderStopStage

                dub_meta = {**input_payload_raw, **prompt_manifest_raw}
                job_dict = {
                    "id": workflow_run_id,
                    "video_title_idea": title_raw,
                    "scenes_layout_json": json.dumps(dub_meta),
                }
                contract = RenderContract(
                    job_id=workflow_run_id,
                    title=title_raw,
                    topic=dub_meta.get("dub_source_url") or title_raw,
                    audience="auto-dubbing",
                    mode=RenderMode.TRANSLATE_DUB,
                    stop_at=RenderStopStage.VIDEO,
                    voice_code=dub_meta.get("voice_code") or "edge-nam-minh",
                    metadata=dub_meta,
                )
                asyncio.run(DubbingStrategy().execute(job_dict, contract))
            except Exception as dub_err:
                _dub_log.error(
                    "DubbingStrategy failed for workflow %s: %s", workflow_run_id, dub_err
                )
                # Mark workflow as FAILED in Control Plane — do NOT re-raise so
                # the consumer continues processing other events in the stream.
                try:
                    import sys as _sys
                    import pathlib
                    _root = pathlib.Path(__file__).resolve().parents[2]
                    _cp_dir = str(_root / "services" / "control-plane")
                    if _cp_dir not in _sys.path:
                        _sys.path.insert(0, _cp_dir)

                    from app.core.dubbing_bridge import sync_dubbing_job_to_control_plane
                    sync_dubbing_job_to_control_plane(
                        job_id=workflow_run_id,
                        title=title_raw,
                        metadata={"error": str(dub_err)[:500]},
                        state="FAILED",
                        workflow_run_id=workflow_run_id,
                    )
                except Exception as cp_err:
                    _dub_log.warning(
                        "Could not mark workflow %s FAILED in Control Plane: %s",
                        workflow_run_id, cp_err,
                    )
            return


        # ─── Standard Short-Form pipeline ────────────────────────────────────
        if payload.get("to_state") == "STORYBOARDED":
            if self._render_dispatcher is None:
                return
            trace_id = fields.get("trace_id")
            if not isinstance(trace_id, str):
                raise ValueError("STORYBOARDED workflow event is missing its trace_id")
            try:
                self._render_dispatcher.dispatch(workflow_run_id, trace_id=trace_id)
            except Exception as dispatch_err:
                import logging
                logging.getLogger(__name__).warning(
                    "STORYBOARDED dispatch failed for workflow %s (non-fatal, e.g. deleted/not found workflow): %s",
                    workflow_run_id, dispatch_err
                )
            return
        if payload.get("to_state") != "QUEUED":
            return
        intake = payload.get("intake")
        if not isinstance(intake, dict) or not isinstance(intake.get("brief"), str) or not intake["brief"].strip():
            raise ValueError("QUEUED workflow event is missing its immutable intake envelope")
        # Queue messages deliberately remain small. Fetch the locked creative
        # snapshot at claim time so the worker renders exactly what the
        # operator approved, never a mutable editor draft.
        creative_doc = None
        try:
            creative_doc = self._control_plane.get_creative_document(workflow_run_id, trace_id=fields.get("trace_id"))
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(
                "Could not fetch creative document for workflow %s (non-fatal): %s",
                workflow_run_id,
                exc,
            )

        intake = {**intake, "creative_document": creative_doc}
        self._intelligence.execute(
            workflow_run_id,
            intake,
            event_id=fields["event_id"],
            trace_id=fields.get("trace_id"),
        )


