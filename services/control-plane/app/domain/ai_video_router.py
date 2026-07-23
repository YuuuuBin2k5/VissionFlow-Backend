"""Domain model for AI Video Routing, Scene Prompt Classification, and Circuit Breaker."""

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
import re
from typing import Dict, List, Optional


class ProviderHealthStatus(str, Enum):
    ACTIVE = "active"
    DEGRADED = "degraded"
    OUT_OF_QUOTA = "out_of_quota"  # Triggered by 402 or 429
    DISABLED = "disabled"


class SceneCategory(str, Enum):
    HUMAN_ACTION = "human_action"       # Kling AI
    CINEMATIC_LANDSCAPE = "cinematic"  # Runway Gen-3
    FAST_MOTION = "fast_motion"        # Luma Dream Machine
    ANIMATION_3D = "animation_3d"      # MiniMax / Pika
    GENERAL = "general"                # Wan 2.1 (Fal.ai / Replicate)


@dataclass
class ProviderState:
    name: str
    status: ProviderHealthStatus = ProviderHealthStatus.ACTIVE
    consecutive_failures: int = 0
    disabled_until: Optional[datetime] = None
    last_error: Optional[str] = None


class AIVideoRouterEngine:
    """Domain router that manages provider health states, circuit breaker, and scene prompt classification."""

    def __init__(self, lockout_minutes: int = 60):
        self.lockout_minutes = lockout_minutes
        self._provider_states: Dict[str, ProviderState] = {
            "kling": ProviderState(name="kling"),
            "runway": ProviderState(name="runway"),
            "luma": ProviderState(name="luma"),
            "fal": ProviderState(name="fal"),
            "replicate": ProviderState(name="replicate"),
            "minimax": ProviderState(name="minimax"),
            "ken_burns_local": ProviderState(name="ken_burns_local"),
        }

    def classify_scene_prompt(self, prompt: str) -> SceneCategory:
        """Classify prompt into scene categories using keyword matching."""
        lower_prompt = prompt.lower()

        # Animation & 3D -> MiniMax / Pika
        animation_keywords = [
            "3d", "anime", "cartoon", "pixar", "disney", "cute", "toy",
            "fantasy", "magic", "hoat hinh"
        ]
        if any(re.search(r'\b' + re.escape(kw) + r'\b', lower_prompt) for kw in animation_keywords):
            return SceneCategory.ANIMATION_3D

        # Fast Motion & Physics -> Luma Dream Machine
        motion_keywords = [
            "car", "speed", "racing", "chase", "explosion", "flying", "superhero",
            "fast", "drift", "fire", "smoke", "lao nhanh", "toc do"
        ]
        if any(re.search(r'\b' + re.escape(kw) + r'\b', lower_prompt) for kw in motion_keywords):
            return SceneCategory.FAST_MOTION

        # Human & Action keywords -> Kling AI
        human_keywords = [
            "man", "woman", "person", "people", "actor", "running", "walking",
            "talking", "fighting", "character", "face", "portrait", "con nguoi", "nguoi"
        ]
        if any(re.search(r'\b' + re.escape(kw) + r'\b', lower_prompt) for kw in human_keywords):
            return SceneCategory.HUMAN_ACTION

        # Cinematic & Landscape keywords -> Runway Gen-3
        cinematic_keywords = [
            "cinematic", "landscape", "mountain", "ocean", "river", "forest",
            "aerial", "drone", "sunset", "sunrise", "nature", "scenery", "phong canh"
        ]
        if any(re.search(r'\b' + re.escape(kw) + r'\b', lower_prompt) for kw in cinematic_keywords):
            return SceneCategory.CINEMATIC_LANDSCAPE

        return SceneCategory.GENERAL

    def get_fallback_chain(self, category: SceneCategory) -> List[str]:
        """Return ordered provider chain based on scene category."""
        chains = {
            SceneCategory.HUMAN_ACTION: ["kling", "runway", "fal", "replicate", "minimax", "ken_burns_local"],
            SceneCategory.CINEMATIC_LANDSCAPE: ["runway", "luma", "fal", "replicate", "kling", "ken_burns_local"],
            SceneCategory.FAST_MOTION: ["luma", "kling", "runway", "fal", "replicate", "ken_burns_local"],
            SceneCategory.ANIMATION_3D: ["minimax", "fal", "replicate", "kling", "ken_burns_local"],
            SceneCategory.GENERAL: ["fal", "replicate", "wan21", "kling", "luma", "runway", "ken_burns_local"],
        }
        return chains.get(category, ["fal", "replicate", "ken_burns_local"])

    def is_provider_available(self, provider_name: str) -> bool:
        """Check if provider is available and not currently locked out."""
        state = self._provider_states.get(provider_name)
        if not state:
            return True

        if state.status == ProviderHealthStatus.DISABLED:
            return False

        if state.status == ProviderHealthStatus.OUT_OF_QUOTA:
            if state.disabled_until and datetime.now(timezone.utc) < state.disabled_until:
                return False
            # Lockout period expired -> Reset to degraded/testing mode
            state.status = ProviderHealthStatus.ACTIVE
            state.consecutive_failures = 0
            state.disabled_until = None

        return True

    def record_success(self, provider_name: str) -> None:
        """Record successful call and reset failure counters."""
        state = self._provider_states.get(provider_name)
        if state:
            state.status = ProviderHealthStatus.ACTIVE
            state.consecutive_failures = 0
            state.last_error = None

    def record_failure(self, provider_name: str, error_code: str, is_quota_error: bool = False) -> None:
        """Record failure and trip circuit breaker if out of quota (402/429) or max failures reached."""
        state = self._provider_states.get(provider_name)
        if not state:
            state = ProviderState(name=provider_name)
            self._provider_states[provider_name] = state

        state.consecutive_failures += 1
        state.last_error = error_code

        # Immediate lockout on 402 Payment Required or 429 Quota Exceeded
        if is_quota_error or error_code in ("402", "429", "INSUFFICIENT_CREDITS", "QUOTA_EXCEEDED"):
            state.status = ProviderHealthStatus.OUT_OF_QUOTA
            state.disabled_until = datetime.now(timezone.utc) + timedelta(minutes=self.lockout_minutes)
        elif state.consecutive_failures >= 3:
            state.status = ProviderHealthStatus.DEGRADED

    def reset_provider(self, provider_name: str) -> None:
        """Manually reset a provider's health status (e.g. after user tops up API keys)."""
        state = self._provider_states.get(provider_name)
        if state:
            state.status = ProviderHealthStatus.ACTIVE
            state.consecutive_failures = 0
            state.disabled_until = None
            state.last_error = None

    def get_all_health_statuses(self) -> Dict[str, dict]:
        """Return diagnostic health dict for all registered providers."""
        now = datetime.now(timezone.utc)
        result = {}
        for name, state in self._provider_states.items():
            is_locked = bool(state.disabled_until and now < state.disabled_until)
            result[name] = {
                "name": name,
                "status": "out_of_quota" if is_locked else state.status.value,
                "consecutive_failures": state.consecutive_failures,
                "disabled_until": state.disabled_until.isoformat() if state.disabled_until else None,
                "last_error": state.last_error,
            }
        return result
