"""Shared narration core for render and Voice Lab; no platform dependencies."""

from .contracts import VoiceProfile, VoiceRequest, resolve_delivery, resolve_profile
from .service import VoiceService

__all__ = ['VoiceProfile', 'VoiceRequest', 'VoiceService', 'resolve_delivery', 'resolve_profile']
