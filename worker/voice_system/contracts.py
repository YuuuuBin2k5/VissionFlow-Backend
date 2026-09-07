"""Provider-neutral voice identity and delivery. Secrets never belong here."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
import re
from typing import Any


class VoiceError(ValueError):
    """Safe, user-visible error; never contains vendor response bodies."""


class TransientVoiceError(VoiceError):
    """Only this category permits a configured fallback."""


PROVIDERS = {'edge_tts', 'azure', 'elevenlabs', 'google'}
DELIVERY_DEFAULT = dict(pace=.5, energy=.5, warmth=.5, tension=.5, clarity=.8,
                        pause_strength=.5, emphasis_strength=.5)
PRESETS = {
    'mystery_documentary': dict(pace=.45, energy=.4, warmth=.5, tension=.72, clarity=.9, pause_strength=.75),
    'science_explainer': dict(pace=.52, energy=.55, warmth=.5, tension=.3, clarity=.95, pause_strength=.45),
    'dark_history': dict(pace=.43, energy=.4, warmth=.4, tension=.7, clarity=.9, pause_strength=.7),
    'reflective_psychology': dict(pace=.44, energy=.35, warmth=.7, tension=.3, clarity=.85, pause_strength=.7),
    'neutral_documentary': dict(pace=.5, energy=.5, warmth=.5, tension=.5, clarity=.8, pause_strength=.5),
    'urgent_news': dict(pace=.6, energy=.65, warmth=.4, tension=.6, clarity=.95, pause_strength=.35),
}
ROLE_MODIFIERS = {
    'hook': dict(pace=.04, tension=.06, energy=.05), 'context': {},
    'evidence': dict(clarity=.05, tension=-.04),
    'reveal': dict(pace=-.04, pause_strength=.07, emphasis_strength=.05),
    'twist': dict(pace=-.04, tension=.07, pause_strength=.08),
    'explanation': dict(clarity=.06),
    'uncertainty': dict(pace=-.03, energy=-.04, warmth=.03),
    'payoff': dict(pace=-.04, warmth=.06, tension=-.06, pause_strength=.06),
}
LEGACY_ALIASES = {
    'edge-nam-minh': 'vi-VN-NamMinhNeural',
    'edge-hoai-my': 'vi-VN-HoaiMyNeural',
    'edge-nu-hoai-my': 'vi-VN-HoaiMyNeural',
    'edge-nu-hoai-an': 'vi-VN-HoaiMyNeural',
    'edge-vi-andrew': 'en-US-AndrewMultilingualNeural',
    'edge-vi-ava': 'en-US-AvaMultilingualNeural',
    'edge-en-andrew': 'en-US-AndrewNeural',
    'edge-en-ava': 'en-US-AvaNeural',
    'edge-en-ryan': 'en-GB-RyanNeural',
    'edge-en-guy': 'en-US-GuyNeural', 'edge-en-jenny': 'en-US-JennyNeural',
    'edge-en-christopher': 'en-US-ChristopherNeural',
}


@dataclass(frozen=True)
class VoiceProfile:
    id: str
    name: str
    provider: str
    provider_voice_id: str
    language: str = 'vi-VN'
    provider_model: str | None = None
    default_preset_id: str = 'neutral_documentary'
    enabled: bool = True

    def __post_init__(self):
        if self.provider not in PROVIDERS:
            raise VoiceError('Provider is not implemented')
        for value in (self.id, self.name, self.provider_voice_id, self.language):
            if not isinstance(value, str) or not value.strip() or len(value) > 240:
                raise VoiceError('Invalid voice profile field')
        if not re.fullmatch(r'[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*', self.language):
            raise VoiceError('Invalid language tag')
        if self.provider in ('edge_tts', 'azure') and not re.fullmatch(r'[a-z]{2,3}-[A-Z]{2}-[A-Za-z0-9:]+Neural', self.provider_voice_id):
            raise VoiceError('Invalid Microsoft voice identifier')

    def to_dict(self):
        return asdict(self)


SYSTEM_PROFILE = VoiceProfile('system-edge-vi', 'Vietnamese baseline', 'edge_tts', 'vi-VN-NamMinhNeural')


def legacy_profile(raw: str | dict) -> VoiceProfile:
    language = raw.get('language') if isinstance(raw, dict) else None
    code = (raw.get('voice_code') or raw.get('voiceCode')) if isinstance(raw, dict) else raw
    if not isinstance(code, str) or not code.strip():
        raise VoiceError('voice_code must be a voice identifier string')
    code = LEGACY_ALIASES.get(code.strip(), code.strip())
    if code in ('adam', 'eleven-adam'):
        return VoiceProfile('legacy-eleven-adam', 'Adam', 'elevenlabs', 'pNInz6obpgDQGcFmaJgB', language or 'en-US', 'eleven_multilingual_v2')
    return VoiceProfile('legacy-' + code, code, 'edge_tts', code, language or '-'.join(code.split('-')[:2]))


def resolve_profile(voice: str | dict | None, profiles: dict[str, VoiceProfile],
                    channel: dict | None = None, system: VoiceProfile = SYSTEM_PROFILE) -> VoiceProfile:
    channel = channel or {}
    if isinstance(voice, str):
        profile = legacy_profile(voice)
    elif voice is not None and not isinstance(voice, dict):
        raise VoiceError('voice must be an object or legacy identifier')
    elif voice and voice.get('profile_id'):
        profile = profiles.get(voice['profile_id'])
        if profile is None:
            raise VoiceError('Voice profile not found in this organization')
    elif voice and (voice.get('voice_code') or voice.get('voiceCode')):
        profile = legacy_profile(voice)
    elif channel.get('voice_profile_id'):
        profile = profiles.get(channel['voice_profile_id'])
        if profile is None:
            raise VoiceError('Channel voice profile not found')
    else:
        profile = system
    if not profile.enabled:
        raise VoiceError('Voice profile is disabled')
    if isinstance(voice, dict) and voice.get('language') and voice['language'] != profile.language:
        raise VoiceError('Voice profile language does not match requested language')
    return profile


def validate_delivery(values: dict) -> dict[str, float]:
    if not isinstance(values, dict) or set(values) - DELIVERY_DEFAULT.keys():
        raise VoiceError('Unknown delivery controls')
    result = {}
    for key, value in values.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
            raise VoiceError(f'{key} must be a finite number from 0 to 1')
        result[key] = float(value)
    return result


def validate_selection(value):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) - {'profile_id', 'use_channel_default', 'preset', 'delivery', 'language'}:
        raise VoiceError('Unknown voice selection fields')
    if value.get('profile_id') and value.get('use_channel_default'):
        raise VoiceError('Choose an explicit profile or channel default, not both')
    for key in ('profile_id', 'preset', 'language'):
        if key in value and (not isinstance(value[key], str) or not value[key].strip() or len(value[key]) > 240):
            raise VoiceError('Invalid voice selection')
    if 'use_channel_default' in value and not isinstance(value['use_channel_default'], bool):
        raise VoiceError('use_channel_default must be boolean')
    validate_delivery(value.get('delivery', {}))
    return dict(value)


def resolve_delivery(profile: VoiceProfile, voice: dict | None = None, channel: dict | None = None,
                     scene: dict | None = None, presets: dict | None = None) -> tuple[str, dict]:
    voice, channel, scene = voice or {}, channel or {}, scene or {}
    catalog = {**PRESETS, **(presets or {})}
    preset = voice.get('preset') or channel.get('default_preset_id') or profile.default_preset_id
    # A channel preset must not override an explicitly selected different profile.
    if voice.get('profile_id') and voice['profile_id'] != channel.get('voice_profile_id') and not voice.get('preset'):
        preset = profile.default_preset_id
    if voice.get('style') == 'calm_documentary' and not voice.get('preset'):
        preset = 'neutral_documentary'
    if preset not in catalog:
        raise VoiceError('Unknown voice preset')
    delivery = {**DELIVERY_DEFAULT, **validate_delivery(catalog[preset])}
    legacy_pace = voice.get('pace')
    if legacy_pace is not None:
        if legacy_pace not in ('slow', 'medium', 'fast'):
            raise VoiceError('Unknown legacy pace')
        delivery['pace'] = {'slow': .35, 'medium': .5, 'fast': .65}[legacy_pace]
    delivery.update(validate_delivery(voice.get('delivery', {})))
    for key, delta in ROLE_MODIFIERS.get(scene.get('role', scene.get('scene_role', '')), {}).items():
        delivery[key] = max(0., min(1., delivery[key] + delta))
    delivery.update(validate_delivery(scene.get('voice_delivery', {})))
    return preset, delivery


@dataclass(frozen=True)
class VoiceRequest:
    text: str
    voice_profile: VoiceProfile
    delivery: dict[str, float]
    preset: str = 'neutral_documentary'
    scene_role: str = ''
    pronunciation: list[dict[str, str]] = field(default_factory=list)
    request_id: str = ''

    def __post_init__(self):
        if not isinstance(self.text, str) or not self.text.strip() or len(self.text) > 10000:
            raise VoiceError('Narration must contain 1 to 10000 characters per request')
        validate_delivery(self.delivery)
        if not self.voice_profile.enabled:
            raise VoiceError('Voice profile is disabled')
        for entry in self.pronunciation:
            if not isinstance(entry, dict) or not entry.get('token') or not entry.get('replacement'):
                raise VoiceError('This version requires a pronunciation token and text replacement')
            if any(not isinstance(v, str) or len(v) > 240 for v in entry.values()):
                raise VoiceError('Invalid pronunciation entry')


def synthesis_text(request: VoiceRequest) -> str:
    """Single-pass replacement on a copy; never mutate narration/caption sources."""
    entries = {e['token']: e['replacement'] for e in request.pronunciation
               if not e.get('language') or e['language'] == request.voice_profile.language}
    if not entries:
        return request.text
    pattern = r'(?<!\w)(?:' + '|'.join(re.escape(k) for k in sorted(entries, key=len, reverse=True)) + r')(?!\w)'
    return re.sub(pattern, lambda m: entries[m.group()], request.text)
