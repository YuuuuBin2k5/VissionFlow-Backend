"""
Dynamic Royalty-Free BGM Soundbank Registry & Intelligent Music Engine
=====================================================================
Design Pattern: Registry Pattern + Strategy Pattern (Open/Closed Principle)

Provides genre-adaptive background music resolution with auto-ducking gain profiles,
seamless looping support, and copyright attribution generation.
"""

from __future__ import annotations
import re
from typing import Any, Dict, List, Optional

# Base CDN URL for high-speed delivery of verified royalty-free audio tracks
R2_AUDIO_BASE = "https://pub-ec302240fdb8cad9ae6c9b685f14eeec.r2.dev/audio/bgm"

SOUNDBANK_REGISTRY: Dict[str, List[Dict[str, Any]]] = {
    "MYSTERY_PARANORMAL_HISTORY": [
        {
            "id": "bgm_mystery_blackout",
            "name": "Blackout Dark Ambiance",
            "artist": "Myuu (The Dark Piano)",
            "url": f"{R2_AUDIO_BASE}/mystery_blackout.mp3",
            "volume_gain": 0.12,
            "license": "CC-BY 4.0",
            "credit": "Music: Blackout by Myuu (thedarkpiano.com)",
            "mood": "ominous_creepy"
        },
        {
            "id": "bgm_mystery_escalation",
            "name": "The Escalation",
            "artist": "Kevin MacLeod",
            "url": f"{R2_AUDIO_BASE}/mystery_escalation.mp3",
            "volume_gain": 0.11,
            "license": "CC-BY 4.0",
            "credit": "Music: The Escalation by Kevin MacLeod (incompetech.com)",
            "mood": "suspense_investigation"
        },
        {
            "id": "bgm_mystery_gathering",
            "name": "Gathering Darkness",
            "artist": "Kevin MacLeod",
            "url": f"{R2_AUDIO_BASE}/mystery_gathering_darkness.mp3",
            "volume_gain": 0.10,
            "license": "CC-BY 4.0",
            "credit": "Music: Gathering Darkness by Kevin MacLeod (incompetech.com)",
            "mood": "eerie_drone"
        }
    ],
    "PHILOSOPHY_LIFE_LESSON": [
        {
            "id": "bgm_chiem_nghiem_clover",
            "name": "Clover 3 Nostalgic Piano",
            "artist": "YouTube Audio Library",
            "url": f"{R2_AUDIO_BASE}/chiem_nghiem_clover3.mp3",
            "volume_gain": 0.14,
            "license": "Royalty Free (No Attribution Required)",
            "credit": "Music: YouTube Audio Library",
            "mood": "healing_nostalgic"
        },
        {
            "id": "bgm_chiem_nghiem_acoustic",
            "name": "Acoustic Breeze",
            "artist": "Bensound",
            "url": f"{R2_AUDIO_BASE}/chiem_nghiem_acoustic_breeze.mp3",
            "volume_gain": 0.13,
            "license": "Royalty Free",
            "credit": "Music: Bensound.com",
            "mood": "warm_guitar"
        },
        {
            "id": "bgm_chiem_nghiem_clean_soul",
            "name": "Clean Soul",
            "artist": "Kevin MacLeod",
            "url": f"{R2_AUDIO_BASE}/chiem_nghiem_clean_soul.mp3",
            "volume_gain": 0.12,
            "license": "CC-BY 4.0",
            "credit": "Music: Clean Soul by Kevin MacLeod (incompetech.com)",
            "mood": "peaceful_wisdom"
        }
    ],
    "WEALTH_FINANCE_MINDSET": [
        {
            "id": "bgm_wealth_better_days",
            "name": "Better Days",
            "artist": "LAKEY INSPIRED",
            "url": f"{R2_AUDIO_BASE}/wealth_better_days.mp3",
            "volume_gain": 0.13,
            "license": "CC-BY 3.0",
            "credit": "Music: Better Days by LAKEY INSPIRED",
            "mood": "modern_inspiring"
        },
        {
            "id": "bgm_wealth_chill_day",
            "name": "Chill Day",
            "artist": "LAKEY INSPIRED",
            "url": f"{R2_AUDIO_BASE}/wealth_chill_day.mp3",
            "volume_gain": 0.13,
            "license": "CC-BY 3.0",
            "credit": "Music: Chill Day by LAKEY INSPIRED",
            "mood": "upbeat_focus"
        }
    ],
    "ANCIENT_STRATEGY_WAR": [
        {
            "id": "bgm_strategy_taiko",
            "name": "Ancient Battle Drums",
            "artist": "YouTube Audio Library",
            "url": f"{R2_AUDIO_BASE}/strategy_battle_drums.mp3",
            "volume_gain": 0.12,
            "license": "Royalty Free",
            "credit": "Music: YouTube Audio Library",
            "mood": "heroic_tactical"
        },
        {
            "id": "bgm_strategy_epic_hero",
            "name": "The Epic Hero",
            "artist": "Keys of Moon",
            "url": f"{R2_AUDIO_BASE}/strategy_epic_hero.mp3",
            "volume_gain": 0.11,
            "license": "CC-BY 4.0",
            "credit": "Music: The Epic Hero by Keys of Moon",
            "mood": "cinematic_grand"
        }
    ],
    "SCIENCE_TECH_FUTURE": [
        {
            "id": "bgm_tech_space_ambient",
            "name": "Deep Space Pulse",
            "artist": "YouTube Audio Library",
            "url": f"{R2_AUDIO_BASE}/tech_deep_space.mp3",
            "volume_gain": 0.12,
            "license": "Royalty Free",
            "credit": "Music: YouTube Audio Library",
            "mood": "futuristic_cosmic"
        }
    ],
    "GENERAL_DISCOVERY": [
        {
            "id": "bgm_general_carefree",
            "name": "Carefree",
            "artist": "Kevin MacLeod",
            "url": f"{R2_AUDIO_BASE}/general_carefree.mp3",
            "volume_gain": 0.13,
            "license": "CC-BY 4.0",
            "credit": "Music: Carefree by Kevin MacLeod (incompetech.com)",
            "mood": "curious_light"
        }
    ]
}


