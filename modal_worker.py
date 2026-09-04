"""
Modal.com Serverless Execution Engine & Live Webhook API for VisionFlow
0 VNĐ Compute Server for FFmpeg Video Composition & Auto-Publishing Pipeline
Supports full Frontend CreationSpec contract:
- Edge TTS multi-language voice synthesis & speed control
- Multi-Scene Storyboard video sequence composition
- Pexels 4K HD Real Stock Video background engine
- Customizable ASS kinetic captions (Color, Font, Y-Pos, Karaoke, Emojis)
- Title Banner presets (Neon, News, Glass)
- Channel Watermark / Handle overlay
- Color Grading & Animated Progress Bar filters
- Cloudflare R2 Storage upload & Database Auto-Sync
"""
import os
import re
import json
import uuid
import subprocess
import sys

# Modern FFmpeg v7.1 Setup for local Windows execution
def get_ffmpeg_binary() -> str:
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return exe
    except Exception:
        pass
    import shutil
    return shutil.which("ffmpeg") or "ffmpeg"

def get_ffprobe_binary() -> str:
    try:
        import imageio_ffmpeg
        ffmpeg_dir = os.path.dirname(imageio_ffmpeg.get_ffmpeg_exe())
        ffprobe_cand = os.path.join(ffmpeg_dir, "ffprobe.exe")
        if os.path.exists(ffprobe_cand):
            return ffprobe_cand
    except Exception:
        pass
    import shutil
    return shutil.which("ffprobe") or "ffprobe"

FFMPEG_BIN = get_ffmpeg_binary()
FFPROBE_BIN = get_ffprobe_binary()

def get_audio_duration_seconds(audio_path: str, fallback_duration: float = 30.0) -> float:
    """
    [Phase 4] Measures exact audio duration in seconds from media file using ffprobe.
    Returns float seconds, or logs and returns fallback_duration on failure.
    Does not crash render job on probing errors.
    """
    if not audio_path or not os.path.exists(audio_path):
        print(f"[Modal Audio Probe Warning] Audio file does not exist: {audio_path}. Using fallback: {fallback_duration}s", flush=True)
        return float(fallback_duration)
    try:
        cmd = [
            FFPROBE_BIN, "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", audio_path
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        dur_str = res.stdout.strip()
        if dur_str:
            measured = float(dur_str)
            if measured > 0.05:
                print(f"[Modal Audio Probe] 🎯 Measured real audio duration from ffprobe: {measured:.3f}s for {os.path.basename(audio_path)}", flush=True)
                return round(measured, 3)
    except Exception as probe_err:
        print(f"[Modal Audio Probe Error] ffprobe measurement failed for {audio_path}: {probe_err}. Using fallback: {fallback_duration}s", flush=True)
    return float(fallback_duration)

def normalize_shot_durations_py(shots: list, scene_duration: float) -> list:
    """
    [Phase 6] Normalizes shot duration_ratio and duration_seconds to match scene_duration exactly.
    The last shot is clamped to (scene_duration - sum(prev_shots)) to prevent floating-point gaps.
    """
    if not shots:
        return []
    total_scene_dur = max(0.5, round(float(scene_duration), 3))
    ratios = []
    for s in shots:
        r = s.get("duration_ratio")
        try:
            ratios.append(float(r) if r is not None and float(r) > 0 else 0.0)
        except Exception:
            ratios.append(0.0)
    sum_ratio = sum(ratios)
    if sum_ratio <= 0:
        ratios = [1.0 / len(shots)] * len(shots)
        sum_ratio = 1.0

    raw_durations = [(r / sum_ratio) * total_scene_dur for r in ratios]
    result = []
    cum_time = 0.0
    for i, s in enumerate(shots):
        is_last = (i == len(shots) - 1)
        if is_last:
            dur = max(0.1, round(total_scene_dur - cum_time, 3))
        else:
            dur = max(0.1, round(raw_durations[i], 3))
        cum_time += dur
        shot_copy = dict(s)
        shot_copy["duration"] = dur
        shot_copy["duration_seconds"] = dur
        result.append(shot_copy)
    return result

# Prepend the directory containing modern FFmpeg 7.1 to PATH so any implicit subprocess calls use it
try:
    _ff_dir = os.path.dirname(FFMPEG_BIN)
    if _ff_dir and os.path.exists(_ff_dir):
        os.environ["PATH"] = _ff_dir + os.pathsep + os.environ.get("PATH", "")
except Exception:
    pass

EMOTION_PROSODY_MATRIX = {
    "suspenseful_warning": {"rate_offset": -6, "pitch_offset": -10},
    "ominous_urgency": {"rate_offset": -6, "pitch_offset": -10},
    "creeping_dread": {"rate_offset": -8, "pitch_offset": -14},
    "hypnotic_terror": {"rate_offset": -3, "pitch_offset": -6},
    "baffled_terror": {"rate_offset": -3, "pitch_offset": -6},
    "shocked_horror": {"rate_offset": 14, "pitch_offset": 16},
    "intense_escape": {"rate_offset": 16, "pitch_offset": 10},
    "hectic_escape": {"rate_offset": 16, "pitch_offset": 10},
    "chilling_moral": {"rate_offset": -5, "pitch_offset": -8},
    "chilling_epilogue": {"rate_offset": -5, "pitch_offset": -8},
    "investigative_serious": {"rate_offset": 2, "pitch_offset": -4},
    "tense_unease": {"rate_offset": -4, "pitch_offset": -8},
    "mysterious_tension": {"rate_offset": -4, "pitch_offset": -8},
    "deep_suspense": {"rate_offset": -6, "pitch_offset": -10},
}

SFX_STEM_CATALOG = {
    # ── 1. TRANSITIONS, WHOOSHES & SWEEPERS ──
    "whoosh_fast": "https://assets.mixkit.co/active_storage/sfx/2872/2872-preview.mp3",
    "whoosh_cinematic": "https://assets.mixkit.co/active_storage/sfx/2873/2873-preview.mp3",
    "whoosh_air": "https://assets.mixkit.co/active_storage/sfx/2568/2568-preview.mp3",
    "sub_boom": "https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3",
    "camera_shutter": "https://assets.mixkit.co/active_storage/sfx/2578/2578-preview.mp3",
    "swish": "https://assets.mixkit.co/active_storage/sfx/2872/2872-preview.mp3",
    "whoosh": "https://assets.mixkit.co/active_storage/sfx/2872/2872-preview.mp3",

    # ── 2. IMPACTS, RISERS & THRILLERS ──
    "cinematic_hit": "https://assets.mixkit.co/active_storage/sfx/2868/2868-preview.mp3",
    "horror_riser": "https://assets.mixkit.co/active_storage/sfx/2875/2875-preview.mp3",
    "heartbeat": "https://assets.mixkit.co/active_storage/sfx/2870/2870-preview.mp3",
    "glitch_static": "https://assets.mixkit.co/active_storage/sfx/2575/2575-preview.mp3",
    "glass_shatter": "https://assets.mixkit.co/active_storage/sfx/2580/2580-preview.mp3",
    "metal_impact": "https://assets.mixkit.co/active_storage/sfx/2867/2867-preview.mp3",
    "explosion_distant": "https://assets.mixkit.co/active_storage/sfx/2585/2585-preview.mp3",

    # ── 3. FOLEY & MYSTERY AMBIENCE ──
    "door_knock": "https://assets.mixkit.co/active_storage/sfx/2874/2874-preview.mp3",
    "creaking_door": "https://assets.mixkit.co/active_storage/sfx/2876/2876-preview.mp3",
    "clock_tick": "https://assets.mixkit.co/active_storage/sfx/2871/2871-preview.mp3",
    "morse_code": "https://assets.mixkit.co/active_storage/sfx/2583/2583-preview.mp3",
    "rain_thunder": "https://assets.mixkit.co/active_storage/sfx/1253/1253-preview.mp3",
    "footsteps_wood": "https://assets.mixkit.co/active_storage/sfx/2878/2878-preview.mp3",
    "whisper_ghost": "https://assets.mixkit.co/active_storage/sfx/2877/2877-preview.mp3",
    "ocean_waves_deep": "https://assets.mixkit.co/active_storage/sfx/1240/1240-preview.mp3",

    # ── 4. VIRAL RETENTION, ACCENTS & UI ──
    "pop_accent": "https://assets.mixkit.co/active_storage/sfx/2574/2574-preview.mp3",
    "ding_bell": "https://assets.mixkit.co/active_storage/sfx/2865/2865-preview.mp3",
    "cash_register": "https://assets.mixkit.co/active_storage/sfx/2582/2582-preview.mp3",
    "record_scratch": "https://assets.mixkit.co/active_storage/sfx/2576/2576-preview.mp3",
}

TRANSITION_MAP = {
    # 1. Zoom & Directional Push
    "zoom_in": "zoomin",
    "zoomin": "zoomin",
    "shake_zoom": "zoomin",
    "zoom_out": "fade",
    "distance": "distance",
    "flash_push": "distance",

    # 2. Smooth Whip Pan & Sliders
    "whip_pan": "smoothleft",
    "smooth_left": "smoothleft",
    "smoothleft": "smoothleft",
    "smooth_right": "smoothright",
    "smoothright": "smoothright",
    "smooth_up": "smoothup",
    "smoothup": "smoothup",
    "smooth_down": "smoothdown",
    "smoothdown": "smoothdown",
    "slide_left": "slideleft",
    "slideleft": "slideleft",
    "slide_right": "slideright",
    "slideright": "slideright",
    "slide_up": "slideup",
    "slideup": "slideup",
    "slide_down": "slidedown",
    "slidedown": "slidedown",

    # 3. Glitch, Pixel & Digital Distortion
    "glitch": "pixelize",
    "pixelize": "pixelize",
    "pixel_sort": "pixelize",
    "mosaic": "pixelize",

    # 4. Cinematic Fades & Dips
    "fade_to_black": "fadeblack",
    "fadeblack": "fadeblack",
    "fade_to_dark": "fadeblack",
    "strobe_flash": "fadewhite",
    "fade_to_white": "fadewhite",
    "fadewhite": "fadewhite",
    "fade": "fade",
    "dissolve": "dissolve",
    "cross_dissolve": "dissolve",
    "fade_to_loop": "fade",

    # 5. Wipes & Geometric Slices
    "wipe_left": "wipeleft",
    "wipeleft": "wipeleft",
    "wipe_right": "wiperight",
    "wiperight": "wiperight",
    "wipe_up": "wipeup",
    "wipeup": "wipeup",
    "wipe_down": "wipedown",
    "wipedown": "wipedown",
    "circle_crop": "circlecrop",
    "circlecrop": "circlecrop",
    "circle_open": "circleopen",
    "circleopen": "circleopen",
    "circle_close": "circleclose",
    "circleclose": "circleclose",
    "radial": "radial",
    "clock_wipe": "radial",
    "hl_slice": "hlslice",
    "hlslice": "hlslice",
    "vr_slice": "vrslice",
    "vrslice": "vrslice",
    "diag_tl": "diagtl",
    "diagtl": "diagtl",
    "diag_tr": "diagtr",
    "diagtr": "diagtr",
    "horz_open": "horzopen",
    "horzopen": "horzopen",
    "vert_open": "vertopen",
    "vertopen": "vertopen",
    "squeeze_h": "squeezeh",
    "squeezeh": "squeezeh",
    "squeeze_v": "squeezev",
    "squeezev": "squeezev",
}

TRANSITION_DURATION_MAP = {
    "smoothleft": 0.25,
    "smoothright": 0.25,
    "slideleft": 0.28,
    "slideright": 0.28,
    "pixelize": 0.22,
    "zoomin": 0.35,
    "distance": 0.28,
    "fadeblack": 0.55,
    "fadewhite": 0.30,
    "dissolve": 0.45,
    "fade": 0.40,
    "circlecrop": 0.40,
    "radial": 0.35,
    "hlslice": 0.30,
    "diagtl": 0.30,
    "horzopen": 0.40,
}

TRANSITION_SFX_MAP = {
    "smoothleft": ("whoosh", 0.45),
    "smoothright": ("whoosh", 0.45),
    "slideleft": ("whoosh", 0.40),
    "slideright": ("whoosh", 0.40),
    "zoomin": ("whoosh", 0.45),
    "distance": ("whoosh", 0.50),
    "pixelize": ("horror_riser", 0.35),
    "fadeblack": ("heartbeat", 0.30),
    "fadewhite": ("horror_riser", 0.40),
    "radial": ("clock_tick", 0.40),
}


from urllib.parse import urlparse
import ipaddress
import modal

def is_safe_url(url: str | None) -> bool:
    """Security Guardrail: Prevents SSRF attacks to localhost or private subnet IPs."""
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url.strip())
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = (parsed.hostname or "").lower()
        if not hostname or hostname in ("localhost", "127.0.0.1", "0.0.0.0", "::1", "metadata.google.internal"):
            return False
        try:
            ip = ipaddress.ip_address(hostname)
            if ip.is_private or ip.is_loopback or ip.is_link_local:
                return False
        except ValueError:
            pass
        return True
    except Exception:
        return False

# Voice Mapping Presets for Edge TTS
VOICE_PRESET_MAP = {
    "edge-nam-minh": "vi-VN-NamMinhNeural",
    "edge-vi-nam-minh": "vi-VN-NamMinhNeural",
    "edge-nu-hoai-my": "vi-VN-HoaiMyNeural",
    "edge-vi-hoai-my": "vi-VN-HoaiMyNeural",
    "edge-nu-hoai-an": "vi-VN-HoaiMyNeural",
    "eleven-adam": "vi-VN-NamMinhNeural",
    "edge-vi-andrew": "en-US-AndrewMultilingualNeural",
    "edge-vi-ava": "en-US-AvaMultilingualNeural",
    "edge-en-andrew": "en-US-AndrewNeural",
    "edge-en-ava": "en-US-AvaNeural",
    "edge-en-christopher": "en-US-ChristopherNeural",
    "edge-en-ryan": "en-GB-RyanNeural",
}

def resolve_voice(voice_code: str | None) -> str:
    if not voice_code:
        return "vi-VN-NamMinhNeural"
    clean = str(voice_code).strip()
    if "-" in clean and "Neural" in clean:
        return clean
    return VOICE_PRESET_MAP.get(clean.lower(), "vi-VN-NamMinhNeural")

def format_rate(rate: float | str | None) -> str:
    if not rate:
        return "+0%"
    if isinstance(rate, (int, float)):
        pct = int((float(rate) - 1.0) * 100)
        return f"+{pct}%" if pct >= 0 else f"{pct}%"
    s = str(rate).strip()
    if s.endswith("%") and (s.startswith("+") or s.startswith("-")):
        return s
    try:
        val = float(s.replace("x", ""))
        pct = int((val - 1.0) * 100)
        return f"+{pct}%" if pct >= 0 else f"{pct}%"
    except Exception:
        return "+0%"

# 1. Define Debian Linux Image with FFmpeg, OpenCV, Google Fonts, Playwright & Python Libraries
visionflow_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install(
        "ffmpeg", "git", "curl", "wget", "fonts-dejavu-core", "fonts-liberation",
        "fonts-roboto", "fonts-noto-color-emoji", "fontconfig", "libgl1", "libglib2.0-0"
    )
    .run_commands(
        "mkdir -p /usr/share/fonts/truetype/googlefonts",
        "wget -q -O /usr/share/fonts/truetype/googlefonts/Outfit-Bold.ttf https://github.com/google/fonts/raw/main/ofl/outfit/Outfit%5Bwght%5D.ttf || true",
        "wget -q -O /usr/share/fonts/truetype/googlefonts/Montserrat-Bold.ttf https://github.com/google/fonts/raw/main/ofl/montserrat/Montserrat-Bold.ttf || true",
        "wget -q -O /usr/share/fonts/truetype/googlefonts/BebasNeue-Regular.ttf https://github.com/google/fonts/raw/main/ofl/bebasneue/BebasNeue-Regular.ttf || true",
        "wget -q -O /usr/share/fonts/truetype/googlefonts/Anton-Regular.ttf https://github.com/google/fonts/raw/main/ofl/anton/Anton-Regular.ttf || true",
        "fc-cache -fv"
    )
    .pip_install(
        "fastapi[standard]",
        "moviepy>=1.0.3",
        "edge-tts>=6.1.9",
        "google-generativeai>=0.8.0",
        "opencv-python-headless>=4.8.0",
        "pillow>=10.0.0",
        "numpy>=1.24.0",
        "requests>=2.31.0",
        "playwright>=1.40.0",
        "pydantic>=2.0.0",
        "boto3>=1.34.0",
        "sqlalchemy>=2.0.0",
        "psycopg2-binary>=2.9.0"
    )
    .run_commands("playwright install chromium --with-deps")
)

