import asyncio
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import wave

import requests

from worker.voice_system.adapters import AzureAdapter, ElevenLabsAdapter, capabilities, _http, VoiceCatalog
from worker.voice_system.contracts import (
    VoiceError, TransientVoiceError, VoiceProfile, VoiceRequest, SYSTEM_PROFILE,
    resolve_profile, resolve_delivery, synthesis_text,
)
from worker.voice_system.service import VoiceService, measure_audio, request_fingerprint
from worker.voice_system.settings import validate_settings


def request(profile=SYSTEM_PROFILE, **kwargs):
    return VoiceRequest('Xin chào Hubble.', profile, resolve_delivery(profile)[1], **kwargs)


class VoiceContractsTest(unittest.TestCase):
    def test_legacy_object(self):
        p = resolve_profile({'voice_code': 'vi-VN-HoaiMyNeural', 'language': 'vi-VN', 'pace': 'medium'}, {})
        self.assertEqual((p.provider, p.provider_voice_id), ('edge_tts', 'vi-VN-HoaiMyNeural'))

    def test_aliases(self):
        for alias in ('edge-nam-minh', 'edge-nu-hoai-my', 'edge-nu-hoai-an', 'edge-en-ryan'):
            with self.subTest(alias=alias):
                self.assertEqual(resolve_profile(alias, {}).provider, 'edge_tts')

    def test_profile_authority(self):
        p = replace(SYSTEM_PROFILE, id='channel')
        profiles = {'channel': p, SYSTEM_PROFILE.id: SYSTEM_PROFILE}
        channel = {'voice_profile_id': p.id}
        self.assertEqual(resolve_profile({'profile_id': SYSTEM_PROFILE.id}, profiles, channel), SYSTEM_PROFILE)
        self.assertEqual(resolve_profile(None, profiles, channel), p)
        self.assertEqual(resolve_profile(None, profiles), SYSTEM_PROFILE)

    def test_invalid_not_fallback(self):
        for value in ({'profile_id': 'missing'}, 'invented-voice', {'voice_code': {'voice': 'bad'}}, 12):
            with self.subTest(value=value), self.assertRaises(VoiceError):
                resolve_profile(value, {})

    def test_disabled(self):
        with self.assertRaises(VoiceError):
            resolve_profile({'profile_id': 'off'}, {'off': replace(SYSTEM_PROFILE, id='off', enabled=False)})

    def test_preset_authority(self):
        p = replace(SYSTEM_PROFILE, default_preset_id='dark_history')
        _, d = resolve_delivery(p, {'preset': 'urgent_news', 'delivery': {'pace': .4}}, scene={'role': 'hook', 'voice_delivery': {'pace': .2}})
        self.assertEqual(d['pace'], .2)
        self.assertAlmostEqual(d['energy'], .7)

    def test_roles_subtle(self):
        hook = resolve_delivery(SYSTEM_PROFILE, scene={'role': 'hook'})[1]
        payoff = resolve_delivery(SYSTEM_PROFILE, scene={'role': 'payoff'})[1]
        self.assertGreater(hook['pace'], payoff['pace'])
        self.assertLess(abs(hook['pace'] - payoff['pace']), .15)

    def test_invalid_delivery(self):
        for value in (-1, 2, float('nan'), float('inf'), True, 'fast'):
            with self.subTest(value=value), self.assertRaises(VoiceError):
                resolve_delivery(SYSTEM_PROFILE, {'delivery': {'pace': value}})

    def test_pronunciation_copy(self):
        r = request(pronunciation=[{'token': 'Hubble', 'replacement': 'Hắp bồ'}])
        self.assertEqual(synthesis_text(r), 'Xin chào Hắp bồ.')
        self.assertEqual(r.text, 'Xin chào Hubble.')

    def test_pronunciation_not_recursive_or_substring(self):
        r = replace(request(), text='WIMP WIMPs', pronunciation=[{'token': 'WIMP', 'replacement': 'weak'}, {'token': 'weak', 'replacement': 'wrong'}])
        self.assertEqual(synthesis_text(r), 'weak WIMPs')

    def test_cache_changes_for_every_voice_setting(self):
        r = request()
        self.assertEqual(request_fingerprint(r), request_fingerprint(replace(r, request_id='retry')))
        for changed in (replace(r, text='khác'), replace(r, delivery={**r.delivery, 'pace': .6}),
                        replace(r, voice_profile=replace(SYSTEM_PROFILE, provider_voice_id='vi-VN-HoaiMyNeural'))):
            self.assertNotEqual(request_fingerprint(r), request_fingerprint(changed))

    def test_settings_reject_secrets_and_dangling_ids(self):
        for config in ({'api_key': 'must-not-store'}, {'channels': {'x': {'voice_profile_id': 'bad'}}}, {'fallback_profile_ids': ['missing']}):
            with self.subTest(config=config), self.assertRaises(VoiceError):
                validate_settings(config)

    def test_settings_normalized(self):
        result = validate_settings({'profiles': [SYSTEM_PROFILE.to_dict()], 'channels': {'my-channel': {'voice_profile_id': SYSTEM_PROFILE.id}}})
        self.assertEqual(result['channels']['my-channel']['voice_profile_id'], SYSTEM_PROFILE.id)


