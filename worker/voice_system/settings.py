"""Validated configuration snapshots; small JSON document, no credential fields."""
from .contracts import PRESETS, VoiceError, VoiceProfile, validate_delivery


def validate_settings(config):
    if not isinstance(config, dict) or set(config) - {'profiles', 'presets', 'channels', 'fallback_profile_ids', 'pronunciation'}:
        raise VoiceError('Unknown voice settings fields; secrets must use environment storage')
    profiles = [VoiceProfile(**p) for p in config.get('profiles', [])]
    if len(profiles) > 100 or len({p.id for p in profiles}) != len(profiles):
        raise VoiceError('Profiles must have unique IDs; maximum 100')
    by_id = {p.id: p for p in profiles}
    presets = config.get('presets', {})
    if len(presets) > 50:
        raise VoiceError('Maximum 50 custom presets')
    for value in presets.values():
        validate_delivery(value)
    preset_ids = PRESETS.keys() | presets.keys()
    for profile in profiles:
        if profile.default_preset_id not in preset_ids:
            raise VoiceError('Profile default preset does not exist')
    channels = config.get('channels', {})
    if not isinstance(channels, dict) or len(channels) > 100:
        raise VoiceError('Invalid channel preferences')
    for key, channel in channels.items():
        if not isinstance(key, str) or not key or len(key) > 160 or set(channel) - {'voice_profile_id', 'default_preset_id'}:
            raise VoiceError('Invalid channel preference')
        if channel.get('voice_profile_id') not in by_id or not by_id[channel['voice_profile_id']].enabled:
            raise VoiceError('Channel must reference an enabled profile')
        if channel.get('default_preset_id') and channel['default_preset_id'] not in preset_ids:
            raise VoiceError('Channel preset does not exist')
    fallback = config.get('fallback_profile_ids', [])
    if len(fallback) > 3 or len(set(fallback)) != len(fallback) or any(k not in by_id or not by_id[k].enabled for k in fallback):
        raise VoiceError('Invalid fallback profile chain')
    pronunciation = config.get('pronunciation', [])
    if not isinstance(pronunciation, list) or len(pronunciation) > 100:
        raise VoiceError('Maximum 100 pronunciation replacements')
    for entry in pronunciation:
        if not isinstance(entry, dict) or set(entry) - {'token', 'replacement', 'language'} or not entry.get('token') or not entry.get('replacement'):
            raise VoiceError('Pronunciation V1 supports token, replacement and optional language only')
        if any(not isinstance(v, str) or len(v) > 240 for v in entry.values()):
            raise VoiceError('Invalid pronunciation replacement')
    return dict(profiles=[p.to_dict() for p in profiles], presets=presets, channels=channels,
                fallback_profile_ids=fallback, pronunciation=pronunciation)


def render_context(config, channel_id):
    return {**{k: v for k, v in config.items() if k != 'channels'},
            'channel': config.get('channels', {}).get(str(channel_id), {})}
