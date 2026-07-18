"""VisionFlow V1 Brief -> Script -> Storyboard intelligence use case."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class WorkflowGateway(Protocol):
    def advance_workflow(self, workflow_run_id: str, expected_state: str, target_state: str, output_payload: dict[str, Any], *, trace_id: str | None = None) -> dict[str, Any]: ...


class ShortFormGenerator(Protocol):
    def generate(self, intake: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class VisionFlowIntelligenceResult:
    workflow_run_id: str
    script: str
    scene_count: int


class LegacyLlmShortFormGenerator:
    """Anti-corruption adapter around the existing Gemini/LLM implementation."""

    def generate(self, intake: dict[str, Any]) -> dict[str, Any]:
        input_payload = intake.get("input_payload", {})
        if not isinstance(input_payload, dict):
            raise ValueError("intake input_payload must be an object")

        # Priority 1: use locked creative document from Control Plane
        creative_document = intake.get("creative_document")
        if isinstance(creative_document, dict) and creative_document.get("state") == "locked":
            script = creative_document.get("script")
            scenes = creative_document.get("scenes")
            if isinstance(script, str) and isinstance(scenes, list):
                return {"full_voice_script": script, "scenes_layout_json": scenes}
            raise ValueError(
                f"Creative document is locked but missing script/scenes. "
                f"script={type(script)}, scenes={type(scenes)}"
            )

        # Priority 2: use creative_draft from input_payload
        creative_draft = input_payload.get("creative_draft")
        if isinstance(creative_draft, dict) and isinstance(creative_draft.get("script"), str) and isinstance(creative_draft.get("scenes"), list):
            return {"full_voice_script": creative_draft["script"], "scenes_layout_json": creative_draft["scenes"]}

        # Fallback: call LLM (only when no pre-approved content exists)
        from worker.services.llm_service import LLMService
        return LLMService().generate_video_details(
            day_number=1,
            topic=str(intake["brief"]),
            title_idea=str(intake["title"]),
            audience=str(input_payload.get("target_audience", "short-form viewers")),
            music_mood=str(input_payload.get("tone", "educational")),
            content_category=str(input_payload.get("visual_preset", "")),
            video_language=str(input_payload.get("target_language", "vi")),
        )


class VisionFlowShortFormIntelligence:
    def __init__(self, gateway: WorkflowGateway, generator: ShortFormGenerator) -> None:
        self._gateway = gateway
        self._generator = generator

    def execute(self, workflow_run_id: str, intake: dict[str, Any], *, event_id: str, trace_id: str | None) -> VisionFlowIntelligenceResult:
        planning = self._gateway.advance_workflow(
            workflow_run_id, "QUEUED", "PLANNING", {"event_id": event_id, "worker": "visionflow-intelligence"}, trace_id=trace_id,
        )
        if not planning.get("changed", False):
            raise RuntimeError("workflow was already claimed; refusing to repeat intelligence generation")
        generated = self._generator.generate(intake)
        script, scenes = _validate_generated(generated)
        self._gateway.advance_workflow(
            workflow_run_id, "PLANNING", "SCRIPTED", {"script": script, "generator": "visionflow-llm"}, trace_id=trace_id,
        )
        self._gateway.advance_workflow(
            workflow_run_id, "SCRIPTED", "STORYBOARDED", {"scenes": scenes, "scene_count": len(scenes)}, trace_id=trace_id,
        )
        return VisionFlowIntelligenceResult(workflow_run_id, script, len(scenes))


def _validate_generated(generated: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    script = generated.get("full_voice_script")
    scenes = generated.get("scenes_layout_json")
    if not isinstance(script, str) or len(script.strip()) < 40:
        raise ValueError("generator returned an invalid short-form script")
    if not isinstance(scenes, list) or not 3 <= len(scenes) <= 20:
        raise ValueError("generator must return between 3 and 20 storyboard scenes")
    normalized: list[dict[str, Any]] = []
    for index, scene in enumerate(scenes, start=1):
        if not isinstance(scene, dict):
            raise ValueError(f"storyboard scene {index} is invalid")
        visual = str(scene.get("visual_search_keywords") or scene.get("visual_prompt") or "").strip()
        if not visual:
            raise ValueError(f"storyboard scene {index} is missing visual_search_keywords")
        scene_id = str(scene.get("scene_id") or scene.get("id") or f"scene-{index}")
        normalized.append({**scene, "scene_id": scene_id, "visual_search_keywords": visual, "duration": int(scene.get("duration") or scene.get("duration_seconds") or 5)})
    return script.strip(), normalized
