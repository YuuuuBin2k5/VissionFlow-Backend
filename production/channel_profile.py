"""
ChannelProfile Models & Production Defaults for VisionFlow (Phase 7 - Section 21).
Provides channel-level production configurations (voice, tone, duration, hook, caption, music level, permissions).
Synchronized with CreativeAgentCenter.tsx channel registry.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger("visionflow.production.channel_profile")


class ChannelProfile(BaseModel):
    id: str
    channel_name: str
    handle: str
    language: str = "vi"
    tagline: str = ""
    about_blurb: str = ""
    cta: str = ""
    copyright: str = ""
    hashtags: List[str] = Field(default_factory=list)
    title_style: str = "nostalgic"
    title_prefix: Optional[str] = None
    voice_code: str = "vi-VN-NamMinhNeural"
    voice_rate: float = 1.0
    target_duration_seconds: int = 45
    archetype_preferences: List[str] = Field(default_factory=lambda: ["DOCUMENTARY", "COMMENTARY"])
    hook_style: str = "question_hook"
    caption_style: str = "hormozi_yellow"
    music_level: float = 0.15
    visual_pacing: str = "fast"
    source_preference: str = "USER_THEN_SCENE"
    stock_permission: bool = True
    generated_media_permission: bool = True
    auto_publish_enabled: bool = False  # Invariant: Safety default remains False


BUILTIN_CHANNEL_PROFILES: List[ChannelProfile] = [
    ChannelProfile(
        id="goc_chiem_nghiem_yuubin",
        channel_name="Góc Chiêm Nghiệm | YuuBin",
        handle="GócChiêmNghiệm||YuuuBin",
        language="vi",
        tagline="📜 Có những câu chuyện trôi qua theo năm tháng, nhưng bài học để lại thì trường tồn cùng thời gian...",
        about_blurb="Chào mừng bạn đến với Góc Chiêm Nghiệm | YuuBin — nơi dừng chân cho những tâm hồn yêu thích sự chiêm nghiệm, hoài niệm và tìm kiếm những bài học giá trị giữa cuộc sống hối hả.",
        cta="🕯️ LỜI NHẮN NGHỆ THUẬT: Nếu câu chuyện hôm nay chạm đến trái tim bạn, hãy để lại lời bình luận nhé.",
        copyright="© Bản quyền thuộc về kênh Góc Chiêm Nghiệm | YuuBin ☞ Vui lòng không reup dưới mọi hình thức.",
        hashtags=["#BaiHocCuocSong", "#ChuyenThoiXua", "#KinhNghiemSong", "#KeChuyen", "#Shorts"],
        title_style="nostalgic",
        title_prefix="Lời Dặn Cổ Xưa",
        voice_code="vi-VN-NamMinhNeural",
        target_duration_seconds=45,
        archetype_preferences=["DOCUMENTARY", "COMMENTARY"],
        hook_style="story_mystery",
        caption_style="cinematic_yellow",
        music_level=0.15,
        visual_pacing="reflective",
        auto_publish_enabled=False,
    ),
    ChannelProfile(
        id="asinmochii_boni",
        channel_name="AsinMochii💕Boni",
        handle="@AsinMochiiBoni",
        language="en",
        tagline="📜 Some stories fade with time, but the lessons stay forever...",
        about_blurb="Welcome to AsinMochii💕Boni — a sanctuary for reflective souls searching for timeless ancient wisdom and real-life lessons.",
        cta="🕯️ ARTISTIC NOTE: If today's story touched your heart, leave a comment to join our community.",
        copyright="© Copyright by AsinMochii💕Boni channel ☞ Do not reupload in any form.",
        hashtags=["#LifeLessons", "#AncientWisdom", "#Storytelling", "#Shorts"],
        title_style="nostalgic",
        title_prefix="Ancient Lesson",
        voice_code="en-US-ChristopherNeural",
        target_duration_seconds=45,
        archetype_preferences=["EDUCATIONAL", "COMMENTARY"],
        hook_style="philosophical_provocation",
        caption_style="hormozi_bold",
        music_level=0.12,
        visual_pacing="steady",
        auto_publish_enabled=False,
    ),
]


class ChannelProfileRegistry:
    """
    In-memory registry and resolver for tenant channel profiles.
    """

    def __init__(self):
        self._profiles: Dict[str, ChannelProfile] = {p.id: p for p in BUILTIN_CHANNEL_PROFILES}

    def get_profile(self, profile_id: Optional[str]) -> ChannelProfile:
        if profile_id and profile_id in self._profiles:
            return self._profiles[profile_id]
        return self._profiles["goc_chiem_nghiem_yuubin"]

    def list_profiles(self) -> List[ChannelProfile]:
        return list(self._profiles.values())

    def register_profile(self, profile: ChannelProfile) -> None:
        self._profiles[profile.id] = profile


channel_profile_registry = ChannelProfileRegistry()
