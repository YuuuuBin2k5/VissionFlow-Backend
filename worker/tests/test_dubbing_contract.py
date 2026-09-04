import unittest

from worker.domain.dubbing_contract import (
    DUBBING_PACKAGE_VERSION,
    build_dubbing_workflow_package,
    legacy_seo_to_publish_metadata,
    record_timing_qc,
)


class DubbingContractTests(unittest.TestCase):
    def test_faithful_is_default_and_adaptation_is_opt_in(self):
        package = build_dubbing_workflow_package({"voice_code": "voice-a"}, source_asset_id="asset-1")
        self.assertEqual(DUBBING_PACKAGE_VERSION, package["version"])
        self.assertEqual("faithful", package["translation"]["mode"])
        self.assertFalse(package["enable_narration_cta"])
        self.assertFalse(package["enable_seamless_loop_adaptation"])
        self.assertEqual("asset-1", package["source"]["asset_id"])

    def test_legacy_seo_maps_without_inventing_branding(self):
        metadata = legacy_seo_to_publish_metadata({"title": "Title", "caption_seo": "Description", "hashtags": ["one"]})
        self.assertEqual("Title", metadata["youtube"]["title"])
        self.assertEqual(["one"], metadata["youtube"]["hashtags"])
        self.assertNotIn("pinned_comment", metadata["youtube"])

    def test_timing_qc_is_explicit(self):
        qc = record_timing_qc([{"duration": 1.0, "tts_duration": 1.2}])
        self.assertEqual("PASSED", qc["status"])
        self.assertEqual(0.2, qc["total_absolute_delta_seconds"])
