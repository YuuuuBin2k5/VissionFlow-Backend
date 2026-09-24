"""Vendor mapping only. Conservative capabilities are per model/voice family."""
from __future__ import annotations

import asyncio
import base64
import inspect
import os
import re
import time
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape, quoteattr

import requests

from .contracts import DELIVERY_DEFAULT, VoiceError, TransientVoiceError, VoiceRequest, synthesis_text


def capabilities(provider: str, voice_id: str = '', model: str | None = None) -> dict:
    # This describes what THIS adapter implements, not every theoretical vendor feature.
    controls: dict[str, str] = {}
    if provider == 'edge_tts':
        controls = {'pace': 'mapped to rate'}
    elif provider == 'azure' and ':DragonHD' not in voice_id and ':MAI' not in voice_id:
        controls = {'pace': 'mapped to SSML rate', 'pause_strength': 'mapped to paragraph breaks'}
    elif provider == 'elevenlabs' and model == 'eleven_multilingual_v2':
        controls = {'pace': 'mapped to speed', 'energy': 'approximate style mapping'}
    return dict(speed='pace' in controls, pitch=False, volume=False, ssml=provider == 'azure' and bool(controls),
                emotion=False, style_prompt=False, pronunciation_dictionary=False, voice_clone=False,
                semantic_controls=controls, pronunciation_replacement=True)


def _required(name: str) -> str:
    value = os.getenv(name, '').strip()
    if not value:
        raise VoiceError(f'Missing credentials/configuration: {name}')
    return value


def _http(method: str, url: str, **kwargs):
    try:
        response = requests.request(method, url, timeout=(10, 90), allow_redirects=False, **kwargs)
    except (requests.Timeout, requests.ConnectionError):
        raise TransientVoiceError('Provider connection unavailable or timed out') from None
    except requests.RequestException:
        raise VoiceError('Provider request failed') from None
    if response.status_code == 429 or response.status_code in (408, 500, 502, 503, 504):
        raise TransientVoiceError(f'Provider temporarily unavailable (HTTP {response.status_code})')
    if response.status_code in (401, 403):
        raise VoiceError('Provider credentials invalid or access denied')
    if response.status_code >= 300:
        raise VoiceError(f'Provider rejected configuration (HTTP {response.status_code})')
    return response


class Adapter:
    provider = ''

    def config_status(self) -> str:
        return 'Configured'

    def list_voices(self, language: str) -> list[dict]:
        raise NotImplementedError

    async def synthesize(self, request: VoiceRequest, path: str) -> dict:
        raise NotImplementedError


class EdgeAdapter(Adapter):
    provider = 'edge_tts'

    def list_voices(self, language):
        import edge_tts
        voices = asyncio.run(edge_tts.list_voices())
        return [dict(provider_voice_id=v['ShortName'], display_name=v['FriendlyName'], language=v['Locale'],
                     gender_hint=v['Gender'].lower(), capabilities=capabilities(self.provider))
                for v in voices if v['Locale'].lower().startswith(language.lower())]

    async def synthesize(self, request, path):
        import edge_tts
        pace = request.delivery['pace']
        kwargs = {'rate': f'{round((pace - .5) * 40):+d}%'}
        if 'boundary' in inspect.signature(edge_tts.Communicate).parameters:
            kwargs['boundary'] = 'WordBoundary'
        boundaries = []
        try:
            async def generate():
                with open(path, 'wb') as audio:
                    async for chunk in edge_tts.Communicate(synthesis_text(request), request.voice_profile.provider_voice_id, **kwargs).stream():
                        if chunk['type'] == 'audio':
                            audio.write(chunk['data'])
                        elif chunk['type'] in ('WordBoundary', 'SentenceBoundary'):
                            boundaries.append(dict(text=chunk['text'], start_ms=chunk['offset'] // 10000,
                                                   end_ms=(chunk['offset'] + chunk['duration']) // 10000,
                                                   kind=chunk['type']))
            await asyncio.wait_for(generate(), timeout=120)
        except (asyncio.TimeoutError, ConnectionError):
            raise TransientVoiceError('Edge TTS timed out or disconnected') from None
        except Exception:
            # Unknown Edge failures are NOT automatically considered transient.
            raise VoiceError('Edge TTS failed; verify voice and provider availability') from None
        return {'boundaries': boundaries}


