"""Render orchestration boundary; adapters own asset and media implementation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from worker.domain.visionflow_render_contract import VisionFlowRenderContract


@dataclass(frozen=True)
class PreparedAssets:
    asset_keys: tuple[str, ...]


@dataclass(frozen=True)
class RenderedArtifact:
    object_key: str
    content_type: str
    byte_size: int
    checksum_sha256: str


class AssetPreparer(Protocol):
    def prepare(self, contract: VisionFlowRenderContract) -> PreparedAssets: ...


class VideoRenderer(Protocol):
    def render(self, contract: VisionFlowRenderContract, assets: PreparedAssets) -> RenderedArtifact: ...


class WorkflowGateway(Protocol):
    def advance_workflow(self, workflow_run_id: str, expected_state: str, target_state: str, output_payload: dict, *, trace_id: str | None = None) -> dict: ...


class VisionFlowRenderWorkflow:
    def __init__(self, gateway: WorkflowGateway, asset_preparer: AssetPreparer, renderer: VideoRenderer) -> None:
        self._gateway = gateway
        self._asset_preparer = asset_preparer
        self._renderer = renderer

    def execute(self, contract: VisionFlowRenderContract) -> RenderedArtifact:
        assets = self._asset_preparer.prepare(contract)
        self._gateway.advance_workflow(
            contract.workflow_run_id, "STORYBOARDED", "ASSETS_READY",
            {"asset_keys": list(assets.asset_keys), "workspace_key": contract.workspace_key}, trace_id=contract.trace_id,
        )
        self._gateway.advance_workflow(
            contract.workflow_run_id, "ASSETS_READY", "RENDERING",
            {"workspace_key": contract.workspace_key}, trace_id=contract.trace_id,
        )
        artifact = self._renderer.render(contract, assets)
        self._gateway.advance_workflow(
            contract.workflow_run_id, "RENDERING", "QA_PENDING",
            {"object_key": artifact.object_key, "content_type": artifact.content_type, "byte_size": artifact.byte_size, "checksum_sha256": artifact.checksum_sha256}, trace_id=contract.trace_id,
        )
        return artifact
