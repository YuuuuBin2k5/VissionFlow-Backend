"""Authenticated control-plane handoff for billable voice rendering."""
import hashlib
import hmac
import json
import os
import time

from .contracts import VoiceError


def _digest(payload):
    secret = os.getenv('VISIONFLOW_VOICE_DISPATCH_SECRET', '')
    if len(secret) < 32:
        raise VoiceError('Voice dispatch secret is not configured')
    data = {k: v for k, v in payload.items() if k != '_voice_signature'}
    return hmac.new(secret.encode(), json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode(), hashlib.sha256).hexdigest()


def sign_dispatch(payload):
    result = {**payload, '_voice_expires_at': int(time.time()) + 600}
    result['_voice_signature'] = _digest(result)
    return result


def verify_dispatch(payload):
    try:
        expires = int(payload.get('_voice_expires_at', 0))
        return time.time() <= expires <= time.time() + 610 and hmac.compare_digest(str(payload.get('_voice_signature', '')), _digest(payload))
    except (VoiceError, ValueError, TypeError):
        return False
