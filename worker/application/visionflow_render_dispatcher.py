"""Dispatch a completed storyboard to the isolated VisionFlow render workflow.

The dispatcher is an anti-corruption boundary: it reads the immutable execution
context through the Control Plane API, never from a database or legacy job.
"""

from __future__ import annotations

from typing import Any, Protocol

from worker.application.visionflow_render_workflow import (
    RenderedArtifact,
    VisionFlowRenderWorkflow,
)
from worker.domain.visionflow_render_contract import build_visionflow_render_contract


class ExecutionContextGateway(Protocol):
    def get_execution_context(
        self, workflow_run_id: str, *, trace_id: str | None = None
    ) -> dict[str, Any]: ...


class VisionFlowRenderDispatcher:
    """Build and execute a render contract only for a STORYBOARDED workflow."""

    def __init__(
        self,
        control_plane: ExecutionContextGateway,
        render_workflow: VisionFlowRenderWorkflow,
    ) -> None:
        self._control_plane = control_plane
        self._render_workflow = render_workflow

    def dispatch(self, workflow_run_id: str, *, trace_id: str) -> RenderedArtifact:
        if not workflow_run_id.strip() or len(trace_id) != 32:
            raise ValueError("workflow_run_id and a 32-character trace_id are required")

        context = self._control_plane.get_execution_context(workflow_run_id, trace_id=trace_id)
        if context.get("state") != "STORYBOARDED":
            raise ValueError("render dispatch requires a STORYBOARDED workflow")
        intake = context.get("intake")
        steps = context.get("steps")
        if not isinstance(intake, dict) or not isinstance(steps, dict):
            raise ValueError("execution context must include intake and steps objects")

        script = _required_script(steps.get("script"))
        scenes = _required_scenes(steps.get("storyboard"))
        contract = build_visionflow_render_contract(
            workflow_run_id,
            trace_id,
            intake,
            script,
            scenes,
        )
        return self._render_workflow.execute(contract)


def _required_script(payload: object) -> str:
    if not isinstance(payload, dict) or not isinstance(payload.get("script"), str):
        raise ValueError("execution context is missing scripted output")
    return payload["script"]


def _required_scenes(payload: object) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("scenes"), list):
        raise ValueError("execution context is missing storyboard output")
    scenes = payload["scenes"]
    if not all(isinstance(scene, dict) for scene in scenes):
        raise ValueError("storyboard scenes must be objects")
    return scenes
