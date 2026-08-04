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
        if payload.get("to_state") == "STORYBOARDED":
            if self._render_dispatcher is None:
                return
            trace_id = fields.get("trace_id")
            if not isinstance(trace_id, str):
                raise ValueError("STORYBOARDED workflow event is missing its trace_id")
            self._render_dispatcher.dispatch(workflow_run_id, trace_id=trace_id)
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
                "Could not fetch creative document for workflow %s (non-fatal, e.g. Dubbing job): %s",
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