class AdapterMappingTest(unittest.TestCase):
    def test_azure_ssml_escaped(self):
        r = replace(request(), text='<script>&\n\nhello', voice_profile=replace(SYSTEM_PROFILE, provider='azure'))
        body = AzureAdapter().ssml(r)
        self.assertIn('&lt;script&gt;&amp;', body)
        self.assertIn('<break', body)
        self.assertNotIn('express-as', body)

    def test_eleven_mapping_v2(self):
        p = VoiceProfile('eleven', 'Test', 'elevenlabs', 'test-id', provider_model='eleven_multilingual_v2')
        body = ElevenLabsAdapter().payload(request(p))
        self.assertEqual(body['voice_settings']['speed'], 1.)
        self.assertNotIn('pitch', body['voice_settings'])

    def test_v3_no_invented_controls(self):
        p = VoiceProfile('eleven', 'Test', 'elevenlabs', 'test-id', provider_model='eleven_v3')
        self.assertNotIn('voice_settings', ElevenLabsAdapter().payload(request(p)))
        self.assertFalse(capabilities('elevenlabs', model='eleven_v3')['speed'])

    def test_google_conservative(self):
        self.assertEqual(capabilities('google')['semantic_controls'], {})

    def test_http_error_classification_and_redaction(self):
        for code in (400, 401, 403, 404, 422, 429, 500, 503):
            response = requests.Response()
            response.status_code, response._content = code, b'credential=SHOULD_NOT_ESCAPE'
            expected = TransientVoiceError if code in (429, 500, 503) else VoiceError
            with self.subTest(code=code), patch('worker.voice_system.adapters.requests.request', return_value=response):
                with self.assertRaises(expected) as error:
                    _http('POST', 'https://example.invalid')
                self.assertNotIn('SHOULD_NOT_ESCAPE', str(error.exception))
                if code < 429:
                    self.assertNotIsInstance(error.exception, TransientVoiceError)

    def test_discovery_cached(self):
        with patch('worker.voice_system.adapters.EdgeAdapter.list_voices', return_value=[]) as listing:
            cache = VoiceCatalog()
            cache.list_voices('edge_tts', 'vi-VN')
            cache.list_voices('edge_tts', 'vi-VN')
            self.assertEqual(listing.call_count, 1)


class ServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_transient_fallback_only(self):
        calls = []
        class Fail:
            async def synthesize(self, r, path):
                calls.append('primary')
                raise TransientVoiceError('timeout')
        class Good:
            async def synthesize(self, r, path):
                calls.append('fallback')
                Path(path).write_bytes(b'audio')
                return {}
        primary = replace(SYSTEM_PROFILE, provider='azure')
        fallback = replace(SYSTEM_PROFILE, id='fallback')
        service = VoiceService({'azure': Fail(), 'edge_tts': Good()}, probe=lambda _: 1234)
        with tempfile.TemporaryDirectory() as directory:
            result = await service.synthesize(request(primary), str(Path(directory) / 'audio.mp3'), [fallback])
        self.assertEqual(calls, ['primary', 'fallback'])
        self.assertTrue(result['fallback_used'])
        self.assertEqual(result['measured_duration_ms'], 1234)

    async def test_configuration_error_no_fallback_or_overwrite(self):
        class Bad:
            async def synthesize(self, r, path):
                Path(path).write_bytes(b'invalid')
                raise VoiceError('invalid voice')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'audio.mp3'
            path.write_bytes(b'original')
            with self.assertRaises(VoiceError):
                await VoiceService({'edge_tts': Bad()}).synthesize(request(), str(path))
            self.assertEqual(path.read_bytes(), b'original')
            self.assertEqual(len(list(Path(directory).iterdir())), 1)

    async def test_probe_failure_is_not_provider_fallback(self):
        class Good:
            async def synthesize(self, r, path):
                Path(path).write_bytes(b'bad-audio')
                return {}
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(VoiceError):
            await VoiceService({'edge_tts': Good()}).synthesize(request(), str(Path(directory) / 'audio.mp3'))


class ActualTimingTest(unittest.TestCase):
    def test_real_ffprobe(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'audio.wav')
            with wave.open(path, 'wb') as stream:
                stream.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
                stream.writeframes(b'\0\0' * 24000)
            self.assertEqual(measure_audio(path), 1000)

    def test_missing_audio_not_estimated(self):
        with self.assertRaises(VoiceError):
            measure_audio('missing-file-voice-test.mp3')


if __name__ == '__main__':
    unittest.main()
