"""Resolve organization-owned configuration once at workflow creation."""
import os

from app.infrastructure.models import VoiceSettings
from worker.voice_system.contracts import VoiceError, VoiceProfile, resolve_profile, resolve_delivery, validate_selection
from worker.voice_system.settings import render_context


def attach_voice_context(session, organization_id, payload):
    result = dict(payload)
    # Never trust client-supplied profile snapshots (cross-tenant IDs/secret fields).
    result.pop('voice_context', None)
    voice = result.get('voice')
    canonical = isinstance(voice, dict) and ('profile_id' in voice or voice.get('use_channel_default'))
    if canonical:
        validate_selection(voice)
    if os.getenv('VISIONFLOW_VOICE_SYSTEM_ENABLED', 'false').lower() != 'true':
        if canonical:
            raise VoiceError('Voice System is not enabled')
        return result
    row = session.get(VoiceSettings, organization_id)
    config = row.config if row else {}
    context = render_context(config, result.get('channel_id', ''))
    explicit_legacy = result.get('voice_code') or isinstance(voice, str) and voice
    if not canonical and (explicit_legacy or not context['channel']):
        return result
    profiles = {p['id']: VoiceProfile(**p) for p in context.get('profiles', [])}
    profile = resolve_profile(voice if canonical else None, profiles, context['channel'])
    options = {k: v for k, v in (voice or {}).items() if k != 'use_channel_default'} if canonical else {}
    preset, delivery = resolve_delivery(profile, options, context['channel'], presets=context.get('presets'))
    for key in context.get('fallback_profile_ids', []):
        if profiles[key].language != profile.language:
            raise VoiceError('Fallback profile language must match selected voice')
    context['fallback_profile_ids'] = [key for key in context.get('fallback_profile_ids', []) if key != profile.id]
    if profile.id not in profiles:
        context['profiles'] = [*context.get('profiles', []), profile.to_dict()]
    result['voice'] = {**options, 'profile_id': profile.id, 'preset': preset}
    result['voice_context'] = context
    result.pop('voice_code', None)
    return result