class AzureAdapter(Adapter):
    provider = 'azure'

    def _config(self):
        region = _required('AZURE_SPEECH_REGION')
        if not re.fullmatch(r'[a-z0-9-]+', region):
            raise VoiceError('Invalid Azure Speech region')
        return f'https://{region}.tts.speech.microsoft.com', {'Ocp-Apim-Subscription-Key': _required('AZURE_SPEECH_KEY')}

    def config_status(self):
        return 'Configured' if os.getenv('AZURE_SPEECH_KEY') and os.getenv('AZURE_SPEECH_REGION') else 'Missing credentials'

    def list_voices(self, language):
        base, headers = self._config()
        rows = _http('GET', base + '/cognitiveservices/voices/list', headers=headers).json()
        return [dict(provider_voice_id=v['ShortName'], display_name=v['DisplayName'], language=v['Locale'],
                     gender_hint=v.get('Gender', '').lower(), capabilities=capabilities('azure', v['ShortName']))
                for v in rows if v['Locale'].lower().startswith(language.lower())]

    def ssml(self, request):
        profile = request.voice_profile
        supported = capabilities('azure', profile.provider_voice_id)['ssml']
        text = synthesis_text(request)
        if supported:
            pause = round(request.delivery['pause_strength'] * 600)
            body = f'<break time="{pause}ms"/>'.join(escape(p) for p in text.split('\n\n'))
            body = f'<prosody rate="{round((request.delivery["pace"] - .5) * 40):+d}%">{body}</prosody>'
        else:
            body = escape(text)
        return (f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang={quoteattr(profile.language)}>'
                f'<voice name={quoteattr(profile.provider_voice_id)}>{body}</voice></speak>')

    async def synthesize(self, request, path):
        base, headers = self._config()
        headers.update({'Content-Type': 'application/ssml+xml', 'X-Microsoft-OutputFormat': 'audio-24khz-48kbitrate-mono-mp3', 'User-Agent': 'VisionFlow'})
        response = await asyncio.to_thread(_http, 'POST', base + '/cognitiveservices/v1', headers=headers, data=self.ssml(request).encode('utf-8'))
        Path(path).write_bytes(response.content)
        return {'provider_request_id': response.headers.get('X-RequestId')}


class ElevenLabsAdapter(Adapter):
    provider = 'elevenlabs'

    def config_status(self):
        return 'Configured' if os.getenv('ELEVENLABS_API_KEY') else 'Missing credentials'

    def list_voices(self, language):
        # Personal/account catalog only; never import community clones automatically.
        rows = _http('GET', 'https://api.elevenlabs.io/v1/voices', headers={'xi-api-key': _required('ELEVENLABS_API_KEY')}).json()['voices']
        return [dict(provider_voice_id=v['voice_id'], display_name=v['name'], language=language,
                     language_verified=False, capabilities=capabilities('elevenlabs', model='eleven_multilingual_v2')) for v in rows]

    def payload(self, request):
        model = request.voice_profile.provider_model or 'eleven_multilingual_v2'
        if model not in ('eleven_multilingual_v2', 'eleven_v3'):
            raise VoiceError('ElevenLabs model mapping is not implemented')
        body = {'text': synthesis_text(request), 'model_id': model}
        if model == 'eleven_multilingual_v2':
            body['voice_settings'] = {'stability': .5, 'similarity_boost': .75,
                                      'style': round(request.delivery['energy'] * .3, 3),
                                      'speed': round(.85 + request.delivery['pace'] * .3, 3)}
        # v3: no invented directions or unsupported control mapping in V1.
        return body

    async def synthesize(self, request, path):
        response = await asyncio.to_thread(_http, 'POST',
            'https://api.elevenlabs.io/v1/text-to-speech/' + quote(request.voice_profile.provider_voice_id, safe=''),
            headers={'xi-api-key': _required('ELEVENLABS_API_KEY')}, params={'output_format': 'mp3_44100_128'}, json=self.payload(request))
        Path(path).write_bytes(response.content)
        return {'provider_request_id': response.headers.get('request-id')}


class GoogleAdapter(Adapter):
    provider = 'google'

    def config_status(self):
        return 'Configured' if os.getenv('GOOGLE_TTS_API_KEY') else 'Missing credentials'

    def list_voices(self, language):
        rows = _http('GET', 'https://texttospeech.googleapis.com/v1/voices',
                     headers={'X-Goog-Api-Key': _required('GOOGLE_TTS_API_KEY')}, params={'languageCode': language}).json().get('voices', [])
        return [dict(provider_voice_id=v['name'], display_name=v['name'], language=lang,
                     gender_hint=v.get('ssmlGender', '').lower(), capabilities=capabilities('google', v['name']))
                for v in rows for lang in v['languageCodes'] if lang.lower().startswith(language.lower())]

    async def synthesize(self, request, path):
        response = await asyncio.to_thread(_http, 'POST', 'https://texttospeech.googleapis.com/v1/text:synthesize',
            headers={'X-Goog-Api-Key': _required('GOOGLE_TTS_API_KEY')}, json={
                'input': {'text': synthesis_text(request)},
                'voice': {'languageCode': request.voice_profile.language, 'name': request.voice_profile.provider_voice_id},
                'audioConfig': {'audioEncoding': 'MP3'}})
        try:
            audio = base64.b64decode(response.json()['audioContent'], validate=True)
        except (ValueError, KeyError):
            raise VoiceError('Google returned invalid audio') from None
        Path(path).write_bytes(audio)
        return {}


ADAPTERS = {a.provider: a for a in (EdgeAdapter, AzureAdapter, ElevenLabsAdapter, GoogleAdapter)}


class VoiceCatalog:
    """Bounded process-local catalog cache; synthesis never performs discovery."""
    def __init__(self, ttl=900):
        self.ttl = ttl
        self._cache = {}

    def list_voices(self, provider, language):
        if provider not in ADAPTERS:
            raise VoiceError('Provider is not implemented')
        key = (provider, language)
        now = time.monotonic()
        if key not in self._cache or now - self._cache[key][0] >= self.ttl:
            rows = ADAPTERS[provider]().list_voices(language)
            if len(self._cache) >= 64:
                self._cache.clear()
            self._cache[key] = (now, rows)
        return self._cache[key][1]