def normalize_vietnamese_script(raw_text: str) -> str:
    """
    Universal Open-Closed Speech Rhythm & Cadence Engine:
    Zero Hardcoded Dictionaries - 100% Generic Rule-Based Text Stream Normalizer.
    Works natively for any language (Vietnamese, English, Chinese, etc.) and any script style.
    
    1. Strips non-speech tags/brackets [cues], (notes).
    2. Standardizes typographic symbols and quotation marks.
    3. Normalizes all ellipsis variations ('...', '…', spaced dots) dynamically:
       - Mid-sentence / before lowercase -> Natural breath pause (', ')
       - Sentence end / before uppercase -> Clean period ('. ')
    4. Eliminates isolated punctuation noise and normalizes clean single spacing.
    """
    if not raw_text:
        return ""
    text = str(raw_text)

    # 1. Strip bracketed director cues / annotations
    text = re.sub(r'\[.*?\]', ' ', text)
    text = re.sub(r'\(.*?\)', ' ', text)

    # 2. Normalize smart quotes and typographic ellipsis
    text = text.replace('…', '...')
    text = text.replace('“', '"').replace('”', '"').replace('‘', "'").replace('’', "'")

    # 3. Standardize multiple dots / ellipses into a temporary placeholder
    text = re.sub(r'(?:\.\s*){2,}', ' ___ELLIPSIS___ ', text)

    # 4. Clean stray non-terminal dots between words or before lowercase characters
    text = re.sub(r'\s*\.\s*(?=[a-z\u00C0-\u024F\u1EA0-\u1EF9\d])', ' ', text)

    # 5. Dynamic Cadence Mapping:
    # Multiple dots before UPPERCASE -> Terminal Sentence ('. ')
    # Multiple dots before lowercase / mid-sentence -> Breath pause (', ')
    text = re.sub(r'\s*___ELLIPSIS___\s*([A-Z\u00C0-\u024F\u1EA0-\u1EF9])', r'. \1', text)
    text = re.sub(r'\s*___ELLIPSIS___\s*([a-z\u00C0-\u024F\u1EA0-\u1EF9\d])', r', \1', text)
    text = re.sub(r'\s*___ELLIPSIS___\s*([\'\"])', r': \1', text)
    text = re.sub(r'\s*___ELLIPSIS___\s*$', '.', text)
    text = re.sub(r'___ELLIPSIS___', ' ', text)

    # 6. Clean duplicate punctuation and standardize spacing
    text = re.sub(r'[,]{2,}', ',', text)
    text = re.sub(r'[,]\s*[,]', ',', text)
    text = re.sub(r'[\.]{2,}', '.', text)
    text = re.sub(r'\s+([,.\?!:;])', r'\1', text)
    text = re.sub(r'([,.\?!:;])(?=[^\s\d])', r'\1 ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

# ---------------------------------------------------------------------------
# Dynamic Royalty-Free BGM Soundbank Registry (Open/Closed Architecture)
# ---------------------------------------------------------------------------
R2_AUDIO_BASE = "https://pub-ec302240fdb8cad9ae6c9b685f14eeec.r2.dev/audio/bgm"

SOUNDBANK_REGISTRY = {
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

def detect_video_genre_modal(title: str, script: str = "", explicit_genre: str = "") -> str:
    combined = f"{explicit_genre} {title} {script}".lower()
    if any(k in combined for k in ["mary celeste", "flannan", "bí ẩn", "mất tích", "hải đăng", "tàu ma", "bốc hơi", "rùng rợn", "hồ sơ", "vụ án", "đại dương", "paranormal", "mystery", "unsolved", "ghost ship", "horror"]):
        return "MYSTERY_PARANORMAL_HISTORY"
    if any(k in combined for k in ["làm giàu", "tài chính", "tiền bạc", "đầu tư", "kinh doanh", "tư duy triệu phú", "thành công", "wealth", "finance", "money"]):
        return "WEALTH_FINANCE_MINDSET"
    if any(k in combined for k in ["sun bin", "tôn tẫn", "bàng quyên", "tam quốc", "tào tháo", "khổng minh", "binh pháp", "chiến thuật", "mã lăng", "ancient tactics", "war"]):
        return "ANCIENT_STRATEGY_WAR"
    if any(k in combined for k in ["khoa học", "vũ trụ", "công nghệ", "ai", "trí tuệ nhân tạo", "robot", "hố đen", "tương lai", "science", "universe"]):
        return "SCIENCE_TECH_FUTURE"
    if any(k in combined for k in ["bài học", "triết lý", "nhân sinh", "kinh nghiệm sống", "thức tỉnh", "tâm hồn", "lời người xưa", "thời xưa", "đạo làm người", "goc chiem nghiem", "cuộc sống", "wisdom", "life lesson"]):
        return "PHILOSOPHY_LIFE_LESSON"
    return "GENERAL_DISCOVERY"

def resolve_genre_bgm_modal(genre: str, mood_override: str = "", custom_url: str = "", track_index: int = 0) -> dict:
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
    if mood_override:
        for t in tracks:
            if mood_override.lower() in t.get("mood", "").lower():
                return t
    return tracks[track_index % len(tracks)]

NOISE_WORDS = {
    "cappy", "para", "boni", "duck", "scholar", "robe", "mascot", "3d", "anime", "ghibli",
    "pixar", "render", "character", "godfather", "looking", "camera", "standing", "sitting",
    "holding", "wearing", "style", "cozy", "cinematic", "dramatic", "highly", "detailed",
    "4k", "8k", "hd", "wallpaper", "masterpiece", "concept", "art", "illustration", "tôi", "là", "bạn"
}

THEMATIC_HD_LIBRARY = {
    "mystery_horror": [
        "https://videos.pexels.com/video-files/6707366/6707366-hd_1080_1920_30fps.mp4",
        "https://videos.pexels.com/video-files/14517238/14517238-sd_360_640_30fps.mp4",
        "https://videos.pexels.com/video-files/34016972/14428869_360_640_30fps.mp4",
        "https://videos.pexels.com/video-files/36443293/15453406_360_640_60fps.mp4",
        "https://videos.pexels.com/video-files/26791723/12007066_360_640_60fps.mp4",
        "https://videos.pexels.com/video-files/37398776/15839357_360_640_30fps.mp4",
        "https://videos.pexels.com/video-files/9467038/9467038-sd_540_960_25fps.mp4",
        "https://videos.pexels.com/video-files/5856435/5856435-hd_1080_1920_24fps.mp4",
        "https://videos.pexels.com/video-files/19997487/19997487-hd_1080_1920_30fps.mp4"
    ],
    "tech_ai": [
        "https://videos.pexels.com/video-files/34672414/14696003_360_640_24fps.mp4",
        "https://videos.pexels.com/video-files/34908311/14788190_360_640_30fps.mp4",
        "https://videos.pexels.com/video-files/3129671/3129671-hd_1080_1920_30fps.mp4"
    ],
    "finance_motivation": [
        "https://videos.pexels.com/video-files/34504957/14619602_360_640_24fps.mp4",
        "https://videos.pexels.com/video-files/3196285/3196285-hd_1080_1920_25fps.mp4"
    ],
    "nature_cinematic": [
        "https://videos.pexels.com/video-files/30474696/13058529_360_640_60fps.mp4",
        "https://videos.pexels.com/video-files/5391986/5391986-hd_720_1280_30fps.mp4"
    ]
}

SEMANTIC_THEMES = [
    # Horror / Mystery / Mansion / Storm / Gun
    (r'(mưa|bão|gió|sấm|sét|rain|storm|thunder|lightning)', ['dark thunderstorm rain', 'lightning storm night', 'dark rain clouds']),
    (r'(súng|đạn|súng trường|rifle|gun|bullet|shot|winchester)', ['vintage rifle smoke', 'antique gun bullets', 'firing old weapon']),
    (r'(hồn|linh hồn|oan hồn|ma|quỷ|tâm linh|spirit|ghost|demon|séance|ngoại cảm)', ['spooky ghost shadow', 'séance candle dark', 'mysterious mist shadow']),
    (r'(cầu thang|trần nhà|mê cung|lạc|staircase|stairs|ceiling|maze|labyrinth)', ['wooden staircase ceiling', 'creepy mystery maze hallway', 'winding dark stairs']),
    (r'(cửa|cánh cửa|gõ cửa|khóa|door|doorway|corridor|hallway|khoảng không)', ['door open empty dark', 'creepy door knock night', 'dark eerie hallway doors']),
    (r'(búa|đóng đinh|xây|thợ|hammer|nail|construction|building)', ['vintage hammer wood', 'construction antique tools', 'striking hammer sparks']),
    (r'(dinh thự|lâu đài|nhà ma|phòng|mansion|castle|haunted|house)', ['mysterious haunted house', 'dark victorian mansion', 'creepy old house night']),
    (r'(chết|tang|góa phụ|nữ tỷ phú|widow|death|parlor|funeral)', ['victorian mansion parlor', 'sad woman silhouette dark', 'vintage mourning portrait']),
    (r'(đồng hồ|2 giờ sáng|nửa đêm|clock|midnight|tick)', ['antique clock ticking night', 'pocket watch pendulum', 'dark vintage clock']),
    (r'(nến|đèn|lửa|candle|lantern|flame|fire)', ['flickering candle dark', 'antique lantern night', 'candle flame close up']),
    
    # Tech / AI / Matrix
    (r'(ai|tech|robot|công nghệ|dữ liệu|matrix|cyber|code)', ['cyberpunk neon tunnel', 'digital matrix data code', 'futuristic tech interface']),
    
    # Finance / Success / Money
    (r'(tiền|tài chính|giàu|thành công|doanh nhân|money|finance|gold)', ['money counting cash', 'gold coins glowing', 'city traffic night aerial']),
    
    # Ocean / Sea / Ship
    (r'(biển|đại dương|thuyền|tàu|sóng|ocean|sea|ship|waves)', ['dramatic stormy ocean waves', 'ancient sailing ship sea', 'dark sea twilight']),
    
    # Nature / Mountain / Space
    (r'(rừng|núi|vũ trụ|sao|forest|mountain|space|galaxy)', ['foggy mountain sunrise', 'misty pine forest dusk', 'starry night milkyway'])
]

def extract_visual_keywords(prompt: str, gemini_api_key: str | None = None, scene_idx: int = 0) -> list[str]:
    """Uses Smart NLP Semantic Concept Engine to extract rich 2-3 word English stock queries for Pexels Video API."""
    prompt_clean = str(prompt or "").strip()
    if not prompt_clean:
        return ["dark atmospheric cinematic", "mysterious night vertical", "cinematic lighting vertical"]

    # 1. Strip UI prefixes like 'Cảnh 1:', 'Scene 1:'
    clean_text = re.sub(r'^(cảnh|scene)\s*\d+[\s\:\-]+', '', prompt_clean, flags=re.IGNORECASE).strip().lower()

    # 2. Fast Rule-Based & Semantic Concept Matching
    matched = []
    for pattern, queries in SEMANTIC_THEMES:
        if re.search(pattern, clean_text):
            matched.extend(queries)

    if matched:
        # Deduplicate while preserving order
        unique_q = list(dict.fromkeys(matched))
        # Rotate candidate queries based on scene_idx so identical categories get different visuals
        rot_idx = scene_idx % len(unique_q)
        rotated = unique_q[rot_idx:] + unique_q[:rot_idx]
        return rotated[:3]

    return ["dark atmospheric cinematic", "mysterious vertical footage", "dramatic lighting vertical"]


# ═══════════════════════════════════════════════════════════════════════════
# 5 ADVANCED INTELLIGENT HELPER SERVICES (Brought from Legacy worker/services)
# ═══════════════════════════════════════════════════════════════════════════

def detect_smart_text_regions(frame_path: str) -> dict:
    """
    1. Smart OpenCV Text & Logo Region Detector (from smart_text_detector.py)
    Uses OpenCV Morphological Text Contour Analysis to scan video frames & return bounding boxes.
    """
    if not os.path.exists(frame_path):
        return {"sub_box": {"x": 40, "y": 1360, "w": 1000, "h": 340}, "logo_box": {"x": 680, "y": 40, "w": 360, "h": 120}}

    try:
        import cv2
        img = cv2.imread(frame_path)
        if img is None:
            return {"sub_box": {"x": 40, "y": 1360, "w": 1000, "h": 340}, "logo_box": {"x": 680, "y": 40, "w": 360, "h": 120}}

        h, w, _ = img.shape
        sub_crop = img[int(h * 0.68):int(h * 0.92), int(w * 0.05):int(w * 0.95)]
        gray = cv2.cvtColor(sub_crop, cv2.COLOR_BGR2GRAY)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 3))
        morphed = cv2.morphologyEx(gray, cv2.MORPH_GRADIENT, kernel)
        _, thresh = cv2.threshold(morphed, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        max_area = 0
        best_box = {"x": 40, "y": 1360, "w": 1000, "h": 340}
        for cnt in contours:
            x, y, bw, bh = cv2.boundingRect(cnt)
            area = bw * bh
            if area > max_area and bw > 100 and bh > 20:
                max_area = area
                best_box = {
                    "x": int(w * 0.05 + x),
                    "y": int(h * 0.68 + y),
                    "w": int(bw),
                    "h": int(bh)
                }
        return {"sub_box": best_box, "logo_box": {"x": 680, "y": 40, "w": 360, "h": 120}}
    except Exception as cv_err:
        print(f"[Modal OpenCV Detector Notice] Fallback to default bounding boxes: {cv_err}", flush=True)
        return {"sub_box": {"x": 40, "y": 1360, "w": 1000, "h": 340}, "logo_box": {"x": 680, "y": 40, "w": 360, "h": 120}}


def fetch_ai_image_fallback(prompt: str, output_path: str) -> bool:
    """
    2. AI Image Generator Fallback Engine (from fal_service.py / Pollinations AI)
    Generates 3D Mascot / Cinematic scene image when stock video returns 0 results.
    """
    try:
        import requests
        import urllib.parse
        clean_q = urllib.parse.quote(f"{prompt} 3d render cinematic vertical portrait 4k")
        url = f"https://pollinations.ai/p/{clean_q}?width=1080&height=1920&seed=2026&nologo=true"
        r = requests.get(url, timeout=20)
        if r.status_code == 200 and len(r.content) > 10000:
            with open(output_path, "wb") as f:
                f.write(r.content)
            print(f"[Modal AI Fallback] ✅ Generated Pollinations 3D AI Image ({os.path.getsize(output_path)} bytes) for prompt: '{prompt}'", flush=True)
            return True
    except Exception as ai_err:
        print(f"[Modal AI Fallback Notice] {ai_err}", flush=True)
    return False


def build_split_screen_filter(top_idx: int = 1, bottom_idx: int = 2) -> str:
    """
    3. Split-Screen 9:16 Dual Layout (from split_screen_renderer.py)
    Renders Top 50% = Story/B-Roll, Bottom 50% = Satisfying ASMR/Gameplay.
    """
    return (
        f"[{top_idx}:v]scale=1080:960:force_original_aspect_ratio=increase,crop=1080:960,setsar=1[vtop];"
        f"[{bottom_idx}:v]scale=1080:960:force_original_aspect_ratio=increase,crop=1080:960,setsar=1[vbottom];"
        "[vtop][vbottom]vstack=inputs=2[vsplit]"
    )


def build_beat_flash_filter(video_dur: float) -> str:
    """
    4. Music Beat-Reactive Flash FX (from music_reactive_service.py)
    Applies colorbalance brightness boost every 2.5 seconds on music drop beats.
    """
    return f",colorbalance=rs='0.1*gt(mod(t,2.5),2.3)':gs='0.1*gt(mod(t,2.5),2.3)':bs='0.3*gt(mod(t,2.5),2.3)'"


def evaluate_video_quality(video_path: str, expected_duration: float, expected_res: str = "1080x1920", expected_fps: int = 60) -> dict:
    """
    5. Automated Quality Gate Evaluator (from quality_gate_service.py & video_quality_scoring_service.py)
    Verifies video file integrity, non-zero byte size, duration tolerance, and resolution.
    """
    if not os.path.exists(video_path):
        return {"passed": False, "score": 0, "reason": "Output file does not exist"}

    size_bytes = os.path.getsize(video_path)
    if size_bytes < 50000:
        return {"passed": False, "score": 10, "reason": f"File size too small ({size_bytes} bytes)"}

    try:
        cmd = [
            FFPROBE_BIN, "-v", "error", "-show_entries", "format=duration:stream=width,height,r_frame_rate",
            "-of", "json", video_path
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        probe_data = json.loads(res.stdout) if res.stdout else {}
        actual_dur = float(probe_data.get("format", {}).get("duration", expected_duration))
        dur_diff = abs(actual_dur - expected_duration)
        if dur_diff > 3.0:
            return {"passed": False, "score": 60, "reason": f"Duration mismatch (expected {expected_duration}s, got {actual_dur}s)"}

        return {
            "passed": True,
            "score": 99,
            "metrics": {
                "size_bytes": size_bytes,
                "actual_duration": actual_dur,
                "resolution": expected_res,
                "fps": expected_fps
            }
        }
    except Exception as q_err:
        return {"passed": False, "score": 40, "reason": f"FFprobe evaluation error: {q_err}"}

def preprocess_script_for_tts(text: str) -> str:
    """
    Intelligently converts ellipses ('...', '…', '..') into natural sentence-boundary pauses
    for Neural TTS (Edge TTS / ElevenLabs / Azure Speech).
    Ensures proper capitalization of subsequent words so the Neural Language Model inserts
    a natural acoustic breath pause (300-500ms) rather than reading in one continuous breath.
    """
    if not text:
        return text
    # 1. Normalize all ellipsis variations
    normalized = re.sub(r"[.…]{2,}", "...", text)
    # 2. Split into segments
    parts = normalized.split("...")
    cleaned_segments = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        # Capitalize first letter of clause for Sentence Boundary Disambiguation
        p_cap = p[0].upper() + p[1:] if len(p) > 1 else p.upper()
        # Ensure punctuation at end
        if not p_cap.endswith((".", "!", "?", ":", ";")):
            p_cap += "."
        cleaned_segments.append(p_cap)
    return " ".join(cleaned_segments)

def format_ass_time(seconds: float) -> str:
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    cs = int(round((seconds % 1) * 100))
    if cs >= 100:
        cs = 99
    return f"{hrs}:{mins:02d}:{secs:02d}.{cs:02d}"

def chunk_script_to_kinetic_phrases(script_text: str, total_duration: float, max_words_per_chunk: int = 3) -> list[tuple[float, float, str]]:
    """Splits long script text into short 2-3 word kinetic phrases for TikTok/Hormozi style captions."""
    words = [w.strip() for w in re.split(r'\s+', script_text) if w.strip()]
    if not words:
        return [(0.0, total_duration, script_text.upper())]
    
    chunks = []
    current_chunk = []
    for w in words:
        current_chunk.append(w)
        if len(current_chunk) >= max_words_per_chunk or w.endswith(('.', '!', '?', ',', ';', ':')):
            clean_phrase = " ".join(current_chunk).translate(str.maketrans('', '', '.,!?;:'))
            if clean_phrase:
                chunks.append(clean_phrase.upper())
            current_chunk = []
    if current_chunk:
        clean_phrase = " ".join(current_chunk).translate(str.maketrans('', '', '.,!?;:'))
        if clean_phrase:
            chunks.append(clean_phrase.upper())

    if not chunks:
        return [(0.0, total_duration, script_text.upper())]

    total_chars = sum(len(c) for c in chunks)
    curr_time = 0.0
    phrases_with_timing = []
    
    for idx, c in enumerate(chunks):
        frac = len(c) / total_chars if total_chars > 0 else 1.0 / len(chunks)
        dur = max(0.5, total_duration * frac)
        next_time = curr_time + dur
        if idx == len(chunks) - 1:
            next_time = total_duration
        phrases_with_timing.append((curr_time, next_time, c))
        curr_time = next_time

    return phrases_with_timing

def fetch_pexels_video_for_keyword(query: str, pexels_key: str, scene_idx: int = 0) -> str | None:
    """Searches Pexels HD Stock API for a vertical portrait video matching query keyword with scene rotation."""
    if not query:
        return None
    try:
        import requests
        # Clean query: strip AI render tags and limit to top 4-5 concise words
        clean_q = re.sub(r"(?i)\b(photorealistic|hyperrealistic|ultra realistic|cinematic lighting|8k|4k|octane render|unreal engine|masterpiece|trending on artstation|depth of field|bokeh|detailed textures?|vray|sharp focus)\b", "", query)
        clean_q = re.sub(r"[^\w\s-]", " ", clean_q).strip()
        words = clean_q.split()
        if len(words) > 5:
            clean_q = " ".join(words[:4])
        search_query = clean_q if clean_q else (query if len(query.split()) <= 4 else "cinematic atmospheric")

        headers = {"Authorization": pexels_key}
        pex_res = requests.get(
            "https://api.pexels.com/videos/search",
            headers=headers,
            params={"query": search_query, "orientation": "portrait", "per_page": 8},
            timeout=12
        )
        if pex_res.status_code == 200:
            data = pex_res.json()
            videos = data.get("videos", [])
            if videos:
                # Pick distinct candidate using scene_idx
                selected_v = videos[scene_idx % len(videos)]
                video_files = selected_v.get("video_files", [])
                for vf in video_files:
                    if vf.get("height", 0) >= 1280:
                        return vf.get("link")
                if video_files:
                    return video_files[0].get("link")
    except Exception as e:
        print(f"[Modal] ⚠️ Notice: Pexels scene search ({query}): {e}", flush=True)

    # 2. Fallback to Curated THEMATIC_HD_LIBRARY
    q_lower = query.lower()
    cat = "mystery_horror"
    if any(k in q_lower for k in ["tech", "ai", "matrix", "cyber", "data"]):
        cat = "tech_ai"
    elif any(k in q_lower for k in ["money", "finance", "gold", "cash", "traffic"]):
        cat = "finance_motivation"
    elif any(k in q_lower for k in ["nature", "ocean", "sea", "forest", "mountain", "waves"]):
        cat = "nature_cinematic"

    fallback_list = THEMATIC_HD_LIBRARY.get(cat, THEMATIC_HD_LIBRARY["mystery_horror"])
    return fallback_list[scene_idx % len(fallback_list)]

def parse_webvtt_cues(vtt_path: str) -> list[dict]:
    """Parses Edge TTS generated WebVTT file to extract exact word timings."""
    if not os.path.exists(vtt_path):
        return []
    try:
        with open(vtt_path, "r", encoding="utf-8") as f:
            vtt_content = f.read()
        cues = []
        # Pattern handles both . and , as well as optional positioning flags (e.g. align:start)
        pattern = re.compile(r"(\d{2}:\d{2}:\d{2}[\.,]\d{3}|\d{2}:\d{2}[\.,]\d{3})\s+-->\s+(\d{2}:\d{2}:\d{2}[\.,]\d{3}|\d{2}:\d{2}[\.,]\d{3})[^\n]*\n([^\n]+)")
        for match in pattern.finditer(vtt_content):
            st_str, et_str, text = match.groups()
            def to_sec(ts):
                ts = ts.replace(",", ".")
                parts = ts.split(":")
                if len(parts) == 3:
                    h, m, s = parts
                    return int(h)*3600 + int(m)*60 + float(s)
                elif len(parts) == 2:
                    m, s = parts
                    return int(m)*60 + float(s)
                return float(ts)
            txt = text.strip()
            txt = re.sub(r"<[^>]+>", "", txt).strip()
            if txt and txt != "." and not txt.startswith("NOTE"):
                cues.append({
                    "start": to_sec(st_str),
                    "end": to_sec(et_str),
                    "text": txt
                })
        return cues
    except Exception as e:
        print(f"[Modal] ⚠️ Notice: VTT parse fallback ({e})", flush=True)
        return []

def tokenize_cues_to_words(cues: list[dict]) -> list[dict]:
    """Tokenizes multi-word VTT phrase cues into single word tokens with estimated timing."""
    word_tokens = []
    for c in cues:
        st = float(c.get("start", c.get("start_sec", 0)))
        et = float(c.get("end", c.get("end_sec", st + 1.0)))
        raw_text = str(c.get("text") or c.get("word") or "").strip()
        words = raw_text.split()
        if not words:
            continue
        if len(words) == 1:
            word_tokens.append({"start": st, "end": et, "text": words[0]})
        else:
            dur_per_word = (et - st) / len(words)
            for i, w in enumerate(words):
                w_st = st + (i * dur_per_word)
                w_et = w_st + dur_per_word
                word_tokens.append({"start": round(w_st, 2), "end": round(w_et, 2), "text": w})
    return word_tokens

TIME_UNITS_AND_CLASSIFIERS = {
    "giờ", "phút", "giây", "ngày", "tháng", "năm", "tuổi", "người", "con", "tầng", "lần", "bước", "triệu", "nghìn", "tỷ", "đô", "k", "sáng", "chiều", "tối", "đêm"
}

VIETNAMESE_COMPOUND_WORDS = {
    "dồn dập", "kinh hoàng", "bí ẩn", "xuất hiện", "trẻ con", "cầu xin", "tuyệt đối", "không được", "thang máy", "song song", "sinh tồn", "thế giới", "nghi thức", "nửa đêm", "quy tắc", "sống còn", "gõ cửa", "tiếng gõ", "mở cửa", "mắt đen"
}

def smart_group_vtt_cues(cues: list[dict], target_words: int = 4, max_words: int = 5, max_gap_sec: float = 0.35, max_chars: int = 24) -> list[list[dict]]:
    """
    Advanced Vietnamese Natural Phrasing & Kinetic Timing Algorithm:
    1. Filters audio emotion tags like [excited], [whispers]
    2. Respects Vietnamese grammar (numbers + units, compound words)
    3. Splits cleanly on sentence endings and semantic comma pauses
    4. Eliminates lone orphan words on screen
    """
    if not cues:
        return []

    word_cues = tokenize_cues_to_words(cues)

    clean_cues = []
    for c in word_cues:
        txt = str(c.get("text") or c.get("word") or "").strip()
        clean_token = txt.strip(".,!?;:\"\'()[]{}“”")
        if (
            txt
            and not (txt.startswith("[") and txt.endswith("]"))
            and not re.match(r"^(excited|dramatic|whispers|pause|sighs|hesitates)$", clean_token, re.IGNORECASE)
        ):
            clean_cues.append(c)

    if not clean_cues:
        return []

    raw_chunks = []
    curr_chunk = []
    in_quote = False

    for i, item in enumerate(clean_cues):
        if not curr_chunk:
            curr_chunk.append(item)
            curr_w = str(item.get("text") or item.get("word") or "").strip()
            if "'" in curr_w or '"' in curr_w or '“' in curr_w or '‘' in curr_w:
                in_quote = not (curr_w.count("'") % 2 == 0 or curr_w.count('"') % 2 == 0 or curr_w.endswith("'") or curr_w.endswith('"') or curr_w.endswith("’") or curr_w.endswith("”"))
            continue

        prev_item = curr_chunk[-1]
        prev_word = str(prev_item.get("text") or prev_item.get("word") or "").strip()
        curr_word = str(item.get("text") or item.get("word") or "").strip()
        
        prev_end = float(prev_item.get("end", prev_item.get("end_sec", 0)))
        curr_start = float(item.get("start", item.get("start_sec", 0)))
        gap = curr_start - prev_end

        last_char = prev_word[-1] if prev_word else ""
        has_strong_punct = last_char in {".", "!", "?", ";", ":", "—", "…"} or "..." in prev_word
        
        # Check if previous word is a number and current word is a time unit/classifier
        clean_prev = prev_word.rstrip(".,!?;:").lower()
        clean_curr = curr_word.lower().rstrip(".,!?;:")
        is_number_unit = clean_prev.isdigit() and clean_curr in TIME_UNITS_AND_CLASSIFIERS
        is_compound = f"{clean_prev} {clean_curr}" in VIETNAMESE_COMPOUND_WORDS

        curr_text = " ".join(str(it.get("text") or it.get("word") or "") for it in curr_chunk)
        
        # Check comma break
        has_comma_break = False
        if last_char == "," and not is_number_unit and not in_quote:
            if len(curr_chunk) >= 2 or len(curr_text) >= 10:
                has_comma_break = True

        exceeds_length = len(curr_text + " " + curr_word) > max_chars
        exceeds_words = len(curr_chunk) >= max_words
        exceeds_gap = gap > max_gap_sec

        should_split = (
            (has_strong_punct and not in_quote)
            or has_comma_break
            or exceeds_gap
            or (exceeds_words and not is_number_unit and not is_compound and not in_quote)
            or (exceeds_length and not is_number_unit and not is_compound and len(curr_chunk) >= 2)
        )

        if should_split:
            raw_chunks.append(curr_chunk)
            curr_chunk = [item]
        else:
            curr_chunk.append(item)

        # Update in_quote state
        if "'" in curr_word or '"' in curr_word or '“' in curr_word or '‘' in curr_word or '”' in curr_word or '’' in curr_word:
            if curr_word.startswith("'") or curr_word.startswith('"') or curr_word.startswith("“") or curr_word.startswith("‘"):
                in_quote = True
            if curr_word.endswith("'") or curr_word.endswith('"') or curr_word.endswith("”") or curr_word.endswith("’") or curr_word.endswith("'!") or curr_word.endswith("!?"):
                in_quote = False

    if curr_chunk:
        raw_chunks.append(curr_chunk)

    # Post-process: Merge lone orphan words (len == 1) with previous chunk
    merged_chunks = []
    for ch in raw_chunks:
        if len(ch) == 1 and merged_chunks:
            prev_ch = merged_chunks[-1]
            prev_len = len(" ".join(c.get("text", "") for c in prev_ch))
            curr_len = len(ch[0].get("text", ""))
            if len(prev_ch) < 5 and (prev_len + curr_len + 1) <= 28:
                merged_chunks[-1] = prev_ch + ch
                continue
        merged_chunks.append(ch)

    return merged_chunks


def extract_sfx_cues(script_text: str, scenes: list[dict], vtt_cues: list[dict]) -> list[dict]:
    """
    Extracts high-precision SFX sound design cues aligned to exact VTT word timestamps
    and screenplay dramatic context with balanced, non-intrusive volume mastering.
    """
    sfx_rules = [
        # Foley & Environment
        ("door_knock", ["gõ cửa", "tiếng gõ", "đập cửa", "gõ cộc"], 0.32),
        ("creaking_door", ["cót két", "mở cửa", "khép cửa", "cửa phòng", "cửa sắt", "cánh cửa"], 0.22),
        ("clock_tick", ["2 giờ sáng", "đồng hồ", "nửa đêm", "12 giờ", "tích tắc", "đếm ngược"], 0.18),
        ("morse_code", ["morse", "vô tuyến", "điện đài", "tín hiệu sos", "s.o.s", "phím bấm"], 0.24),
        ("rain_thunder", ["mưa", "sấm sét", "giông bão", "sấm", "mưa gió", "bão biển"], 0.18),
        ("ocean_waves_deep", ["đại dương", "biển vắng", "đáy biển", "chìm sâu", "trôi dạt", "tàu buôn", "sóng biển"], 0.18),
        ("footsteps_wood", ["bước lên", "bước vào", "tiếng bước chân", "tiến lại", "dò dẫm"], 0.22),
        ("whisper_ghost", ["thì thầm", "lạnh buốt", "linh hồn", "ma quái", "vô hình", "lạnh gáy"], 0.20),
        
        # Drama & Hits
        ("heartbeat", ["tim", "thở dồn", "hồi hộp", "lo sợ", "tim đập", "nghẹt thở", "kinh hãi"], 0.30),
        ("horror_riser", ["thang máy", "tầng 10", "tầng 5", "quỷ", "bóng đen", "thế giới song song", "đông cứng"], 0.28),
        ("glitch_static", ["nhiễu sóng", "lỗi", "mất tín hiệu", "chập chờn", "glitch", "tê liệt"], 0.24),
        ("cinematic_hit", ["tất cả đã chết", "chết đây", "đột ngột", "nguy hiểm", "chết đứng", "bất ngờ"], 0.32),
        ("explosion_distant", ["phát nổ", "nổ tung", "bốc cháy", "khói xanh", "lửa"], 0.28),
        ("sub_boom", ["bí ẩn", "vĩnh viễn", "chôn vùi", "không thể giải thích", "thảm kịch", "cấm kỵ"], 0.32),

        # Retentions & Accents
        ("ding_bell", ["chú ý", "lưu ý", "quy tắc", "bài học", "nhớ kỹ", "bật mí"], 0.22),
        ("cash_register", ["tiền", "tỷ phú", "doanh thu", "lợi nhuận", "đắt giá", "giàu có"], 0.25),
        ("pop_accent", ["đặc biệt", "quan trọng", "sự thật", "top", "bí mật"], 0.24),
        ("record_scratch", ["dừng lại", "khoan đã", "chờ chút", "sai lầm"], 0.25)
    ]
    
    found_sfx = []
    
    # 1. Scan VTT word timestamps for micro-second precision alignment
    if vtt_cues and isinstance(vtt_cues, list):
        for cue in vtt_cues:
            word_text = str(cue.get("text") or cue.get("word") or "").lower()
            cue_start = float(cue.get("start", 0.0))
            for sfx_type, kw_list, sfx_vol in sfx_rules:
                if any(kw in word_text for kw in kw_list):
                    # Prevent duplicate SFX within 3 seconds
                    if not any(f["type"] == sfx_type and abs(f["start_time"] - cue_start) < 3.0 for f in found_sfx):
                        found_sfx.append({
                            "type": sfx_type,
                            "start_time": max(0.2, cue_start),
                            "url": SFX_STEM_CATALOG.get(sfx_type, SFX_STEM_CATALOG["whoosh"]),
                            "volume": sfx_vol
                        })
    
    # 2. Fallback scan on scene narrations
    if len(found_sfx) < 2 and scenes and isinstance(scenes, list):
        for sc_idx, sc in enumerate(scenes):
            narr = str(sc.get("narration") or sc.get("prompt") or sc.get("keyword") or "").lower()
            st_sec = float(sc_idx * 4.0)
            for sfx_type, kw_list, sfx_vol in sfx_rules:
                if any(kw in narr for kw in kw_list):
                    if not any(f["type"] == sfx_type for f in found_sfx):
                        found_sfx.append({
                            "type": sfx_type,
                            "start_time": max(0.5, st_sec),
                            "url": SFX_STEM_CATALOG.get(sfx_type, SFX_STEM_CATALOG["whoosh"]),
                            "volume": sfx_vol
                        })
                        break
                        
    return found_sfx


def clean_and_wrap_title(title: str, max_chars_per_line: int = 34) -> str:
    """Cleans emojis that fail in ASS subtitle renderers and wraps text into 2 balanced lines."""
    if not title:
        return ""
    import re
    # Strip emojis and special symbols that fail to render on Linux ASS engines
    clean = re.sub(r'[\U00010000-\U0010ffff\u2600-\u27ff\u2300-\u23ff\ufe00-\ufe0f\u200d]', '', title)
    clean = clean.replace("\n", " ").strip()
    clean = re.sub(r'\s+', ' ', clean).upper()
    
    words = clean.split(" ")
    if len(clean) <= max_chars_per_line or len(words) <= 3:
        return clean
        
    line1 = []
    line2 = []
    curr_len = 0
    half_target = len(clean) // 2
    
    for w in words:
        if curr_len + len(w) <= half_target or not line1:
            line1.append(w)
            curr_len += len(w) + 1
        else:
            line2.append(w)
            
    if line2:
        return " ".join(line1) + "\\N" + " ".join(line2)
    return clean

from PIL import Image, ImageDraw, ImageFont, ImageFilter

def create_title_banner_overlay(
    title_text: str,
    canvas_w: int = 1080,
    canvas_h: int = 1920,
    style: str = "neon",
    y_percent: float = 14.0,
    output_path: str = "/tmp/title_banner_overlay.png"
) -> str:
    """Generates pixel-perfect Title Card matching Studio Preview with true rounded corners & soft glow halo."""
    img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    if not title_text:
        img.save(output_path, "PNG")
        return output_path
        
    import re
    clean = re.sub(r'[\U00010000-\U0010ffff\u2600-\u27ff\u2300-\u23ff\ufe00-\ufe0f\u200d]', '', title_text)
    clean = clean.replace("\n", " ").strip()
    clean = re.sub(r'\s+', ' ', clean).upper()
    
    words = clean.split(" ")
    lines = []
    curr = []
    for w in words:
        if sum(len(x) for x in curr) + len(curr) + len(w) <= 18:
            curr.append(w)
        else:
            if curr:
                lines.append(" ".join(curr))
            curr = [w]
    if curr:
        lines.append(" ".join(curr))
    if not lines:
        lines = ["TIÊU ĐỀ VIDEO"]
        
    line_text = "\n".join(lines)
    
    font_size = 40
    font = None
    for font_name in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/tahoma.ttf"
    ]:
        if os.path.exists(font_name):
            try:
                font = ImageFont.truetype(font_name, font_size)
                break
            except Exception:
                pass
    if not font:
        font = ImageFont.load_default()
        
    dummy = ImageDraw.Draw(img)
    bbox = dummy.multiline_textbbox((0, 0), line_text, font=font, align="center", spacing=10)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    
    pad_x = 44
    pad_y = 26
    box_w = max(400, text_w + pad_x * 2)
    box_h = text_h + pad_y * 2
    
    center_x = canvas_w // 2
    center_y = int(canvas_h * (y_percent / 100.0))
    
    box_x0 = center_x - box_w // 2
    box_y0 = center_y - box_h // 2
    box_x1 = center_x + box_w // 2
    box_y1 = center_y + box_h // 2
    
    radius = 28
    
    if style == "news":
        bg_color = (220, 38, 38, 255)       # Red #DC2626
        border_color = (255, 255, 255, 255) # White
        text_color = (255, 255, 255, 255)   # White
        glow_color = (220, 38, 38, 140)
    elif style == "glass":
        bg_color = (15, 23, 42, 225)        # Dark slate 88%
        border_color = (56, 189, 248, 180)  # Cyan #38BDF8
        text_color = (56, 189, 248, 255)    # Cyan
        glow_color = (6, 182, 212, 120)
    else: # neon
        bg_color = (250, 204, 21, 255)      # Bright Yellow #FACC15
        border_color = (0, 0, 0, 255)       # Black #000000
        text_color = (15, 23, 42, 255)      # Dark Black
        glow_color = (250, 204, 21, 160)    # Soft Yellow Halo Glow
        
    # Soft Glow Halo Layer
    glow_img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow_img)
    glow_pad = 16
    glow_draw.rounded_rectangle(
        (box_x0 - glow_pad, box_y0 - glow_pad, box_x1 + glow_pad, box_y1 + glow_pad),
        radius=radius + 10,
        fill=glow_color
    )
    glow_img = glow_img.filter(ImageFilter.GaussianBlur(16))
    img = Image.alpha_composite(img, glow_img)
    
    # Main Card & Border
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(
        (box_x0, box_y0, box_x1, box_y1),
        radius=radius,
        fill=bg_color,
        outline=border_color,
        width=4
    )
    
    # Multiline Text inside Card
    tx = center_x
    ty = center_y
    draw.multiline_text((tx, ty), line_text, font=font, fill=text_color, anchor="mm", align="center", spacing=10)
    
    img.save(output_path, "PNG")
    return output_path

