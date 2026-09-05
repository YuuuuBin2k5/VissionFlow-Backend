import unittest
from unittest.mock import patch
from fastapi import HTTPException
from app.routers.dubbing import _require_web_dubbing, dubbing_capabilities


class WebDubbingGateTests(unittest.TestCase):
    def test_default_is_off_and_rejects_intake(self):
        with patch.dict('os.environ', {}, clear=True):
            self.assertFalse(dubbing_capabilities()['web_dubbing_enabled'])
            with self.assertRaises(HTTPException) as error:
                _require_web_dubbing()
            self.assertEqual(503,error.exception.status_code)

    def test_explicit_dev_enable(self):
        with patch.dict('os.environ', {'ENABLE_WEB_DUBBING':'true'}):
            self.assertTrue(dubbing_capabilities()['web_dubbing_enabled'])
            _require_web_dubbing()
