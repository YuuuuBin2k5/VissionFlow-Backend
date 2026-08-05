"""
Unified Video Metadata Service (Facade Pattern)
==============================================
Design Pattern: Facade Pattern

Single point of access for generating multi-language video titles,
SEO descriptions, pinned comments, and hashtags across all VisionFlow
pipelines (Video Short and AI Dubbing).
"""

from __future__ import annotations

from typing import Any

from worker.services.video_metadata_strategy import (
    MetadataStrategyFactory,
    VideoMetadataResult,
)


class UnifiedVideoMetadataService:
    """Facade service for unified metadata and title generation."""

    def __init__(self, target_language: str = "vi", voice_code: str = "") -> None:
        self.target_language = target_language
        self.voice_code = voice_code
        self.strategy = MetadataStrategyFactory.get_strategy(target_language, voice_code)

    def generate_seo_metadata(
        self,
        transcript: str,
        original_title: str | None = None,
    ) -> VideoMetadataResult:
        """Generate structured title, description (caption SEO), pinned comment & hashtags."""
        return self.strategy.generate(transcript, original_title)

    def sanitize_and_translate_title(self, raw_title: str | None) -> str:
        """Quickly translate foreign/Chinese titles into the target language."""
        if not raw_title:
            return "Video Lồng Tiếng Mới" if self.target_language == "vi" else "New Dubbed Video"
        return self.strategy.translate_raw_title(raw_title)


def process_video_metadata(
    transcript: str,
    original_title: str | None = None,
    target_language: str = "vi",
    voice_code: str = "",
) -> dict[str, Any]:
    """Helper function to obtain a metadata dictionary directly."""
    service = UnifiedVideoMetadataService(target_language=target_language, voice_code=voice_code)
    result = service.generate_seo_metadata(transcript, original_title)
    return result.to_dict()
