"""
TTS Subsystem for VisionFlow Auto Production System (Phase 5 - Section 3, 4)
Integrates voice synthesis, ffprobe duration measurement, and word-level timestamps.

Invariant:
actual_duration_seconds MUST be measured downstream via ffprobe.
Estimated speech duration is strictly provisional for preliminary visual planning.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
import re
import shutil
import struct
import subprocess
import wave
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from worker.config.render_profile import resolve_ffprobe_exe

logger = logging.getLogger("visionflow.production.tts_service")

CACHE_DIR = Path(os.getenv("VISIONFLOW_MEDIA_CACHE", ".media_cache/tts")).resolve()
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def measure_audio_duration_ffprobe(file_path: Path | str) -> float:
    """
    Measures the exact duration in seconds of an audio file using ffprobe.
    CANONICAL TIMING SOURCE for all downstream Editor Planning and Timeline assembly.
    """
    path_obj = Path(file_path)
    if not path_obj.exists():
        raise FileNotFoundError(f"Audio file not found for ffprobe: {file_path}")

    exe = resolve_ffprobe_exe().strip('"')

    # Try direct duration probe
    try:
        cmd = [
            exe,
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path_obj.resolve()),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode == 0 and result.stdout.strip():
            val = float(result.stdout.strip())
            if val > 0:
                return round(val, 3)
    except Exception as e:
        logger.warning(f"ffprobe direct probe error on {file_path}: {e}")

    # Fallback to json output probe
    try:
        cmd = [
            exe,
            "-v", "error",
            "-show_entries", "format=duration:stream=duration",
            "-of", "json",
            str(path_obj.resolve()),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode == 0:
            payload = json.loads(result.stdout)
            format_dur = payload.get("format", {}).get("duration")
            if format_dur:
                return round(float(format_dur), 3)
            streams = payload.get("streams", [])
            for st in streams:
                if st.get("duration"):
                    return round(float(st["duration"]), 3)
    except Exception as e:
        logger.warning(f"ffprobe JSON probe error on {file_path}: {e}")

    # WAV header inspection fallback if ffprobe failed
    if path_obj.suffix.lower() == ".wav":
        try:
            with wave.open(str(path_obj), "rb") as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                if rate > 0:
                    return round(frames / float(rate), 3)
        except Exception:
            pass

    raise RuntimeError(f"Could not determine audio duration via ffprobe for: {file_path}")


def create_synthetic_wav(file_path: Path | str, duration_sec: float, sample_rate: int = 24000) -> float:
    """
    Creates a valid PCM WAV audio file with exact duration for offline testing and deterministic CI.
    Produces a 100% compliant WAV file readable by ffprobe and all audio decoders.
    """
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    num_samples = int(duration_sec * sample_rate)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)  # Mono
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        # Fill with gentle low-volume tone (440Hz)
        data = bytearray()
        for i in range(num_samples):
            val = int(1000 * math.sin(2 * math.pi * 440 * i / sample_rate))
            data.extend(struct.pack("<h", val))
        wf.writeframes(data)

    return round(duration_sec, 3)


class SceneTTSResult(BaseModel):
    """Structured result of TTS generation per narration scene."""
    scene_id: str
    audio_asset_id: str
    audio_file_path: str
    actual_duration_seconds: float = Field(ge=0.0)
    provider: str
    voice_code: str
    voice_rate: float
    word_timestamps: List[Dict[str, Any]] = Field(default_factory=list)
    measured_at: Optional[datetime] = None


class TTSVoiceProvider(ABC):
    @abstractmethod
    async def synthesize_narration(
        self,
        scene_id: str,
        text: str,
        voice_code: str,
        voice_rate: float,
        output_dir: Path,
    ) -> SceneTTSResult:
        pass


class DeterministicMockTTSProvider(TTSVoiceProvider):
    """
    Deterministic offline TTS generator for automated tests and CI.
    Generates genuine WAV files and real word timestamps without network latency or external API keys.
    """

    async def synthesize_narration(
        self,
        scene_id: str,
        text: str,
        voice_code: str,
        voice_rate: float,
        output_dir: Path,
    ) -> SceneTTSResult:
        clean_text = re.sub(r"\[[^\]]+\]", "", text).strip()
        words = clean_text.split()
        word_count = len(words)

        # Baseline speaking rate: 3.2 words per second in Vietnamese divided by rate
        nominal_dur = max(1.2, round((word_count / (3.2 * max(0.5, voice_rate))), 3))

        audio_asset_id = f"aud_{scene_id}_{abs(hash(text)) % 1000000:06d}"
        output_path = output_dir / f"{audio_asset_id}.wav"

        create_synthetic_wav(output_path, nominal_dur)

        # Strictly measure via ffprobe
        actual_dur = measure_audio_duration_ffprobe(output_path)

        # Generate proportional word timestamps
        word_timestamps = []
        curr_time = 0.0
        time_per_word = actual_dur / max(1, word_count)

        for w in words:
            w_start_ms = int(curr_time * 1000)
            curr_time += time_per_word
            w_end_ms = int(curr_time * 1000)
            cleaned_word = w.strip(".,!?;:\"'()[]{}“”")
            if cleaned_word:
                word_timestamps.append({
                    "word": cleaned_word,
                    "start_ms": w_start_ms,
                    "end_ms": w_end_ms,
                })

        return SceneTTSResult(
            scene_id=scene_id,
            audio_asset_id=audio_asset_id,
            audio_file_path=str(output_path.resolve()),
            actual_duration_seconds=actual_dur,
            provider="deterministic_mock",
            voice_code=voice_code,
            voice_rate=voice_rate,
            word_timestamps=word_timestamps,
            measured_at=datetime.now(timezone.utc),
        )


class EdgeTTSVoiceProvider(TTSVoiceProvider):
    """
    Microsoft Edge-TTS Voice Provider (Production Default).
    Reuses existing worker.services.tts_providers.edge_tts_provider.EdgeTTSProvider.
    """

    def __init__(self):
        from worker.services.tts_providers.edge_tts_provider import EdgeTTSProvider
        self._provider = EdgeTTSProvider()
        self._mock_fallback = DeterministicMockTTSProvider()

    async def synthesize_narration(
        self,
        scene_id: str,
        text: str,
        voice_code: str,
        voice_rate: float,
        output_dir: Path,
    ) -> SceneTTSResult:
        # If in offline test environment, use deterministic mock
        if os.getenv("VISIONFLOW_USE_DEV_REPOSITORIES") == "1" and os.getenv("VISIONFLOW_ALLOW_TEST_TTS") == "1":
            return await self._mock_fallback.synthesize_narration(
                scene_id=scene_id,
                text=text,
                voice_code=voice_code,
                voice_rate=voice_rate,
                output_dir=output_dir,
            )

        fingerprint = hashlib.sha256(f'{text}\0{voice_code}\0{voice_rate}'.encode()).hexdigest()[:16]
        audio_asset_id = f"aud_{scene_id}_{fingerprint}"
        output_path = output_dir / f"{audio_asset_id}.mp3"

        rate_str = f"{int((voice_rate - 1.0) * 100):+d}%"
        voice_profile = {"voice": voice_code, "rate": rate_str}

        try:
            word_timestamps = await self._provider.synthesize(
                text=text,
                output_path=str(output_path),
                voice_profile=voice_profile,
            )
            actual_dur = measure_audio_duration_ffprobe(output_path)

            return SceneTTSResult(
                scene_id=scene_id,
                audio_asset_id=audio_asset_id,
                audio_file_path=str(output_path.resolve()),
                actual_duration_seconds=actual_dur,
                provider="edge_tts",
                voice_code=voice_code,
                voice_rate=voice_rate,
                word_timestamps=word_timestamps,
                measured_at=datetime.now(timezone.utc),
            )
        except Exception as e:
            logger.warning('EdgeTTS failed: %s', type(e).__name__)
            raise RuntimeError('TTS_PROVIDER_UNAVAILABLE') from None


class TTSService:
    """
    Main TTS Coordination Service for Auto Production Pipeline.
    Generates audio for each SceneNarration and measures actual durations via ffprobe.
    """

    def __init__(self, provider: Optional[TTSVoiceProvider] = None):
        self.provider = provider or EdgeTTSVoiceProvider()

    async def synthesize_script(
        self,
        scenes: List[Any],
        voice_code: str = "vi-VN-NamMinhNeural",
        voice_rate: float = 1.0,
        run_id: str = "run_default",
    ) -> List[SceneTTSResult]:
        """
        Synthesizes speech audio for each scene in parallel/sequence and measures actual durations.
        """
        run_output_dir = CACHE_DIR / run_id
        run_output_dir.mkdir(parents=True, exist_ok=True)

        results: List[SceneTTSResult] = []

        for scn in scenes:
            scene_id = getattr(scn, "scene_id", None) or f"scene_{getattr(scn, 'scene_index', 1):03d}"
            narration = getattr(scn, "narration", "")

            tts_res = await self.provider.synthesize_narration(
                scene_id=scene_id,
                text=narration,
                voice_code=voice_code,
                voice_rate=voice_rate,
                output_dir=run_output_dir,
            )
            results.append(tts_res)

        return results


# Global singleton
tts_service = TTSService()
