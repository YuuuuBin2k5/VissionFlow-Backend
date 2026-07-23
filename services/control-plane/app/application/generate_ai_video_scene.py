"""Application Use Case for Generating AI Video Scenes with Resilience & Fallbacks."""

from dataclasses import dataclass
from typing import Dict, Optional, List
import logging

from app.domain.ai_video_router import AIVideoRouterEngine, SceneCategory
from app.infrastructure.ai_video_providers import (
    BaseAIVideoProvider,
    FalAIVideoProvider,
    ReplicateVideoProvider,
    KlingAIVideoProvider,
    RunwayGen3VideoProvider,
    LumaDreamVideoProvider,
    MiniMaxVideoProvider,
    KenBurnsImageFallbackProvider,
    ProviderQuotaError,
    ProviderExecutionError,
)

logger = logging.getLogger(__name__)


@dataclass
class GenerateSceneVideoCommand:
    prompt: str
    duration_seconds: int = 5
    aspect_ratio: str = "9:16"
    custom_category: Optional[str] = None
    custom_api_keys: Optional[Dict[str, str]] = None


@dataclass
class GenerateSceneVideoResult:
    video_url: str
    provider_used: str
    category_used: str
    fallback_occurred: bool
    fallback_history: List[str]


class GenerateAIVideoScene:
    """Application Use Case coordinating resilient multi-provider AI video rendering."""

    def __init__(self, router_engine: AIVideoRouterEngine):
        self.router = router_engine
        self.providers: Dict[str, BaseAIVideoProvider] = {
            "fal": FalAIVideoProvider(),
            "replicate": ReplicateVideoProvider(),
            "kling": KlingAIVideoProvider(),
            "runway": RunwayGen3VideoProvider(),
            "luma": LumaDreamVideoProvider(),
            "minimax": MiniMaxVideoProvider(),
            "ken_burns_local": KenBurnsImageFallbackProvider(),
        }

    async def execute(self, command: GenerateSceneVideoCommand) -> GenerateSceneVideoResult:
        # 1. Determine Scene Category
        if command.custom_category:
            try:
                category = SceneCategory(command.custom_category.lower())
            except ValueError:
                category = self.router.classify_scene_prompt(command.prompt)
        else:
            category = self.router.classify_scene_prompt(command.prompt)

        # 2. Get ordered fallback provider chain
        provider_chain = self.router.get_fallback_chain(category)
        keys_dict = command.custom_api_keys or {}

        fallback_history: List[str] = []
        fallback_occurred = False

        # 3. Iterate through provider chain
        for provider_name in provider_chain:
            # Skip if circuit breaker tripped
            if not self.router.is_provider_available(provider_name):
                fallback_history.append(f"{provider_name}: skipped (circuit_breaker_active)")
                fallback_occurred = True
                continue

            provider_adapter = self.providers.get(provider_name)
            if not provider_adapter:
                continue

            api_key = keys_dict.get(provider_name)

            try:
                video_url = await provider_adapter.generate_video(
                    prompt=command.prompt,
                    duration_seconds=command.duration_seconds,
                    aspect_ratio=command.aspect_ratio,
                    api_key=api_key,
                )
                self.router.record_success(provider_name)
                return GenerateSceneVideoResult(
                    video_url=video_url,
                    provider_used=provider_name,
                    category_used=category.value,
                    fallback_occurred=fallback_occurred,
                    fallback_history=fallback_history,
                )
            except ProviderQuotaError as err:
                logger.warning("Provider %s out of quota / 402: %s", provider_name, err)
                self.router.record_failure(provider_name, error_code="402", is_quota_error=True)
                fallback_history.append(f"{provider_name}: failed_quota ({str(err)})")
                fallback_occurred = True
            except ProviderExecutionError as err:
                logger.warning("Provider %s execution failed: %s", provider_name, err)
                self.router.record_failure(provider_name, error_code="500", is_quota_error=False)
                fallback_history.append(f"{provider_name}: failed_exec ({str(err)})")
                fallback_occurred = True
            except Exception as err:
                logger.error("Provider %s unhandled exception: %s", provider_name, err)
                self.router.record_failure(provider_name, error_code="500", is_quota_error=False)
                fallback_history.append(f"{provider_name}: error ({str(err)})")
                fallback_occurred = True

        # 4. Final Safety Net: Local Ken Burns Motion Fallback (Guaranteed to succeed)
        ken_burns = self.providers["ken_burns_local"]
        video_url = await ken_burns.generate_video(command.prompt, command.duration_seconds, command.aspect_ratio)
        return GenerateSceneVideoResult(
            video_url=video_url,
            provider_used="ken_burns_local",
            category_used=category.value,
            fallback_occurred=True,
            fallback_history=fallback_history,
        )
