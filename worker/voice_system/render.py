"""Render integration for canonical profiles; the legacy renderer remains available."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import subprocess

from .contracts import VoiceError, VoiceProfile, VoiceRequest, resolve_delivery, resolve_profile
from .service import VoiceService, measure_audio


def is_canonical_voice(payload: dict) -> bool:
    voice = payload.get('voice')
    return bool(payload.get('voice_context') or isinstance(voice, dict) and voice.get('profile_id'))


async def synthesize_narration(payload: dict, script: str, output: str, service=None) -> dict:
    context = payload.get('voice_context') or {}
    profiles = {p['id']: VoiceProfile(**p) for p in context.get('profiles', [])}
    voice = payload.get('voice')
    profile = resolve_profile(voice, profiles, context.get('channel'))
    options = voice if isinstance(voice, dict) else {}
    fallback = []
    for key in context.get('fallback_profile_ids', []):
        if key not in profiles:
            raise VoiceError('Fallback profile not found')
        fallback.append(profiles[key])
    scenes = payload.get('scenes') or []
    narrated = [s for s in scenes if isinstance(s, dict) and str(s.get('narration') or '').strip()]
    # Never silently discard full narration if storyboard coverage is incomplete.
    if narrated and ' '.join(' '.join(str(s['narration']).split()) for s in narrated) != ' '.join(script.split()):
        raise VoiceError('Scene narration does not match full script; reconcile before voice rendering')
    if not narrated:
        narrated = [{'narration': script}]
    if len(narrated) > 40:
        raise VoiceError('At most 40 narration scenes are supported')
    service = service or VoiceService()
    results, paths, boundaries = [], [], []
    offset = 0
    active_profile = profile
    for index, scene in enumerate(narrated):
        preset, delivery = resolve_delivery(active_profile, options, context.get('channel'), scene, context.get('presets'))
        request = VoiceRequest(str(scene['narration']), active_profile, delivery, preset,
                               scene.get('role', scene.get('scene_role', '')),
                               context.get('pronunciation', []), f'{payload.get("workflow_run_id", "render")}:{index}')
        path = str(Path(output).with_name(f'voice-scene-{index:03d}.mp3'))
        result = await service.synthesize(request, path, fallback if index == 0 else [])
        # Pin selected voice after scene 1. No mid-video identity changes.
        if result['fallback_used']:
            active_profile = profiles[result['voice_profile_id']]
        decoded = str(Path(path).with_suffix('.wav'))
        try:
            await asyncio.to_thread(subprocess.run,
                ['ffmpeg', '-y', '-v', 'error', '-i', path, '-ar', '24000', '-ac', '1', decoded],
                check=True, capture_output=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            raise VoiceError('Cannot normalize scene narration audio') from None
        result['measured_duration_ms'] = measure_audio(decoded)
        for boundary in result.get('boundaries', []):
            boundaries.append({**boundary, 'start_ms': boundary['start_ms'] + offset, 'end_ms': boundary['end_ms'] + offset})
        offset += result['measured_duration_ms']
        paths.append(decoded)
        results.append(result)
    # Decode + concat to avoid accumulating MP3 encoder delay at segment joins.
    command = ['ffmpeg', '-y', '-v', 'error']
    for path in paths:
        command.extend(['-i', path])
    graph = ''.join(f'[{i}:a]' for i in range(len(paths))) + f'concat=n={len(paths)}:v=0:a=1[out]'
    command.extend(['-filter_complex', graph, '-map', '[out]', '-ar', '24000', '-ac', '1', output])
    try:
        await asyncio.to_thread(subprocess.run, command, check=True, capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        raise VoiceError('Cannot assemble narration audio') from None
    duration = measure_audio(output)
    # Segment container durations can differ from decoded concat duration. Boundary
    # estimates must not be advertised as measured word alignment after assembly.
    return dict(measured_duration_ms=duration, timing_source='ffprobe', scenes=results,
                boundaries=[], warnings=['Canonical narration requires downstream caption alignment; no fabricated word timings'])


def render_narration(payload, script, output, vtt_output):
    result = asyncio.run(synthesize_narration(payload, script, output))
    Path(vtt_output).write_text('WEBVTT\n\n', encoding='utf-8')
    Path(output).with_suffix('.voice.json').write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    return result