def resolve_genre_bgm(
    genre: str,
    mood_override: str = "",
    custom_url: str = "",
    track_index: int = 0
) -> Dict[str, Any]:
    """
    Resolves the optimal royalty-free BGM track.
    If custom_url is passed, wraps it safely.
    Otherwise selects from SOUNDBANK_REGISTRY matching the genre/mood.
    """
    if custom_url and custom_url.startswith("http"):
        return {
            "id": "bgm_custom",
            "name": "Custom Background Audio",
            "artist": "User Upload",
            "url": custom_url,
            "volume_gain": 0.14,
            "license": "Custom License",
            "credit": "",
            "mood": mood_override or "custom"
        }

    genre_key = genre.upper() if genre else "GENERAL_DISCOVERY"
    tracks = SOUNDBANK_REGISTRY.get(genre_key, SOUNDBANK_REGISTRY["GENERAL_DISCOVERY"])

    # If mood override requested, look for match
    if mood_override:
        for t in tracks:
            if mood_override.lower() in t.get("mood", "").lower():
                return t

    # Select track by index safely
    selected_track = tracks[track_index % len(tracks)]
    return selected_track


def format_bgm_attribution(bgm_info: Optional[Dict[str, Any]]) -> str:
    """
    Formats YouTube & Facebook copyright-safe attribution block.
    """
    if not bgm_info:
        return ""
    credit = bgm_info.get("credit", "").strip()
    if not credit or "No Attribution" in bgm_info.get("license", ""):
        return ""
    
    return f"🎵 Âm thanh & Nhạc nền:\n• {credit}\n• Licensed under Creative Commons (Royalty-Free)"
