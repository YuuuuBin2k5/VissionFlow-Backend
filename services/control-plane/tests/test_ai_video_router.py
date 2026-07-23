"""Comprehensive Pytest Unit Tests for AI Video Router, Circuit Breaker, and Fallbacks."""

import pytest
import pytest_asyncio
from app.domain.ai_video_router import AIVideoRouterEngine, SceneCategory, ProviderHealthStatus
from app.application.generate_ai_video_scene import (
    GenerateAIVideoScene,
    GenerateSceneVideoCommand,
)


@pytest.fixture
def router_engine():
    """Fresh router engine for each test."""
    return AIVideoRouterEngine(lockout_minutes=60)


def test_scene_prompt_classification(router_engine):
    """Test keyword-based scene prompt classifier."""
    assert router_engine.classify_scene_prompt("A man running in the rain") == SceneCategory.HUMAN_ACTION
    assert router_engine.classify_scene_prompt("Cinematic mountain drone shot at sunset") == SceneCategory.CINEMATIC_LANDSCAPE
    assert router_engine.classify_scene_prompt("Superhero flying fast car chase explosion") == SceneCategory.FAST_MOTION
    assert router_engine.classify_scene_prompt("Cute 3d anime character playing with toy") == SceneCategory.ANIMATION_3D
    assert router_engine.classify_scene_prompt("Abstract neon glowing background particles") == SceneCategory.GENERAL


@pytest.mark.asyncio
async def test_successful_video_generation(router_engine):
    """Test successful scene video generation using Fal.ai or Kling."""
    use_case = GenerateAIVideoScene(router_engine)
    cmd = GenerateSceneVideoCommand(
        prompt="Cinematic drone landscape",
        duration_seconds=5,
        custom_api_keys={"runway": "mock_runway_key"}
    )
    result = await use_case.execute(cmd)

    assert result.video_url.startswith("https://cdn.visionflow.ai/generated/")
    assert result.provider_used == "runway"
    assert result.category_used == SceneCategory.CINEMATIC_LANDSCAPE.value
    assert result.fallback_occurred is False


@pytest.mark.asyncio
async def test_circuit_breaker_tripping_on_402(router_engine):
    """Test circuit breaker tripping when provider returns 402 Payment Required."""
    use_case = GenerateAIVideoScene(router_engine)

    # Kling prompt containing FAIL_KLING_402 to trigger quota error only for Kling
    cmd = GenerateSceneVideoCommand(
        prompt="A man running FAIL_KLING_402",
        custom_api_keys={"kling": "mock_kling_key", "runway": "mock_runway_key"}
    )
    result = await use_case.execute(cmd)

    # Kling should fail with 402 and fallback to Runway
    assert result.fallback_occurred is True
    assert result.provider_used == "runway"
    assert any("kling: failed_quota" in h for h in result.fallback_history)

    # Verify Kling state is marked OUT_OF_QUOTA
    kling_health = router_engine.get_all_health_statuses()["kling"]
    assert kling_health["status"] == "out_of_quota"


@pytest.mark.asyncio
async def test_ultimate_fallback_to_ken_burns_local(router_engine):
    """Test 100% zero-failure guarantee fallback to Ken Burns local motion zoom when all AI APIs fail."""
    use_case = GenerateAIVideoScene(router_engine)

    # All API keys missing / 402 errors for all providers
    cmd = GenerateSceneVideoCommand(
        prompt="A man FAIL_402",
        custom_api_keys={} # Empty keys force 402 missing key error for all cloud providers
    )
    result = await use_case.execute(cmd)

    # Must fallback to ken_burns_local without crashing
    assert result.provider_used == "ken_burns_local"
    assert result.video_url.startswith("https://cdn.visionflow.ai/fallback/ken_burns_motion_")
    assert result.fallback_occurred is True


def test_reset_provider_health(router_engine):
    """Test manual reset of provider circuit breaker."""
    router_engine.record_failure("kling", error_code="402", is_quota_error=True)
    assert router_engine.is_provider_available("kling") is False

    # Reset
    router_engine.reset_provider("kling")
    assert router_engine.is_provider_available("kling") is True
    assert router_engine.get_all_health_statuses()["kling"]["status"] == "active"
