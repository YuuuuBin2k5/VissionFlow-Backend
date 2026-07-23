"""FastAPI Router for AI Video Generation, Provider Health, and Circuit Breaker Reset."""

from typing import Dict, Optional, List
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.domain.ai_video_router import AIVideoRouterEngine
from app.application.generate_ai_video_scene import (
    GenerateAIVideoScene,
    GenerateSceneVideoCommand,
)

router = APIRouter(prefix="/api/v1/ai-video", tags=["AI Video Generation"])

# Shared singleton router engine in memory
_router_engine = AIVideoRouterEngine(lockout_minutes=60)


def get_router_engine() -> AIVideoRouterEngine:
    return _router_engine


class RenderSceneRequest(BaseModel):
    prompt: str = Field(..., min_length=3, max_length=2000)
    duration_seconds: int = Field(default=5, ge=1, le=30)
    aspect_ratio: str = Field(default="9:16", max_length=10)
    custom_category: Optional[str] = Field(default=None, max_length=32)
    custom_api_keys: Optional[Dict[str, str]] = Field(default=None)


class RenderSceneResponse(BaseModel):
    video_url: str
    provider_used: str
    category_used: str
    fallback_occurred: bool
    fallback_history: List[str]


class ResetProviderRequest(BaseModel):
    provider_name: str = Field(..., min_length=2, max_length=32)


@router.post("/render-scene", response_model=RenderSceneResponse)
async def render_scene_video(
    request: RenderSceneRequest,
    engine: AIVideoRouterEngine = Depends(get_router_engine),
) -> RenderSceneResponse:
    """Generate an AI video scene clip with automatic provider routing and circuit-breaker resilience."""
    use_case = GenerateAIVideoScene(engine)
    result = await use_case.execute(
        GenerateSceneVideoCommand(
            prompt=request.prompt,
            duration_seconds=request.duration_seconds,
            aspect_ratio=request.aspect_ratio,
            custom_category=request.custom_category,
            custom_api_keys=request.custom_api_keys,
        )
    )
    return RenderSceneResponse(
        video_url=result.video_url,
        provider_used=result.provider_used,
        category_used=result.category_used,
        fallback_occurred=result.fallback_occurred,
        fallback_history=result.fallback_history,
    )


@router.get("/providers/health")
def get_providers_health(
    engine: AIVideoRouterEngine = Depends(get_router_engine),
) -> Dict[str, dict]:
    """Get real-time health, failures, and circuit-breaker status of all registered AI Video providers."""
    return engine.get_all_health_statuses()


@router.post("/providers/reset")
def reset_provider_health(
    request: ResetProviderRequest,
    engine: AIVideoRouterEngine = Depends(get_router_engine),
) -> dict:
    """Manually reset circuit breaker for a provider after topping up API credits."""
    engine.reset_provider(request.provider_name)
    return {"message": f"Successfully reset provider '{request.provider_name}'", "status": "ok"}
