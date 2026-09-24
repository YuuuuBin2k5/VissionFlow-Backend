"""Single synthesis path: adapter -> actual file -> ffprobe -> result."""
from __future__ import annotations

from dataclasses import asdict, replace
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import subprocess
import time
import uuid

from .adapters import ADAPTERS, capabilities
from .contracts import VoiceError, TransientVoiceError, VoiceRequest, VoiceProfile

logger = logging.getLogger(__name__)


def measure_audio(path: str) -> int:
    try:
        output = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration:stream=codec_type',
                                 '-of', 'json', path], capture_output=True, text=True, check=True, timeout=20)
        data = json.loads(output.stdout)
        duration = float(data['format']['duration'])
        if not math.isfinite(duration) or duration <= 0 or not any(s['codec_type'] == 'audio' for s in data['streams']):
            raise ValueError()
        return max(1, round(duration * 1000))
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        raise VoiceError('Cannot measure generated audio; no actual timing is available') from None


def request_fingerprint(request: VoiceRequest) -> str:
    data = asdict(request)
    data.pop('request_id', None)
    return hashlib.sha256(json.dumps({'adapter_revision': 1, 'request': data}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class VoiceService:
    def __init__(self, adapters=None, probe=measure_audio):
        self.adapters = adapters or {name: cls() for name, cls in ADAPTERS.items()}
        self.probe = probe

    async def synthesize(self, request: VoiceRequest, path: str, fallback_profiles: list[VoiceProfile] | None = None) -> dict:
        profiles = [request.voice_profile, *(fallback_profiles or [])]
        if len(profiles) > 4 or len({p.id for p in profiles}) != len(profiles):
            raise VoiceError('Fallback chain must be unique and contain at most four profiles')
        for profile in profiles:
            if not profile.enabled or profile.language != request.voice_profile.language:
                raise VoiceError('Fallback must use an enabled profile with the same language')
            if profile.provider not in self.adapters:
                raise VoiceError('Provider is not implemented')
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        for index, profile in enumerate(profiles):
            current = replace(request, voice_profile=profile)
            temp = destination.with_name(destination.stem + '.' + uuid.uuid4().hex + '.mp3')
            try:
                metadata = await self.adapters[profile.provider].synthesize(current, str(temp))
                duration = self.probe(str(temp))
                os.replace(temp, destination)
                caps = capabilities(profile.provider, profile.provider_voice_id, profile.provider_model or ('eleven_multilingual_v2' if profile.provider == 'elevenlabs' else None))
                warnings = [f'{key}: not mapped by selected voice/model' for key in current.delivery if key not in caps['semantic_controls']]
                if index:
                    warnings.append('Fallback voice used; review narration identity before publishing')
                result = dict(provider=profile.provider, voice_profile_id=profile.id, model=profile.provider_model,
                              preset=request.preset, scene_role=request.scene_role, local_path=str(destination),
                              measured_duration_ms=duration, timing_source='ffprobe', fallback_used=bool(index),
                              warnings=warnings, characters=len(request.text), request_count=index + 1,
                              latency_ms=round((time.monotonic() - started) * 1000),
                              request_fingerprint=request_fingerprint(current), **metadata)
                logger.info('voice_synthesized provider=%s profile=%s duration_ms=%s fallback=%s',
                            profile.provider, profile.id, duration, bool(index))
                return result
            except TransientVoiceError:
                if index == len(profiles) - 1:
                    raise
            finally:
                temp.unlink(missing_ok=True)
        raise VoiceError('Synthesis did not produce audio')
