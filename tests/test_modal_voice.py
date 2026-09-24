import unittest

import edge_tts
from modal_worker import normalize_psycopg_dsn, resolve_voice


class ModalVoiceTests(unittest.TestCase):
    def test_reported_structured_voice_is_accepted_by_edge_tts(self):
        voice = {'language':'vi-VN','voice_code':'vi-VN-HoaiMyNeural',
                 'style':'calm_documentary','pace':'medium'}
        resolved = resolve_voice(voice)
        self.assertEqual('vi-VN-HoaiMyNeural', resolved)
        # The real provider validates voice before any network operation.
        edge_tts.Communicate('Xin chào.', resolved, rate='+6%', pitch='-10Hz')
        self.assertEqual('calm_documentary', voice['style'])

    def test_legacy_and_structured_aliases(self):
        for value in ('edge-nam-minh', {'voice_code':'edge-nam-minh'},
                      {'voiceCode':'edge-nam-minh'}, None, {}):
            with self.subTest(value=value):
                self.assertEqual('vi-VN-NamMinhNeural', resolve_voice(value))

    def test_english_native_voice(self):
        self.assertEqual('en-US-AndrewMultilingualNeural', resolve_voice('en-US-AndrewMultilingualNeural'))

    def test_invalid_nested_voice_type_is_rejected(self):
        with self.assertRaises(ValueError):
            resolve_voice({'voice_code':{'unexpected':'vi-VN-HoaiMyNeural'}})

    def test_sqlalchemy_postgres_url_is_normalized_for_psycopg(self):
        url = 'postgresql+psycopg://visionflow_app:secret@127.0.0.1:55432/visionflow?sslmode=disable'
        self.assertEqual(
            'postgresql://visionflow_app:secret@127.0.0.1:55432/visionflow?sslmode=disable',
            normalize_psycopg_dsn(url),
        )

    def test_standard_postgres_url_is_unchanged(self):
        url = 'postgresql://visionflow_app:secret@127.0.0.1:55432/visionflow'
        self.assertEqual(url, normalize_psycopg_dsn(url))