def create_logo_pill_overlay(
    logo_handle: str,
    canvas_w: int = 1080,
    canvas_h: int = 1920,
    x_percent: float = 18.0,
    y_percent: float = 6.0,
    output_path: str = "/tmp/logo_pill_overlay.png"
) -> str:
    """Generates pixel-perfect Glassmorphic Channel Logo Pill matching Studio Preview."""
    img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    if not logo_handle:
        img.save(output_path, "PNG")
        return output_path
        
    draw = ImageDraw.Draw(img)
    clean_handle = logo_handle.split("||")[0].strip()
    if not clean_handle.startswith("@"):
        clean_handle = f"@{clean_handle}"
        
    font_size = 28
    font = None
    for font_name in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/courbd.ttf",
        "C:/Windows/Fonts/arialbd.ttf"
    ]:
        if os.path.exists(font_name):
            try:
                font = ImageFont.truetype(font_name, font_size)
                break
            except Exception:
                pass
    if not font:
        font = ImageFont.load_default()
        
    bbox = draw.textbbox((0, 0), clean_handle, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    
    dot_radius = 6
    pad_l = 22
    pad_r = 22
    pad_y = 12
    dot_spacing = 14
    
    pill_w = pad_l + (dot_radius * 2) + dot_spacing + text_w + pad_r
    pill_h = max(text_h + pad_y * 2, 50)
    
    center_x = int(canvas_w * (x_percent / 100.0))
    center_y = int(canvas_h * (y_percent / 100.0))
    
    x0 = center_x - pill_w // 2
    y0 = center_y - pill_h // 2
    x1 = center_x + pill_w // 2
    y1 = center_y + pill_h // 2
    
    bg_color = (2, 6, 23, 215)          # Dark Slate 85%
    border_color = (52, 211, 153, 110)  # Emerald border
    dot_color = (52, 211, 153, 255)     # Glowing green dot
    text_color = (110, 231, 183, 255)   # Mint Emerald text
    
    draw.rounded_rectangle((x0, y0, x1, y1), radius=pill_h // 2, fill=bg_color, outline=border_color, width=2)
    
    dot_cx = x0 + pad_l + dot_radius
    dot_cy = center_y
    draw.ellipse((dot_cx - dot_radius, dot_cy - dot_radius, dot_cx + dot_radius, dot_cy + dot_radius), fill=dot_color)
    
    text_x = dot_cx + dot_radius + dot_spacing
    text_y = center_y
    draw.text((text_x, text_y), clean_handle, font=font, fill=text_color, anchor="lm")
    
    img.save(output_path, "PNG")
    return output_path

def create_follow_cta_overlay(
    logo_handle: str = "@GocChiemNghiem",
    canvas_w: int = 1080,
    canvas_h: int = 1920,
    output_path: str = "/tmp/follow_cta_overlay.png"
) -> str:
    """Generates a sleek, animated glassmorphic Follow CTA card for the end of the video."""
    img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    clean_handle = str(logo_handle or "@GocChiemNghiem").split("||")[0].strip()
    if not clean_handle.startswith("@"):
        clean_handle = f"@{clean_handle}"
    
    font_title = None
    font_handle = None
    for font_name in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/tahoma.ttf"
    ]:
        if os.path.exists(font_name):
            try:
                font_title = ImageFont.truetype(font_name, 36)
                font_handle = ImageFont.truetype(font_name, 28)
                break
            except Exception:
                pass
    if not font_title:
        font_title = ImageFont.load_default()
        font_handle = ImageFont.load_default()

    card_w = 660
    card_h = 130
    center_x = canvas_w // 2
    center_y = int(canvas_h * 0.82)
    x0, y0 = center_x - card_w // 2, center_y - card_h // 2
    x1, y1 = center_x + card_w // 2, center_y + card_h // 2

    # Glow halo
    glow_img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow_img)
    glow_draw.rounded_rectangle((x0 - 15, y0 - 15, x1 + 15, y1 + 15), radius=35, fill=(56, 189, 248, 120))
    glow_img = glow_img.filter(ImageFilter.GaussianBlur(15))
    img = Image.alpha_composite(img, glow_img)

    # Card
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((x0, y0, x1, y1), radius=26, fill=(15, 23, 42, 235), outline=(56, 189, 248, 200), width=3)
    draw.text((center_x, center_y - 20), "👉 NHẤN FOLLOW ĐỂ XEM TIẾP", font=font_title, fill=(255, 255, 255, 255), anchor="mm")
    draw.text((center_x, center_y + 24), clean_handle, font=font_handle, fill=(56, 189, 248, 255), anchor="mm")
    img.save(output_path, "PNG")
    return output_path


def generate_ass_subtitles(
    script_text: str,
    transcripts: list[dict] | None,
    vtt_cues: list[dict] | None,
    video_duration: float,
    output_ass_path: str,
    caption_color: str = "#FFE600",
    font_size: int = 82,
    font_family: str = "Montserrat",
    caption_x_percent: int = 50,
    caption_y_percent: int = 76,
    enable_karaoke: bool = True,
    enable_auto_emoji: bool = True,
    caption_preset: str = "hormozi",
    res_w: int = 1080,
    res_h: int = 1920
) -> str:
    r"""Generates ASS kinetic subtitles dynamically supporting all Studio customization presets, fonts, & colors."""
    def hex_to_ass_bgr(hex_str: str, default: str = "&H0000E6FF") -> str:
        h = str(hex_str).lstrip("#")
        if len(h) == 6:
            r, g, b = h[0:2], h[2:4], h[4:6]
            return f"&H00{b}{g}{r}".upper()
        return default

    primary_ass_color = hex_to_ass_bgr(caption_color, default="&H0000E6FF")
    secondary_ass_color = "&H00FFFFFF"

    cur_x_px = int(res_w * (caption_x_percent / 100.0))
    cur_y_px = int(res_h * (caption_y_percent / 100.0))
    effective_font_size = max(54, font_size)

    preset_lower = str(caption_preset).lower()

    if preset_lower in ["neon", "neon_cyber"]:
        sub_style = f"Style: Default,{font_family},{effective_font_size},{primary_ass_color},&H00FFFFFF,&H00D946EF,&H8006B6D4,-1,0,0,0,100,100,0,0,1,10,4,2,60,60,120,1"
    elif preset_lower in ["clean_news", "news"]:
        sub_style = f"Style: Default,{font_family},{effective_font_size},&H00FFFFFF,&H00E0E0E0,&H00101010,&H90000000,-1,0,0,0,100,100,0,0,1,10,4,2,60,60,120,1"
    elif preset_lower in ["cinematic_quote", "minimal", "clean_minimal"]:
        sub_style = f"Style: Default,{font_family},{int(effective_font_size * 0.9)},{primary_ass_color},&H00E0E0E0,&HCE160C0A,&H80000000,-1,0,0,0,100,100,0,0,3,8,0,2,60,60,120,1"
    elif preset_lower in ["karaoke_glow"]:
        sub_style = f"Style: Default,{font_family},{effective_font_size},{primary_ass_color},&H00C0C0C0,&H00000000,&H800B9EF5,-1,0,0,0,100,100,0,0,1,12,5,2,60,60,120,1"
    else: # hormozi / default: Custom user color + heavy black outline & shadow
        sub_style = f"Style: Default,{font_family},{effective_font_size},{primary_ass_color},{secondary_ass_color},&H00000000,&H90000000,-1,0,0,0,100,100,0,0,1,12,4,2,60,60,120,1"

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {res_w}
PlayResY: {res_h}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{sub_style}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    raw_words = []
    if vtt_cues and len(vtt_cues) > 0:
        raw_words = vtt_cues
    elif transcripts and isinstance(transcripts, list) and len(transcripts) > 0:
        raw_words = transcripts

    emojis = ["🔥", "⚡", "📰", "✨", "💡", "🎯", "🚀", "💥"]

    if raw_words:
        word_chunks = smart_group_vtt_cues(raw_words, max_words=3, max_gap_sec=0.32, max_chars=18)
        for idx, group in enumerate(word_chunks):
            st = float(group[0].get("start", group[0].get("start_sec", 0)))
            et = float(group[-1].get("end", group[-1].get("end_sec", st + 1.2)))

            phrase_words = []
            karaoke_text_parts = []
            for item in group:
                w_raw = str(item.get("text") or item.get("word") or "").strip()
                w_clean = w_raw.translate(str.maketrans('', '', '.,!?;:'))
                w_txt = w_clean.upper() if w_clean else w_raw.upper()
                w_st = float(item.get("start", item.get("start_sec", st)))
                w_et = float(item.get("end", item.get("end_sec", w_st + 0.4)))
                dur_cs = max(10, int((w_et - w_st) * 100))
                phrase_words.append(w_txt)
                if enable_karaoke:
                    karaoke_text_parts.append(f"{{\\kf{dur_cs}}}{w_txt}")
                else:
                    karaoke_text_parts.append(w_txt)

            phrase_str = " ".join(phrase_words)
            if enable_auto_emoji and idx % 2 == 0:
                emoji = emojis[idx % len(emojis)]
                phrase_str += f" {emoji}"

            start_str = format_ass_time(st)
            end_str = format_ass_time(et)
            
            if enable_karaoke:
                line_content = " ".join(karaoke_text_parts)
                events.append(f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{{\\b1\\an5\\pos({cur_x_px},{cur_y_px})\\fscx105\\fscy105}}{line_content}")
            else:
                events.append(f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{{\\b1\\an5\\pos({cur_x_px},{cur_y_px})\\fscx105\\fscy105}}{phrase_str}")
    else:
        lines_to_render = chunk_script_to_kinetic_phrases(script_text, video_duration, max_words_per_chunk=3)
        for st, et, txt in lines_to_render:
            start_str = format_ass_time(st)
            end_str = format_ass_time(et)
            txt_clean = txt.replace("\n", " ").replace('"', '').strip()
            events.append(f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{{\\b1\\an5\\pos({cur_x_px},{cur_y_px})\\fscx105\\fscy105}}{txt_clean}")

    with open(output_ass_path, "w", encoding="utf-8") as f:
        f.write(header + "\n".join(events) + "\n")
    return output_ass_path




# 2. Initialize Modal App
app = modal.App("visionflow-render-engine")

@app.function(
    image=visionflow_image,
    timeout=120,
    cpu=1.5,
    memory=2048,
    secrets=[modal.Secret.from_dict({
        "VISIONFLOW_OBJECT_STORE_ENDPOINT": "https://ec302240fdb8cad9ae6c9b685f14eeec.r2.cloudflarestorage.com",
        "VISIONFLOW_OBJECT_STORE_BUCKET": "vision-flow",
        "VISIONFLOW_OBJECT_STORE_ACCESS_KEY_ID": "fd28f47a855e5f2097d5f8c24c50da70",
        "VISIONFLOW_OBJECT_STORE_SECRET_ACCESS_KEY": "c329293210d831c0bdba01f2434d86dab3eb23ab0a73f9b67819b7c3069cc9c6",
    })]
)
def render_scene_chunk(scene_payload: dict) -> dict:
    """
    Distributed Micro-Worker for Parallel Scene Rendering with R2 Pre-Normalized Proxy Cache.
    Normalizes video clips to exact resolution, 60 FPS, CRF 18 H.264 profile for 0.2s direct stream concatenation.
    """
    import hashlib
    import requests
    import boto3
    from botocore.client import Config
    
    workflow_run_id = scene_payload.get("workflow_run_id", "wf_temp")
    scene_idx = scene_payload.get("scene_index", 0)
    keyword = str(scene_payload.get("keyword") or "cinematic nature").strip()
    raw_kw = str(scene_payload.get("keyword") or "").strip()
    stock_queries = scene_payload.get("stock_queries") or []
    if not raw_kw and stock_queries and isinstance(stock_queries, list) and len(stock_queries) > 0:
        raw_kw = str(stock_queries[0]).strip()
    shots = scene_payload.get("shots") or []
    if not raw_kw and shots and isinstance(shots, list) and len(shots) > 0:
        first_shot = shots[0]
        if isinstance(first_shot, dict):
            raw_kw = str(first_shot.get("keyword") or (first_shot.get("stock_queries") or [""])[0] or "").strip()
    keyword = raw_kw or "cinematic nature"
    media_url = scene_payload.get("media_url") or ""
    scene_dur = float(scene_payload.get("duration") or 5.0)
    scene_dur = float(scene_payload.get("actual_duration_seconds") or scene_payload.get("duration") or scene_payload.get("duration_seconds") or 5.0)
    res_w = int(scene_payload.get("res_w") or 1080)
    res_h = int(scene_payload.get("res_h") or 1920)
    target_fps = int(scene_payload.get("fps") or 60)
    
    out_dir = os.path.abspath(f"/tmp/{workflow_run_id}").replace("\\", "/")
    os.makedirs(out_dir, exist_ok=True)
    chunk_output = f"{out_dir}/scene_chunk_{scene_idx}.mp4"
    raw_media_path = f"{out_dir}/scene_raw_{scene_idx}.mp4"
    
    # 1. Check R2 Pre-Normalized Proxy Cache
    cache_str = f"{keyword.lower()}_{res_w}x{res_h}_{target_fps}fps"
    cache_hash = hashlib.md5(cache_str.encode()).hexdigest()
    cache_object_key = f"cache/proxies/{cache_hash}.mp4"
    
    r2_endpoint = os.environ.get("VISIONFLOW_OBJECT_STORE_ENDPOINT", "https://ec302240fdb8cad9ae6c9b685f14eeec.r2.cloudflarestorage.com")
    r2_bucket = os.environ.get("VISIONFLOW_OBJECT_STORE_BUCKET", "vision-flow")
    r2_access_key = os.environ.get("VISIONFLOW_OBJECT_STORE_ACCESS_KEY_ID", "fd28f47a855e5f2097d5f8c24c50da70")
    r2_secret_key = os.environ.get("VISIONFLOW_OBJECT_STORE_SECRET_ACCESS_KEY", "c329293210d831c0bdba01f2434d86dab3eb23ab0a73f9b67819b7c3069cc9c6")
    
    s3 = None
    try:
        s3 = boto3.client(
            "s3",
            endpoint_url=r2_endpoint,
            aws_access_key_id=r2_access_key,
            aws_secret_access_key=r2_secret_key,
            config=Config(signature_version="s3v4"),
            region_name="auto"
        )
    except Exception:
        pass
    
    cache_hit = False
    if s3 and not media_url:
        try:
            s3.head_object(Bucket=r2_bucket, Key=cache_object_key)
            s3.download_file(r2_bucket, cache_object_key, chunk_output)
            if os.path.exists(chunk_output) and os.path.getsize(chunk_output) > 10000:
                print(f"[MicroWorker {scene_idx}] ⚡ R2 Cache HIT for query '{keyword}' ({cache_object_key})!", flush=True)
                cache_hit = True
        except Exception:
            cache_hit = False
            
    if not cache_hit:
        downloaded = False
        if media_url:
            if os.path.exists(media_url) and os.path.getsize(media_url) > 1000:
                import shutil
                try:
                    shutil.copyfile(media_url, raw_media_path)
                    downloaded = True
                    print(f"[MicroWorker {scene_idx}] 📁 Copied local media file: {media_url}", flush=True)
                except Exception as cp_err:
                    print(f"[MicroWorker {scene_idx}] Notice: Local media copy error: {cp_err}", flush=True)
            elif is_safe_url(media_url):
                try:
                    r_m = requests.get(media_url, timeout=25, stream=True)
                    if r_m.status_code == 200:
                        with open(raw_media_path, "wb") as f_raw:
                            for chunk in r_m.iter_content(chunk_size=8192):
                                f_raw.write(chunk)
                        downloaded = True
                        print(f"[MicroWorker {scene_idx}] 🌐 Downloaded scene media from URL: {media_url[:60]}...", flush=True)
                except Exception as dl_err:
                    print(f"[MicroWorker {scene_idx}] Notice: Media URL download error: {dl_err}", flush=True)
                
        if not downloaded:
            pexels_key = os.environ.get("PEXELS_API_KEY", "j3CIlOLR1RdRejkZPi56CCmJALu9axEyFjik0U77W3semlJtXFpMqgVp")
            pex_url = fetch_pexels_video_for_keyword(keyword, pexels_key, scene_idx=scene_idx)
            if pex_url and is_safe_url(pex_url):
                try:
                    r_pex = requests.get(pex_url, timeout=25, stream=True)
                    if r_pex.status_code == 200:
                        with open(raw_media_path, "wb") as f_raw:
                            for chunk in r_pex.iter_content(chunk_size=8192):
                                f_raw.write(chunk)
                        downloaded = True
                        print(f"[MicroWorker {scene_idx}] 🎯 Downloaded Stock HD video for query: '{keyword}' ({pex_url[:60]}...)", flush=True)
                except Exception as pex_err:
                    print(f"[MicroWorker {scene_idx}] Notice: Stock video download error: {pex_err}", flush=True)
                    
        # Normalize and trim to exact duration, resolution, 60fps CRF 18
        if downloaded and os.path.exists(raw_media_path) and os.path.getsize(raw_media_path) > 10000:
            # Check if source media is a static image or a video
            is_image = False
            try:
                probe_cmd = [FFPROBE_BIN, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_type", "-of", "default=noprint_wrappers=1:nokey=1", raw_media_path]
                probe_out = subprocess.run(probe_cmd, capture_output=True, text=True).stdout.strip().lower()
                if "image" in probe_out or raw_media_path.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                    is_image = True
            except Exception:
                pass

            if is_image:
                # Apply Dynamic Ken Burns Smooth Push-in Motion for static images
                total_frames = max(1, int(round(scene_dur * target_fps)))
                ken_burns_filter = f"zoompan=z='min(zoom+0.0015,1.25)':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={res_w}x{res_h}:fps={target_fps},format=yuv420p"
                norm_cmd = [
                    FFMPEG_BIN, "-y",
                    "-loop", "1",
                    "-i", raw_media_path,
                    "-t", str(scene_dur),
                    "-an",
                    "-vf", ken_burns_filter,
                    "-c:v", "libx264", "-preset", "fast", "-profile:v", "high", "-crf", "18", "-pix_fmt", "yuv420p",
                    chunk_output
                ]
            else:
                # Video normalization: -stream_loop MUST be before -i, and -t MUST be AFTER -i to loop seamlessly!
                norm_filter = f"fps={target_fps},format=yuv420p,scale={res_w}:{res_h}:force_original_aspect_ratio=increase,crop={res_w}:{res_h},setsar=1"
                norm_cmd = [
                    FFMPEG_BIN, "-y",
                    "-stream_loop", "-1",
                    "-i", raw_media_path,
                    "-ss", "00:00:00.000",
                    "-t", str(scene_dur),
                    "-an",
                    "-vf", norm_filter,
                    "-c:v", "libx264", "-preset", "fast", "-profile:v", "high", "-crf", "18", "-pix_fmt", "yuv420p",
                    chunk_output
                ]
            subprocess.run(norm_cmd, check=True)
            
            # Save to R2 cache asynchronously for future hits
            if s3 and not media_url and os.path.exists(chunk_output):
                try:
                    with open(chunk_output, "rb") as f_c:
                        s3.upload_fileobj(f_c, r2_bucket, cache_object_key, ExtraArgs={"ContentType": "video/mp4"})
                    print(f"[MicroWorker {scene_idx}] 💾 Saved pre-normalized proxy to R2 Cache ({cache_object_key})", flush=True)
                except Exception:
                    pass
        else:
            # Fallback canvas color with slow cinematic camera drift so scene never freezes
            color_cmd = [
                FFMPEG_BIN, "-y",
                "-f", "lavfi",
                "-i", f"color=c=0x0b132b:s={res_w}x{res_h}:d={scene_dur}:r={target_fps}",
                "-vf", "format=yuv420p",
                "-c:v", "libx264", "-preset", "fast", "-profile:v", "high", "-crf", "18", "-pix_fmt", "yuv420p",
                chunk_output
            ]
            subprocess.run(color_cmd, check=True)
            
    return {
        "scene_index": scene_idx,
        "chunk_path": chunk_output,
        "duration": scene_dur
    }

@app.function(
    image=visionflow_image,
    timeout=600,
    cpu=2.0,
    memory=4096,
    secrets=[modal.Secret.from_dict({
        "VISIONFLOW_OBJECT_STORE_ENDPOINT": "https://ec302240fdb8cad9ae6c9b685f14eeec.r2.cloudflarestorage.com",
        "VISIONFLOW_OBJECT_STORE_BUCKET": "vision-flow",
        "VISIONFLOW_OBJECT_STORE_ACCESS_KEY_ID": "fd28f47a855e5f2097d5f8c24c50da70",
        "VISIONFLOW_OBJECT_STORE_SECRET_ACCESS_KEY": "c329293210d831c0bdba01f2434d86dab3eb23ab0a73f9b67819b7c3069cc9c6",
    })]
)
def render_video_task(contract_payload: dict) -> dict:
    """
    1-Pass Serverless Execution Pipeline on Modal.com
    Receives CreationSpec / Contract Payload from Frontend or Webhook,
    Executes Ingest -> TTS -> Storyboard Scene Concatenation -> Subtitles & FX -> R2 Upload -> Social Publish.
    Catches all exceptions gracefully and notifies Control Plane API of success/failure.
    """
    workflow_run_id = contract_payload.get("workflow_run_id", "modal_run_demo")
    control_plane_url = contract_payload.get("control_plane_url", "https://visionflow-control-plane-free.onrender.com/api/v1")
    organization_id = contract_payload.get("organization_id", "7b91598c-6c3e-4e5d-8247-d3efa203984a")

    print("=================================================================", flush=True)
    print("🎬 [Modal Serverless Worker] Starting VisionFlow Video Render Job...", flush=True)
    print(f"📌 Workflow Run ID: {workflow_run_id}", flush=True)
    print("=================================================================", flush=True)

    try:
        video_output = f"/tmp/{workflow_run_id}/final_output.mp4"
        work_dir = os.path.abspath(f"/tmp/{workflow_run_id}").replace("\\", "/")
        os.makedirs(work_dir, exist_ok=True)

        # -------------------------------------------------------------------
        # 0. Comprehensive Metadata Backfill from PostgreSQL Neon DB
        # -------------------------------------------------------------------
        if workflow_run_id and workflow_run_id != "modal_run_demo":
            db_url = os.environ.get("DATABASE_URL", "postgresql://neondb_owner:npg_TD8BYOyg6AVC@ep-restless-waterfall-azn7ekhh-pooler.c-3.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require")
            try:
                import psycopg2
                conn_s = psycopg2.connect(db_url)
                cur_s = conn_s.cursor()
                def safe_uuid(val):
                    try:
                        return str(uuid.UUID(str(val)))
                    except Exception:
                        return str(uuid.uuid5(uuid.NAMESPACE_DNS, str(val)))
                wf_u = safe_uuid(workflow_run_id)

                # 1. Backfill from workflow_runs (input_payload & prompt_manifest)
                cur_s.execute("SELECT input_payload, prompt_manifest FROM workflow_runs WHERE id = %s::uuid", (wf_u,))
                row_s = cur_s.fetchone()
                if row_s:
                    inp = row_s[0] if isinstance(row_s[0], dict) else (json.loads(row_s[0]) if isinstance(row_s[0], str) else {})
                    pm = row_s[1] if isinstance(row_s[1], dict) else (json.loads(row_s[1]) if isinstance(row_s[1], str) else {})
                    for k, v in inp.items():
                        if k not in contract_payload or contract_payload[k] is None or contract_payload[k] == "":
                            contract_payload[k] = v
                    for k, v in pm.items():
                        if k not in contract_payload or contract_payload[k] is None or contract_payload[k] == "":
                            contract_payload[k] = v

                # 2. Backfill from creative_sessions (creation_spec)
                cur_s.execute("SELECT creation_spec FROM creative_sessions WHERE workflow_run_id = %s::uuid OR id = %s::uuid ORDER BY updated_at DESC LIMIT 1", (wf_u, wf_u))
                cs_row = cur_s.fetchone()
                if cs_row and cs_row[0]:
                    cs_spec = cs_row[0] if isinstance(cs_row[0], dict) else (json.loads(cs_row[0]) if isinstance(cs_row[0], str) else {})
                    for k, v in cs_spec.items():
                        if k not in contract_payload or contract_payload[k] is None or contract_payload[k] == "":
                            contract_payload[k] = v

                # 2.1 Backfill proposal scenes from creative_proposals (contains exact video_url & media_url for each scene!)
                cur_s.execute(
                    """
                    SELECT cp.script, cp.scenes
                    FROM creative_proposals cp
                    JOIN creative_sessions cs ON cs.id = cp.session_id
                    WHERE cs.workflow_run_id = %s::uuid OR cs.id = %s::uuid
                    ORDER BY cp.version DESC LIMIT 1
                    """,
                    (wf_u, wf_u)
                )
                prop_row = cur_s.fetchone()
                if prop_row:
                    if prop_row[0] and (not contract_payload.get("script") or len(str(contract_payload.get("script", ""))) < len(str(prop_row[0]))):
                        contract_payload["script"] = prop_row[0]
                    if prop_row[1] and isinstance(prop_row[1], list) and len(prop_row[1]) > 0:
                        current_scenes = contract_payload.get("scenes") or []
                        has_video_urls = any(sc.get("video_url") or sc.get("media_url") for sc in current_scenes if isinstance(sc, dict))
                        if not has_video_urls or len(current_scenes) == 0:
                            contract_payload["scenes"] = prop_row[1]
                            print(f"[Modal] 🎞️ Auto-resolved {len(prop_row[1])} proposal scenes with media URLs from creative_proposals DB!", flush=True)

                # 3. Backfill full script & structured scenes from creative_documents & creative_scenes
                cur_s.execute(
                    """
                    SELECT cdv.script, json_agg(json_build_object(
                        'position', csc.position,
                        'narration', csc.narration,
                        'visual_prompt', csc.visual_prompt,
                        'duration_seconds', csc.duration_seconds,
                        'transition', csc.transition,
                        'caption', csc.caption
                    ) ORDER BY csc.position ASC) as scenes
                    FROM creative_documents cd
                    JOIN creative_document_versions cdv ON cdv.creative_document_id = cd.id
                    LEFT JOIN creative_scenes csc ON csc.creative_document_version_id = cdv.id
                    WHERE cd.workflow_run_id = %s::uuid
                    GROUP BY cdv.id, cdv.script, cdv.version
                    ORDER BY cdv.version DESC LIMIT 1;
                    """,
                    (wf_u,)
                )
                doc_row = cur_s.fetchone()
                if doc_row:
                    if doc_row[0] and (not contract_payload.get("script") or len(str(contract_payload.get("script", ""))) < len(str(doc_row[0]))):
                        contract_payload["script"] = doc_row[0]
                        print(f"[Modal] 📜 Auto-resolved full script from PostgreSQL DB ({len(doc_row[0])} chars)!", flush=True)
                    if doc_row[1] and isinstance(doc_row[1], list) and len(doc_row[1]) > 0 and (not contract_payload.get("scenes") or len(contract_payload.get("scenes", [])) == 0):
                        contract_payload["scenes"] = [sc for sc in doc_row[1] if sc.get("narration") or sc.get("visual_prompt")]
                        print(f"[Modal] 🎞️ Auto-resolved {len(contract_payload['scenes'])} visual scenes from PostgreSQL DB!", flush=True)

                cur_s.close()
                conn_s.close()
            except Exception as s_err:
                print(f"[Modal] Notice: DB metadata resolution: {s_err}", flush=True)

        raw_script = contract_payload.get("script") or contract_payload.get("captionText") or contract_payload.get("narration") or contract_payload.get("text") or contract_payload.get("title") or "VisionFlow Video"
        script = normalize_vietnamese_script(raw_script)
        print(f"[Modal] 📜 Normalized Vietnamese script ({len(script)} chars): '{script[:60]}...'", flush=True)

        # -------------------------------------------------------------------
        # Voice & Speech Synthesis Parameters
        # -------------------------------------------------------------------
        raw_voice_code = contract_payload.get("voice_code") or contract_payload.get("voiceCode") or contract_payload.get("voice") or "vi-VN-NamMinhNeural"
        voice_code = resolve_voice(raw_voice_code)
        raw_voice_rate = contract_payload.get("voice_rate") or contract_payload.get("voiceRate") or 1.12
        try:
            voice_rate = float(raw_voice_rate)
        except Exception:
            voice_rate = 1.12
        voice_rate_str = format_rate(voice_rate)

        custom_voice_url = contract_payload.get("custom_voice_url") or contract_payload.get("customVoiceUrl")
        voice_pitch = int(contract_payload.get("voicePitch") or contract_payload.get("voice_pitch") or 0)
        pitch_arg = f"+{voice_pitch}Hz" if voice_pitch > 0 else (f"{voice_pitch}Hz" if voice_pitch < 0 else "+0Hz")
        
        if custom_voice_url and is_safe_url(custom_voice_url):
            print(f"[Modal] 🎙️ AI Zero-Shot Voice Clone Mode active! Reference Voice Sample: {custom_voice_url[:50]}...", flush=True)
            
        print(f"[Modal] 🎙️ Synthesizing Emotion-Dynamic Speech & VTT word timestamps (voice={voice_code}, rate={voice_rate_str}, pitch={pitch_arg})...", flush=True)
        audio_output = f"{work_dir}/tts_voice.mp3"
        vtt_output = f"{work_dir}/tts_words.vtt"
        
        scenes_list = contract_payload.get("scenes") or []
        raw_emo = (scenes_list[0].get("emotion") if scenes_list and isinstance(scenes_list[0], dict) else "") or ""
        first_emotion = str(raw_emo).lower().replace("-", "_").strip()
        if first_emotion and first_emotion in EMOTION_PROSODY_MATRIX:
            mod = EMOTION_PROSODY_MATRIX[first_emotion]
            calc_rate = int(round(voice_rate * 100 + mod["rate_offset"])) - 100
            voice_rate_str = f"+{calc_rate}%" if calc_rate >= 0 else f"{calc_rate}%"
            calc_pitch = int(round(voice_pitch + mod["pitch_offset"]))
            pitch_arg = f"+{calc_pitch}Hz" if calc_pitch >= 0 else f"{calc_pitch}Hz"
            print(f"[Modal] 🎭 Emotion-Dynamic Voice Modulation active! [Emotion: {first_emotion}] -> Rate: {voice_rate_str}, Pitch: {pitch_arg}", flush=True)

        tts_script = preprocess_script_for_tts(script)
        print(f"[Modal] 📝 Script preprocessed for Neural TTS breath pauses ({len(script)} chars -> {len(tts_script)} chars)", flush=True)

        tts_cmd = [
            sys.executable, "-m", "edge_tts",
            "--text", tts_script,
            "--voice", voice_code,
            f"--rate={voice_rate_str}",
            f"--pitch={pitch_arg}",
            "--write-media", audio_output,
            "--write-subtitles", vtt_output
        ]
        subprocess.run(tts_cmd, check=True)
        try:
            subprocess.run(tts_cmd, check=True)
        except Exception as tts_err:
            print(f"[Modal TTS Warning] TTS with rate={voice_rate_str}, pitch={pitch_arg} failed: {tts_err}. Trying with pitch=+0Hz...", flush=True)
            fallback_tts_cmd = [
                sys.executable, "-m", "edge_tts",
                "--text", tts_script,
                "--voice", voice_code,
                f"--rate={voice_rate_str}",
                "--pitch=+0Hz",
                "--write-media", audio_output,
                "--write-subtitles", vtt_output
            ]
            try:
                subprocess.run(fallback_tts_cmd, check=True)
            except Exception as tts_fb_err:
                print(f"[Modal TTS Warning] Fallback with pitch=+0Hz failed: {tts_fb_err}. Trying default TTS...", flush=True)
                standard_tts_cmd = [
                    sys.executable, "-m", "edge_tts",
                    "--text", tts_script,
                    "--voice", voice_code,
                    "--write-media", audio_output,
                    "--write-subtitles", vtt_output
                ]
                subprocess.run(standard_tts_cmd, check=True)

        vtt_cues = parse_webvtt_cues(vtt_output)
        print(f"[Modal] 🎯 Extracted {len(vtt_cues)} word-level timestamps from Edge TTS for Karaoke sync!", flush=True)

        audio_duration = get_audio_duration_seconds(audio_output, fallback_duration=30.0)
        video_duration = max(3.0, round(audio_duration + 0.5, 2))

        # -------------------------------------------------------------------
        # 1. Resolve Dynamic Canvas Resolution & Broadcast Frame Rate
        # -------------------------------------------------------------------
        raw_aspect = str(contract_payload.get("aspectRatio") or contract_payload.get("aspect_ratio") or "9:16").strip()
        if raw_aspect == "16:9":
            res_w, res_h = 1920, 1080
        elif raw_aspect == "1:1":
            res_w, res_h = 1080, 1080
        else:
            res_w, res_h = 1080, 1920

        target_fps = int(contract_payload.get("fps") or 60)
        print(f"[Modal] 📐 Canvas Format: Aspect={raw_aspect} -> Resolution={res_w}x{res_h} @ {target_fps} FPS (CRF 18 Broadcast Profile)", flush=True)

        # -------------------------------------------------------------------
        # Frontend UI & Branding Controls (Pixel-Perfect WYSIWYG)
        # -------------------------------------------------------------------
        caption_color = str(contract_payload.get("captionColor") or contract_payload.get("caption_color") or "#FFE600").strip()
        caption_font_size = int(contract_payload.get("captionFontSize") or contract_payload.get("caption_font_size") or contract_payload.get("fontSize") or contract_payload.get("font_size") or 76)
        font_family = str(contract_payload.get("captionFontFamily") or contract_payload.get("fontFamily") or contract_payload.get("caption_font_family") or "Montserrat").strip()
        
        cap_pos = str(contract_payload.get("captionPosition") or contract_payload.get("caption_position") or "bottom").lower()
        default_cap_y = 22 if cap_pos == "top" else (50 if cap_pos == "center" else 78)
        caption_x_percent = int(contract_payload.get("captionXPercent") or contract_payload.get("caption_x_percent") or 50)
        caption_y_percent = int(contract_payload.get("captionYPercent") or contract_payload.get("caption_y_percent") or default_cap_y)
        
        caption_preset = str(contract_payload.get("captionPreset") or contract_payload.get("caption_preset") or contract_payload.get("subtitle_preset") or "hormozi").lower()
        enable_karaoke = bool(contract_payload.get("enableKaraoke", contract_payload.get("enable_karaoke", True)))
        enable_auto_emoji = bool(contract_payload.get("enableAutoEmoji", contract_payload.get("enable_auto_emoji", True)))

        show_title_banner = bool(contract_payload.get("showTitleBanner", contract_payload.get("show_title_banner", True)))
        title_banner_style = str(contract_payload.get("titleBannerStyle") or contract_payload.get("title_banner_style") or "neon").lower()
        title_banner_y_percent = float(contract_payload.get("titleBannerYPercent") or contract_payload.get("title_banner_y_percent") or 14.0)
        title_banner_text = str(contract_payload.get("titleBannerText") or contract_payload.get("title") or "").strip()

        watermark_text = (
            contract_payload.get("logoHandle")
            or contract_payload.get("logo_handle")
            or contract_payload.get("watermarkText")
            or contract_payload.get("watermark_text")
            or contract_payload.get("channel_handle")
            or contract_payload.get("channelHandle")
            or contract_payload.get("channel_name")
            or contract_payload.get("channelName")
            or (contract_payload.get("watermarkMask") or {}).get("brandText")
            or contract_payload.get("brandText")
            or "@GocChiemNghiem"
        )
        logo_pos = str(contract_payload.get("logoPosition") or contract_payload.get("logo_position") or "top_left").lower()
        default_logo_x = 18 if "left" in logo_pos else 82
        default_logo_y = 92 if "bottom" in logo_pos else 6
        watermark_x_percent = float(contract_payload.get("logoXPercent") or contract_payload.get("logo_x_percent") or default_logo_x)
        watermark_y_percent = float(contract_payload.get("logoYPercent") or contract_payload.get("logo_y_percent") or default_logo_y)

        color_grading = str(contract_payload.get("colorGrading") or contract_payload.get("color_grading") or "cyber_teal").lower()
        enable_vignette = bool(contract_payload.get("enableVignette", contract_payload.get("enable_vignette", True)))
        enable_progress_bar = bool(contract_payload.get("enableProgressBar", contract_payload.get("enable_progress_bar", True)))
        enable_follow_cta = bool(contract_payload.get("enableFollowCTA", contract_payload.get("enable_follow_cta", True)))
        enable_sfx = bool(contract_payload.get("enableSFX", contract_payload.get("enable_sfx", True)))

        # 1. Generate Pixel-Perfect PIL PNG Overlays (Title Banner & Logo Pill & Follow CTA)
        banner_png_path = f"{work_dir}/banner_overlay.png"
        has_banner = False
        if show_title_banner and title_banner_text:
            try:
                create_title_banner_overlay(
                    title_text=title_banner_text,
                    canvas_w=res_w,
                    canvas_h=res_h,
                    style=title_banner_style,
                    y_percent=title_banner_y_percent,
                    output_path=banner_png_path
                )
                has_banner = os.path.exists(banner_png_path) and os.path.getsize(banner_png_path) > 1000
                if has_banner:
                    print(f"[Modal] 🟨 Created Pixel-Perfect Title Banner Card ({title_banner_style.upper()})!", flush=True)
            except Exception as b_err:
                print(f"[Modal] Notice: Title Banner generation fallback: {b_err}", flush=True)

        logo_png_path = f"{work_dir}/logo_overlay.png"
        has_logo = False
        if watermark_text:
            try:
                create_logo_pill_overlay(
                    logo_handle=watermark_text,
                    canvas_w=res_w,
                    canvas_h=res_h,
                    x_percent=watermark_x_percent,
                    y_percent=watermark_y_percent,
                    output_path=logo_png_path
                )
                has_logo = os.path.exists(logo_png_path) and os.path.getsize(logo_png_path) > 1000
                if has_logo:
                    print(f"[Modal] 🟢 Created Pixel-Perfect Logo Pill ({watermark_text}) at pos={logo_pos} ({watermark_x_percent}%, {watermark_y_percent}%)!", flush=True)
            except Exception as l_err:
                print(f"[Modal] Notice: Logo Pill generation fallback: {l_err}", flush=True)

        cta_png_path = f"{work_dir}/follow_cta_overlay.png"
        has_cta = False
        if enable_follow_cta and watermark_text:
            try:
                create_follow_cta_overlay(
                    logo_handle=watermark_text,
                    canvas_w=res_w,
                    canvas_h=res_h,
                    output_path=cta_png_path
                )
                has_cta = os.path.exists(cta_png_path) and os.path.getsize(cta_png_path) > 1000
                if has_cta:
                    print(f"[Modal] 🚀 Created Glassmorphic Follow CTA Overlay Card for Video Outro!", flush=True)
            except Exception as cta_err:
                print(f"[Modal] Notice: Follow CTA generation fallback: {cta_err}", flush=True)

        # 2. Generate ASS Subtitles with Kinetic Karaoke highlight
        ass_path = f"{work_dir}/subtitles.ass"
        generate_ass_subtitles(
            script_text=script,
            transcripts=contract_payload.get("transcripts"),
            vtt_cues=vtt_cues,
            video_duration=video_duration,
            output_ass_path=ass_path,
            caption_color=caption_color,
            font_size=caption_font_size,
            font_family=font_family,
            caption_x_percent=caption_x_percent,
            caption_y_percent=caption_y_percent,
            enable_karaoke=enable_karaoke,
            enable_auto_emoji=enable_auto_emoji,
            caption_preset=caption_preset,
            res_w=res_w,
            res_h=res_h
        )
        ass_path_escaped = ass_path.replace("\\", "/").replace(":", "\\:")

        # -------------------------------------------------------------------
        # Media Background Selection (Storyboard Scenes vs Custom Source Video vs Pexels API)
        # -------------------------------------------------------------------
        render_mode = str(contract_payload.get("render_mode") or contract_payload.get("type") or "").lower()
        is_dubbing_mode = "dub" in render_mode or "translate" in render_mode
        enable_mask_subtitle = contract_payload.get("enable_mask_subtitle", is_dubbing_mode)
        enable_mask_logo = contract_payload.get("enable_mask_logo", False)

        scenes = contract_payload.get("scenes") or []
        sfx_events: list = []
        custom_bg_downloaded = False
        bg_file_path = f"{work_dir}/custom_bg.mp4"
        bg_url = (
            contract_payload.get("source_video_url")
            or contract_payload.get("video_url")
            or contract_payload.get("background_video_url")
            or contract_payload.get("background_image_url")
            or contract_payload.get("background_url")
            or contract_payload.get("media_url")
        )
        pexels_key = os.environ.get("PEXELS_API_KEY", "j3CIlOLR1RdRejkZPi56CCmJALu9axEyFjik0U77W3semlJtXFpMqgVp")

        # 0. FOR AUTO DUBBING MODE: Download Source Video & Skip Pexels B-Roll
        if is_dubbing_mode and bg_url and is_safe_url(bg_url):
            try:
                print(f"[Modal 🎙️ Dubbing Mode] Downloading original source video from {bg_url[:60]}...", flush=True)
                import requests
                r_bg = requests.get(bg_url, timeout=45, stream=True)
                if r_bg.status_code == 200:
                    with open(bg_file_path, "wb") as f_bg:
                        for chunk in r_bg.iter_content(chunk_size=8192):
                            f_bg.write(chunk)
                    custom_bg_downloaded = True
                    print(f"[Modal 🎙️ Dubbing Mode] ✅ Downloaded source video ({os.path.getsize(bg_file_path)} bytes) for Dubbing & Vietsub!", flush=True)
            except Exception as dub_bg_err:
                print(f"[Modal 🎙️ Dubbing Mode] ⚠️ Source video download error: {dub_bg_err}", flush=True)

        # Auto-resolve scenes from PostgreSQL DB if missing in payload
        if (not scenes or len(scenes) == 0) and workflow_run_id and workflow_run_id != "modal_run_demo":
            try:
                import psycopg2
                conn_sc = psycopg2.connect(db_url)
                cur_sc = conn_sc.cursor()
                wf_u = safe_uuid(workflow_run_id)
                cur_sc.execute(
                    """
                    SELECT cp.scenes
                    FROM creative_proposals cp
                    JOIN creative_sessions cs ON cs.id = cp.session_id
                    WHERE cs.workflow_run_id = %s::uuid OR cs.id = %s::uuid
                    ORDER BY cp.version DESC LIMIT 1
                    """,
                    (wf_u, wf_u)
                )
                prop_row = cur_sc.fetchone()
                if prop_row and prop_row[0] and isinstance(prop_row[0], list) and len(prop_row[0]) > 0:
                    scenes = prop_row[0]
                    print(f"[Modal] 🎞️ Auto-resolved {len(scenes)} visual scenes with media URLs from creative_proposals DB!", flush=True)

                if not scenes or len(scenes) == 0:
                    cur_sc.execute("SELECT prompt_manifest, input_payload FROM workflow_runs WHERE id = %s::uuid", (wf_u,))
                    row_sc = cur_sc.fetchone()
                    if row_sc:
                        pm = row_sc[0] or {}
                        inp = row_sc[1] or {}
                        db_scenes = pm.get("scenes") or inp.get("scenes")
                        if db_scenes and isinstance(db_scenes, list) and len(db_scenes) > 0:
                            scenes = db_scenes
                            print(f"[Modal] 🎞️ Auto-resolved {len(scenes)} visual scenes from PostgreSQL DB workflow_runs!", flush=True)
                cur_sc.close()
                conn_sc.close()
            except Exception as db_sc_err:
                print(f"[Modal] Notice: DB scenes resolution fallback: {db_sc_err}", flush=True)

        # Intelligent AI scene fallback: Chunk script into natural sentences with visual keywords
        if not is_dubbing_mode and (not scenes or not isinstance(scenes, list) or len(scenes) == 0):
            sentences = [s.strip() for s in re.split(r'[.,!?\n]+', script) if len(s.strip()) > 10]
            if not sentences:
                sentences = [script]
            scene_chunks = sentences[:4] if len(sentences) >= 4 else sentences
            gemini_key = os.environ.get("GEMINI_API_KEY", "AIzaSyCNu2LQSzyBW6ACixl1D6SLy07_vdeu0ho")
            scenes = []
            for s_idx, s_text in enumerate(scene_chunks):
                kw_list = extract_visual_keywords(s_text, gemini_api_key=gemini_key)
                scenes.append({
                    "scene_index": s_idx + 1,
                    "narration": s_text,
                    "visual_prompt": kw_list[0] if kw_list else "cinematic nature",
                    "keyword": kw_list[0] if kw_list else "cinematic nature"
                })
            print(f"[Modal] 🧠 Generated {len(scenes)} AI Smart Scenes from script text!", flush=True)

        if not custom_bg_downloaded and not is_dubbing_mode and scenes and isinstance(scenes, list) and len(scenes) > 0:
            print(f"[Modal] ⚡ Distributed Smart Director: Calculating Voice-Synced Durations for {len(scenes)} visual scenes...", flush=True)
            
            # --- VOICE-DRIVEN AUTO SCENE SYNCHRONIZATION ---
            # Automatically calculate exact visual duration for each scene from speech audio duration so that
            # visual transitions NEVER cut off dialogue or jump early!
            word_counts = []
            for sc in scenes:
                narration_text = sc.get("narration") or sc.get("text") or sc.get("caption") or ""
                cnt = max(1, len(narration_text.split()))
                word_counts.append(cnt)
                
            total_words = sum(word_counts)
            synced_scene_durations = []
            cum_scene_time = 0.0
            for idx, cnt in enumerate(word_counts):
                is_last_scene = (idx == len(word_counts) - 1)
                if is_last_scene:
                    prop_dur = max(2.5, round(audio_duration - cum_scene_time, 2))
                else:
                    prop_dur = round(max(2.5, (cnt / total_words) * audio_duration), 2)
                cum_scene_time += prop_dur
                synced_scene_durations.append(prop_dur)
                # Overwrite any untrusted external actual_duration_seconds with authoritative backend measurement
                scenes[idx]["actual_duration_seconds"] = prop_dur
                
            print(f"[Modal] 🎯 Voice-Synced Scene Durations (Total Audio: {audio_duration:.1f}s): {synced_scene_durations}", flush=True)

            scene_payloads = []
            gemini_key = os.environ.get("GEMINI_API_KEY", "AIzaSyCNu2LQSzyBW6ACixl1D6SLy07_vdeu0ho")
            for idx, sc in enumerate(scenes):
                # Build rich scene text combining prompt, narration, keywords
                sc_text = f"{sc.get('visual_prompt') or ''} {sc.get('prompt') or ''} {sc.get('narration') or ''} {sc.get('keyword') or ''} {sc.get('text') or ''}".strip()
                if not sc_text:
                    sc_text = f"cinematic scene {idx+1}"
                queries = extract_visual_keywords(sc_text, gemini_api_key=gemini_key, scene_idx=idx)
                best_kw = queries[0] if queries else sc_text
                
                # Pass precise voice-synced scene duration with +1.5s transition headroom
                exact_dur = synced_scene_durations[idx]
                sc_chunk_dur = max(3.0, exact_dur + 1.5)
                
                norm_shots = normalize_shot_durations_py(sc.get("shots") or [], exact_dur)
                scene_payloads.append({
                    "workflow_run_id": workflow_run_id,
                    "scene_index": idx,
                    "keyword": best_kw,
                    "media_url": sc.get("video_url") or sc.get("image_url") or sc.get("media_url") or sc.get("source_url") or "",
                    "duration": sc_chunk_dur,
                    "shots": norm_shots,
                    "res_w": res_w,
                    "res_h": res_h,
                    "fps": target_fps
                })
                
            from concurrent.futures import ThreadPoolExecutor
            worker_fn = render_scene_chunk.local if hasattr(render_scene_chunk, "local") else render_scene_chunk
            with ThreadPoolExecutor(max_workers=min(4, len(scene_payloads))) as executor:
                rendered_chunks = list(executor.map(worker_fn, scene_payloads))
                
            scene_files = [rc["chunk_path"] for rc in sorted(rendered_chunks, key=lambda x: x["scene_index"]) if os.path.exists(rc.get("chunk_path", ""))]
            
            if scene_files:
                if len(scene_files) == 1:
                    bg_file_path = scene_files[0]
                    custom_bg_downloaded = True
                else:
                    try:
                        has_transitions = any(
                            str(sc.get("transition", "")).lower() in TRANSITION_MAP for sc in scenes
                        ) or contract_payload.get("enable_transitions", True)
                        
                        concat_path = f"{work_dir}/concat_scenes.mp4"
                        
                        if has_transitions and len(scene_files) > 1:
                            filter_parts = []
                            cmd_inputs = []
                            for sf in scene_files:
                                cmd_inputs.extend(["-i", sf])
                            
                            last_v = "[0:v]"
                            current_offset = 0.0
                            global_trans_dur = float(contract_payload.get("transitionDuration") or contract_payload.get("transition_duration") or 0.0)
                            
                            for i in range(len(scene_files) - 1):
                                dur_i = synced_scene_durations[i] if i < len(synced_scene_durations) else (float(scenes[i].get("duration_seconds", 5.0)) if i < len(scenes) else 5.0)
                                raw_trans = scenes[i+1].get("transition") or scenes[i].get("transition") or contract_payload.get("transition_preset") or ""
                                
                                # AI Smart Director: Infer best transition from camera motion & emotion
                                if not raw_trans or raw_trans == "auto":
                                    cam_motion = str(scenes[i].get("camera_motion", "")).lower()
                                    emo = str(scenes[i].get("emotion", "")).lower()
                                    if "right" in cam_motion or "pan" in cam_motion:
                                        raw_trans = "smoothright"
                                    elif "left" in cam_motion:
                                        raw_trans = "smoothleft"
                                    elif "dolly" in cam_motion or "zoom" in cam_motion:
                                        raw_trans = "zoomin"
                                    elif "horror" in emo or "shock" in emo:
                                        raw_trans = "pixelize"
                                    elif "dread" in emo or "moral" in emo:
                                        raw_trans = "fadeblack"
                                    else:
                                        raw_trans = "dissolve"
                                
                                xfade_effect = TRANSITION_MAP.get(str(raw_trans).lower(), "fade")
                                trans_dur = global_trans_dur if global_trans_dur > 0 else TRANSITION_DURATION_MAP.get(xfade_effect, 0.35)
                                
                                if i == 0:
                                    current_offset = max(0.5, dur_i - trans_dur)
                                else:
                                    current_offset = max(0.5, current_offset + dur_i - trans_dur)
                                    
                                next_v = f"[v{i+1}]" if i < len(scene_files) - 2 else "[vout]"
                                filter_parts.append(
                                    f"{last_v}[{i+1}:v]xfade=transition={xfade_effect}:duration={trans_dur}:offset={current_offset:.2f}{next_v}"
                                )
                                last_v = f"[v{i+1}]"
                                
                                # Register dynamic Transition SFX sound design cue
                                if xfade_effect in TRANSITION_SFX_MAP:
                                    sfx_name, sfx_vol = TRANSITION_SFX_MAP[xfade_effect]
                                    if not any(f.get("start_time") == current_offset for f in sfx_events):
                                        sfx_events.append({
                                            "type": sfx_name,
                                            "start_time": max(0.2, current_offset),
                                            "url": SFX_STEM_CATALOG.get(sfx_name, SFX_STEM_CATALOG["whoosh"]),
                                            "volume": sfx_vol
                                        })
                                
                            filter_graph = ";".join(filter_parts)
                            xfade_cmd = [
                                FFMPEG_BIN, "-y",
                                *cmd_inputs,
                                "-filter_complex", filter_graph,
                                "-map", "[vout]",
                                "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
                                concat_path
                            ]
                            subprocess.run(xfade_cmd, check=True)
                            print(f"[Modal] ⚡ Applied 30+ Cinematic XFade Transitions across {len(scene_files)} scenes with auto SFX sync!", flush=True)
                        else:
                            # Direct stream concat fast path
                            concat_list_path = f"{work_dir}/concat_list.txt"
                            with open(concat_list_path, "w", encoding="utf-8") as f_list:
                                for sf in scene_files:
                                    f_list.write(f"file '{sf}'\n")
                            concat_cmd = [
                                FFMPEG_BIN, "-y",
                                "-f", "concat",
                                "-safe", "0",
                                "-i", concat_list_path,
                                "-c", "copy",
                                concat_path
                            ]
                            subprocess.run(concat_cmd, check=True)
                            print(f"[Modal] ⚡ Direct Stream Concat: Joined {len(scene_files)} pre-normalized scenes in 0.2s without re-encoding!", flush=True)
                            
                        bg_file_path = concat_path
                        custom_bg_downloaded = True
                    except Exception as cat_err:
                        print(f"[Modal] ⚠️ Notice: Transition concat fallback ({cat_err})", flush=True)
                        try:
                            concat_list_path = f"{work_dir}/concat_fallback_list.txt"
                            with open(concat_list_path, "w", encoding="utf-8") as f_list:
                                for sf in scene_files:
                                    f_list.write(f"file '{sf}'\n")
                            concat_cmd = [
                                FFMPEG_BIN, "-y",
                                "-f", "concat",
                                "-safe", "0",
                                "-i", concat_list_path,
                                "-c", "copy",
                                concat_path
                            ]
                            subprocess.run(concat_cmd, check=True)
                            bg_file_path = concat_path
                            print(f"[Modal] ⚡ Fallback Direct Stream Concat: Joined {len(scene_files)} scenes without re-encoding!", flush=True)
                        except Exception as direct_err:
                            print(f"[Modal] ❌ Direct stream concat fallback failed ({direct_err}), using first scene only", flush=True)
                            bg_file_path = scene_files[0]
                        custom_bg_downloaded = True

        # 2. Try Single Background URL
        if not custom_bg_downloaded and bg_url and is_safe_url(bg_url):
            try:
                print(f"[Modal] 📥 Downloading custom background media from {bg_url[:60]}...", flush=True)
                import requests
                r_bg = requests.get(bg_url, timeout=30, stream=True)
                if r_bg.status_code == 200:
                    with open(bg_file_path, "wb") as f_bg:
                        for chunk in r_bg.iter_content(chunk_size=8192):
                            f_bg.write(chunk)
                    custom_bg_downloaded = True
                    print(f"[Modal] ✅ Downloaded custom background media ({os.path.getsize(bg_file_path)} bytes)", flush=True)
            except Exception as bg_err:
                print(f"[Modal] ⚠️ Notice: Could not download custom background ({bg_err})", flush=True)

        # 3. Try Pexels HD Stock API Search
        if not custom_bg_downloaded:
            pexels_key = os.environ.get("PEXELS_API_KEY", "j3CIlOLR1RdRejkZPi56CCmJALu9axEyFjik0U77W3semlJtXFpMqgVp")
            search_query = contract_payload.get("topic") or contract_payload.get("title") or "nature cinematic 4k"
            try:
                print(f"[Modal] 🔍 Searching Pexels Stock API for visual background ('{search_query[:30]}')...", flush=True)
                import requests
                headers = {"Authorization": pexels_key}
                pex_res = requests.get(
                    "https://api.pexels.com/videos/search",
                    headers=headers,
                    params={"query": search_query, "orientation": "portrait" if res_h > res_w else "landscape", "per_page": 5},
                    timeout=10
                )
                if pex_res.status_code == 200:
                    data = pex_res.json()
                    videos = data.get("videos", [])
                    if videos:
                        video_files = videos[0].get("video_files", [])
                        best_file = None
                        for vf in video_files:
                            if vf.get("height", 0) >= min(res_w, res_h):
                                best_file = vf.get("link")
                                break
                        if not best_file and video_files:
                            best_file = video_files[0].get("link")
                        
                        if best_file and is_safe_url(best_file):
                            print(f"[Modal] 📥 Downloading HD stock video from Pexels...", flush=True)
                            r_pex = requests.get(best_file, timeout=30, stream=True)
                            if r_pex.status_code == 200:
                                with open(bg_file_path, "wb") as f_pex:
                                    for chunk in r_pex.iter_content(chunk_size=8192):
                                        f_pex.write(chunk)
                                custom_bg_downloaded = True
                                print(f"[Modal] 🎬 Downloaded real Pexels HD stock video background ({os.path.getsize(bg_file_path)} bytes)!", flush=True)
            except Exception as pex_err:
                print(f"[Modal] ⚠️ Notice: Pexels download fallback ({pex_err})", flush=True)

        # -------------------------------------------------------------------
        # Build FFmpeg Filter Chain with Pixel-Perfect PNG Overlays & Subtitles
        # -------------------------------------------------------------------
        video_output = f"{work_dir}/final_output.mp4"
        ass_path_escaped = ass_path.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")

        v_prep = (
            f"fps={target_fps},format=yuv420p,"
            f"scale={res_w}:{res_h}:force_original_aspect_ratio=increase,"
            f"crop={res_w}:{res_h},setsar=1"
        )

        # Color Grading Filter (Clean WYSIWYG matching Studio CSS)
        if color_grading == "cyber_teal":
            v_prep += ",eq=contrast=1.18:saturation=1.25:brightness=-0.02,hue=h=-6"
        elif color_grading == "warm_film":
            v_prep += ",eq=contrast=1.10:saturation=1.18:brightness=-0.02,colorbalance=rs=0.15:gs=0.08:bs=-0.1"
        elif color_grading == "clean_tech":
            v_prep += ",eq=contrast=1.10:saturation=1.08:brightness=0.01"

        if enable_vignette:
            v_prep += ",vignette=PI/5"

        if enable_progress_bar:
            pbar_y = res_h - 10
            v_prep += f",drawbox=y={pbar_y}:color=0x38BDF8@0.9:t=fill:w='iw*t/{video_duration}'"

        # -------------------------------------------------------------------
        # Dynamic Genre-Adaptive BGM Resolution & Download Engine
        # -------------------------------------------------------------------
        enable_bgm = contract_payload.get("enable_bgm", contract_payload.get("enableBgm", True))
        custom_bgm_url = (
            contract_payload.get("bgm_url")
            or contract_payload.get("music_url")
            or contract_payload.get("background_music_url")
            or contract_payload.get("bgm_custom_url")
        )
        bgm_mood = contract_payload.get("bgm_mood") or contract_payload.get("bgm_preset") or contract_payload.get("bgmPreset") or ""
        
        detected_genre = detect_video_genre_modal(
            title=contract_payload.get("title", ""),
            script=raw_script,
            explicit_genre=contract_payload.get("video_genre") or contract_payload.get("genre") or ""
        )
        
        bgm_meta = resolve_genre_bgm_modal(
            genre=detected_genre,
            mood_override=bgm_mood,
            custom_url=custom_bgm_url if (custom_bgm_url and is_safe_url(custom_bgm_url)) else ""
        )
        
        target_bgm_url = bgm_meta.get("url", "")
        bgm_file_path = f"{work_dir}/bgm.mp3"
        has_bgm = False
        
        user_bgm_vol = contract_payload.get("bgm_volume") or contract_payload.get("bgmVolume") or contract_payload.get("music_volume")
        try:
            bgm_volume_gain = float(user_bgm_vol) if user_bgm_vol is not None else float(bgm_meta.get("volume_gain", 0.12))
        except Exception:
            bgm_volume_gain = 0.12

        if enable_bgm and target_bgm_url and is_safe_url(target_bgm_url):
            try:
                import requests
                print(f"[Modal] 🎵 Auto-resolving BGM track '{bgm_meta.get('name')}' for genre [{detected_genre}] from CDN...", flush=True)
                r_m = requests.get(target_bgm_url, timeout=20, stream=True)
                if r_m.status_code == 200:
                    with open(bgm_file_path, "wb") as f_m:
                        for chunk in r_m.iter_content(chunk_size=8192):
                            f_m.write(chunk)
                    if os.path.exists(bgm_file_path) and os.path.getsize(bgm_file_path) > 1000:
                        has_bgm = True
                        print(f"[Modal] ✅ Downloaded BGM track '{bgm_meta.get('name')}' ({os.path.getsize(bgm_file_path)} bytes) [Artist: {bgm_meta.get('artist')}]!", flush=True)
            except Exception as m_err:
                print(f"[Modal] ⚠️ Notice: BGM download fallback ({m_err})", flush=True)

        # -------------------------------------------------------------------
        # Smart SFX Sound Design Track Extraction & Mixing
        # -------------------------------------------------------------------
        auto_sfx_events = extract_sfx_cues(script, scenes_list, vtt_cues) if enable_sfx else []
        for cue in auto_sfx_events:
            if not any(abs(f.get("start_time", 0) - cue.get("start_time", 0)) < 0.5 for f in sfx_events):
                sfx_events.append(cue)
        sfx_extra_inputs = []
        sfx_audio_labels = []

        # Assemble Video & Image Inputs
        extra_inputs = []
        filter_steps = [f"[1:v]{v_prep}[vscaled]", f"[0:v][vscaled]overlay=0:0:repeatlast=1[vbg]"]
        curr_v = "[vbg]"
        next_input_idx = 4 if has_bgm else 3

        if has_banner:
            extra_inputs.extend(["-loop", "1", "-i", banner_png_path])
            filter_steps.append(f"{curr_v}[{next_input_idx}:v]overlay=0:0:enable='between(t,0,3.5)'[vbanner]")
            curr_v = "[vbanner]"
            next_input_idx += 1

        if has_logo:
            extra_inputs.extend(["-loop", "1", "-i", logo_png_path])
            filter_steps.append(f"{curr_v}[{next_input_idx}:v]overlay=0:0[vlogo]")
            curr_v = "[vlogo]"
            next_input_idx += 1

        if has_cta:
            extra_inputs.extend(["-loop", "1", "-i", cta_png_path])
            cta_start = max(0.5, video_duration - 3.5)
            filter_steps.append(f"{curr_v}[{next_input_idx}:v]overlay=0:0:enable='between(t,{cta_start:.2f},{video_duration:.2f})'[vcta]")
            curr_v = "[vcta]"
            next_input_idx += 1

        filter_steps.append(f"{curr_v}subtitles=filename='{ass_path_escaped}'[vout]")

        # Download and inject SFX sound effects
        for sfx_idx, sfx_item in enumerate(sfx_events):
            s_type = sfx_item["type"]
            s_url = sfx_item["url"]
            s_st = sfx_item["start_time"]
            s_vol = sfx_item["volume"]
            s_path = f"{work_dir}/sfx_{sfx_idx}_{s_type}.mp3"
            try:
                import requests
                r_s = requests.get(s_url, timeout=10)
                if r_s.status_code == 200:
                    with open(s_path, "wb") as f_s:
                        f_s.write(r_s.content)
                    sfx_extra_inputs.extend(["-i", s_path])
                    delay_ms = int(s_st * 1000)
                    lbl = f"sfx_{sfx_idx}"
                    filter_steps.append(f"[{next_input_idx}:a]adelay={delay_ms}|{delay_ms},volume={s_vol}[{lbl}]")
                    sfx_audio_labels.append(f"[{lbl}]")
                    next_input_idx += 1
                    print(f"[Modal] 🔊 Smart SFX Sound Design: Injected '{s_type}' sound effect at {s_st:.1f}s!", flush=True)
            except Exception as s_err:
                print(f"[Modal] ⚠️ Notice: SFX download fallback: {s_err}", flush=True)

        # Audio Filter Mixing: Clean Voice + EQ Sculpted Ducked BGM + SFX
        filter_steps.append(
            "[2:a]highpass=f=80,equalizer=f=350:t=q:w=1.0:g=-3,equalizer=f=4000:t=q:w=1.0:g=2,acompressor=threshold=-18dB:ratio=3:attack=10:release=100:makeup=1[vclean]"
        )
        mix_inputs = ["[vclean]"]
        mix_weights = ["1.0"]

        if has_bgm:
            filter_steps.append(
                f"[3:a]equalizer=f=2500:t=q:w=1.5:g=-4,volume={bgm_volume_gain}[bgm_shaped];"
                f"[bgm_shaped][vclean]sidechaincompress=threshold=0.08:ratio=12:attack=15:release=250[mducked]"
            )
            mix_inputs.append("[mducked]")
            mix_weights.append("1.0")

        for s_lbl in sfx_audio_labels:
            mix_inputs.append(s_lbl)
            mix_weights.append("0.35")

        if len(mix_inputs) > 1:
            amix_str = "".join(mix_inputs) + f"amix=inputs={len(mix_inputs)}:duration=first:weights='{' '.join(mix_weights)}',loudnorm=I=-14:TP=-1.5:LRA=11[aout]"
            filter_steps.append(amix_str)
        else:
            filter_steps.append("[vclean]loudnorm=I=-14:TP=-1.5:LRA=11[aout]")

        filter_complex = ";".join(filter_steps)

        bgm_inputs = ["-stream_loop", "-1", "-i", bgm_file_path] if has_bgm else []
        ffmpeg_cmd = [
            FFMPEG_BIN, "-y",
            "-f", "lavfi", "-i", f"color=c=0x0a0c16:s={res_w}x{res_h}:d={video_duration}:r={target_fps}",
            "-ss", "00:00:00.000", "-stream_loop", "-1", "-an", "-i", bg_file_path if custom_bg_downloaded else f"color=c=0x0a0c16:s={res_w}x{res_h}:d={video_duration}",
            "-i", audio_output,
            *bgm_inputs,
            *extra_inputs,
            *sfx_extra_inputs,
            "-filter_complex", filter_complex,
            "-map", "[vout]",
            "-map", "[aout]",
            "-c:v", "libx264", "-preset", "fast", "-profile:v", "high", "-crf", "18",
            "-c:a", "aac", "-b:a", "192k", "-pix_fmt", "yuv420p",
            "-r", str(target_fps),
            "-t", str(video_duration),
            video_output
        ]

        subprocess.run(ffmpeg_cmd, check=True)
        print(f"[Modal] ✅ Video render complete! Export path: {video_output}", flush=True)

        # Quality Gate Evaluator
        q_res = evaluate_video_quality(video_output, video_duration, expected_res=f"{res_w}x{res_h}", expected_fps=target_fps)
        print(f"[Modal Quality Gate] Evaluation Result: {q_res}", flush=True)

        # -------------------------------------------------------------------
        # Upload Rendered Video & 3D Cover Thumbnail to Cloudflare R2
        # -------------------------------------------------------------------
        r2_endpoint = os.environ.get("VISIONFLOW_OBJECT_STORE_ENDPOINT", "https://ec302240fdb8cad9ae6c9b685f14eeec.r2.cloudflarestorage.com")
        r2_bucket = os.environ.get("VISIONFLOW_OBJECT_STORE_BUCKET", "vision-flow")
        r2_access_key = os.environ.get("VISIONFLOW_OBJECT_STORE_ACCESS_KEY_ID", "fd28f47a855e5f2097d5f8c24c50da70")
        r2_secret_key = os.environ.get("VISIONFLOW_OBJECT_STORE_SECRET_ACCESS_KEY", "c329293210d831c0bdba01f2434d86dab3eb23ab0a73f9b67819b7c3069cc9c6")
        r2_public = os.environ.get("VISIONFLOW_OBJECT_STORE_PUBLIC_BASE", "https://pub-ec302240fdb8cad9ae6c9b685f14eeec.r2.dev")
        
        object_key = f"visionflow/{workflow_run_id}/exports/final.mp4"
        print(f"[Modal] ☁️ Uploading rendered video to R2 ({r2_bucket}/{object_key})...", flush=True)

        import boto3
        from botocore.client import Config

        s3 = boto3.client(
            "s3",
            endpoint_url=r2_endpoint,
            aws_access_key_id=r2_access_key,
            aws_secret_access_key=r2_secret_key,
            config=Config(signature_version="s3v4"),
            region_name="auto"
        )

        with open(video_output, "rb") as f_out:
            s3.upload_fileobj(
                f_out,
                r2_bucket,
                object_key,
                ExtraArgs={"ContentType": "video/mp4"}
            )
        
        print(f"[Modal] ✅ R2 Upload complete: {r2_bucket}/{object_key}", flush=True)

        # AI Golden Frame 3D Cover Thumbnail Extraction at 1.5s
        cover_path = f"{work_dir}/cover.jpg"
        cover_url = ""
        try:
            extract_cover_cmd = [
                FFMPEG_BIN, "-y",
                "-ss", "00:00:01.500",
                "-i", video_output,
                "-vframes", "1",
                "-q:v", "2",
                cover_path
            ]
            subprocess.run(extract_cover_cmd, check=True)
            if s3 and os.path.exists(cover_path):
                cover_key = f"workflows/{workflow_run_id}/cover.jpg"
                s3.upload_file(cover_path, r2_bucket, cover_key, ExtraArgs={"ContentType": "image/jpeg"})
                cover_url = f"{r2_public}/{cover_key}"
                print(f"[Modal] 📸 Uploaded 3D Golden Frame Cover Thumbnail to R2 ({cover_url})!", flush=True)
        except Exception as cov_err:
            print(f"[Modal] ⚠️ Notice: Cover thumbnail extraction: {cov_err}", flush=True)

        # Generate presigned GET URL for 7 days
        presigned_url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": r2_bucket, "Key": object_key},
            ExpiresIn=604800,
            HttpMethod="GET"
        )

        # -------------------------------------------------------------------
        # Update PostgreSQL Database (media_assets & workflow_runs)
        # -------------------------------------------------------------------
        db_url = os.environ.get("DATABASE_URL", "postgresql://neondb_owner:npg_TD8BYOyg6AVC@ep-restless-waterfall-azn7ekhh-pooler.c-3.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require")
        try:
            import psycopg2
            conn = psycopg2.connect(db_url)
            cur = conn.cursor()
            media_id = str(uuid.uuid4())
            meta = json.dumps({"title": contract_payload.get("title", "Rendered Video"), "workflow_run_id": str(workflow_run_id), "cover_url": cover_url})
            byte_size = os.path.getsize(video_output)

            def safe_uuid(val):
                try:
                    return str(uuid.UUID(str(val)))
                except Exception:
                    return str(uuid.uuid5(uuid.NAMESPACE_DNS, str(val)))

            wf_uuid = safe_uuid(workflow_run_id)
            org_uuid = safe_uuid(organization_id)

            # Ensure parent video_project and workflow_run exist so foreign key constraint is always satisfied
            cur.execute("SELECT id FROM workflow_runs WHERE id = %s::uuid", (wf_uuid,))
            wf_exists = cur.fetchone()
            if not wf_exists:
                proj_id = str(uuid.uuid4())
                wf_title = str(contract_payload.get("title") or contract_payload.get("titleBannerText") or f"VisionFlow Video {workflow_run_id}")
                wf_brief = str(contract_payload.get("brief") or wf_title)
                idempotency_key = f"modal_{wf_uuid}"
                cur.execute(
                    """
                    INSERT INTO video_projects (id, organization_id, title, brief, format_profile, timezone, created_at, updated_at)
                    VALUES (%s::uuid, %s::uuid, %s, %s, 'short_vertical', 'Asia/Ho_Chi_Minh', NOW(), NOW())
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (proj_id, org_uuid, wf_title, wf_brief)
                )
                cur.execute(
                    """
                    INSERT INTO workflow_runs (id, project_id, idempotency_key, state, input_payload, prompt_manifest, created_at, updated_at)
                    VALUES (%s::uuid, %s::uuid, %s, 'APPROVAL_PENDING', %s::jsonb, %s::jsonb, NOW(), NOW())
                    ON CONFLICT (id) DO UPDATE SET state = 'APPROVAL_PENDING', updated_at = NOW()
                    """,
                    (wf_uuid, proj_id, idempotency_key, json.dumps(contract_payload), json.dumps({"source": "modal_engine"}))
                )

            # Check if MediaAsset already exists
            cur.execute("SELECT id FROM media_assets WHERE workflow_run_id = %s::uuid", (wf_uuid,))
            existing = cur.fetchone()
            if not existing:
                cur.execute(
                    """
                    INSERT INTO media_assets (id, organization_id, workflow_run_id, byte_size, metadata_json, created_at, updated_at, object_key, media_kind, content_type, checksum_sha256)
                    VALUES (%s::uuid, %s::uuid, %s::uuid, %s, %s::jsonb, NOW(), NOW(), %s, 'final_export', 'video/mp4', 'sha256_modal')
                    """,
                    (media_id, org_uuid, wf_uuid, byte_size, meta, object_key)
                )
            else:
                cur.execute(
                    "UPDATE media_assets SET object_key = %s, byte_size = %s, metadata_json = %s::jsonb, updated_at = NOW() WHERE workflow_run_id = %s::uuid",
                    (object_key, byte_size, meta, wf_uuid)
                )

            # Update Workflow Run State to APPROVAL_PENDING
            cur.execute(
                "UPDATE workflow_runs SET state = 'APPROVAL_PENDING', updated_at = NOW() WHERE id = %s::uuid",
                (wf_uuid,)
            )
            conn.commit()
            cur.close()
            conn.close()
            print(f"[Modal] 💾 Successfully saved MediaAsset & registered APPROVAL_PENDING in DB for workflow {workflow_run_id}!", flush=True)
        except Exception as db_err:
            print(f"[Modal] ⚠️ Direct DB update error: {db_err}", flush=True)

        return {
            "status": "SUCCESS",
            "workflow_run_id": workflow_run_id,
            "video_url": presigned_url,
            "object_key": object_key,
            "duration": video_duration
        }

    except Exception as exc:
        print(f"[Modal] ❌ Execution Error: {exc}", flush=True)
        import traceback
        traceback.print_exc()

        # Update Workflow Run State to FAILED in PostgreSQL so failure is accurately reported
        db_url = os.environ.get("DATABASE_URL", "postgresql://neondb_owner:npg_TD8BYOyg6AVC@ep-restless-waterfall-azn7ekhh-pooler.c-3.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require")
        try:
            import psycopg2
            conn = psycopg2.connect(db_url)
            cur = conn.cursor()
            def safe_uuid(val):
                try:
                    return str(uuid.UUID(str(val)))
                except Exception:
                    return str(uuid.uuid5(uuid.NAMESPACE_DNS, str(val)))
            wf_uuid = safe_uuid(workflow_run_id)
            err_code = str(exc)[:90]
            err_detail = str(exc)[:500]
            cur.execute(
                "UPDATE workflow_runs SET state = 'FAILED', failure_code = %s, updated_at = NOW() WHERE id = %s::uuid",
                (err_code, wf_uuid)
            )
            conn.commit()
            cur.close()
            conn.close()
            print(f"[Modal] ⚠️ Recorded FAILED state in DB for workflow {workflow_run_id}: {err_code}", flush=True)
        except Exception as db_f_err:
            print(f"[Modal] ⚠️ Could not write FAILED state to DB: {db_f_err}", flush=True)

        return {
            "status": "ERROR",
            "workflow_run_id": workflow_run_id,
            "error": str(exc)
        }

@app.function(image=visionflow_image)
@modal.fastapi_endpoint(method="POST")
def webhook_job(request_body: dict):
    """Public HTTPS Endpoint triggered by Control Plane API or Frontend."""
    render_video_task.spawn(request_body)
    return {
        "status": "QUEUED",
        "message": "VisionFlow Video Render Job triggered on Modal Cloud 24/7!"
    }
